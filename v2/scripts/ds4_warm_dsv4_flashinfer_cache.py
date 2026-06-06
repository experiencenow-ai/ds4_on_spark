#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
import re
import shlex
import subprocess
import sys
import time
from urllib.parse import urlparse


ROOT = Path(__file__).resolve().parents[1]
TOPOLOGY = ROOT / "profiles" / "topology" / "static_sparks.json"
DSV4_DEPLOYMENT = ROOT / "profiles" / "kv_cache" / "dsv4_flash_pp8_simple_offload.json"
SERVICE_ID = "dsv4_flash_pp8"
PEER_SERVICES = ("qwen27_bf16_pp8", "gemma4_26b_a4b_pp8")
COMPILER_NAMES = ("cicc", "cc1plus", "ptxas", "nvcc")
SECRET_RE = re.compile(r"([A-Za-z_][A-Za-z0-9_]*(?:TOKEN|SECRET|PASSWORD|KEY)[A-Za-z0-9_]*=)([^ ]+)")
COMPILE_ENV = {
    "DS4_FLASHINFER_JIT_MAX_JOBS": "1",
    "MAX_JOBS": "1",
    "CMAKE_BUILD_PARALLEL_LEVEL": "1",
    "TORCHINDUCTOR_COMPILE_THREADS": "1",
    "NVCC_THREADS": "1",
    "VLLM_DEEP_GEMM_WARMUP": "skip",
}


def main() -> int:
    args = _parse_args()
    topology = _load(args.topology)
    service = _service(topology, SERVICE_ID)
    nodes = [str(item) for item in service["node_ids"]]
    token = _load_token(args) if args.execute else _dry_token(args)
    plan = _plan(args, token=token)
    if not args.execute:
        _emit_plan(plan, args)
        return 0
    _run_plan([plan["fabric_check"]], args)
    _check_memory(nodes, args, phase="pre-warm")
    try:
        _run_plan(plan["peer_stop"], args)
        _run_plan([plan["dsv4_stop"], plan["dsv4_launch"]], args)
        _wait_models(service, args)
        _warm_completion(service, args)
    finally:
        if not args.keep_dsv4_running:
            _run_plan([plan["dsv4_stop"]], args, allow_fail=True)
        _cleanup_compilers(nodes, args)
        _check_memory(nodes, args, phase="post-warm")
    return 0


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Warm DSV4 native FlashInfer/CUDA JIT caches before first-three residency.")
    parser.add_argument("--execute", action="store_true")
    parser.add_argument("--topology", default=str(TOPOLOGY))
    parser.add_argument("--remote-repo", default="$HOME/src/ds4_on_spark")
    parser.add_argument("--token-file", default="/private/tmp/ds4_jit_kv_token")
    parser.add_argument("--prefetch-token", default=os.environ.get("DS4_API_JIT_KV_PREFETCH_TOKEN", ""))
    parser.add_argument("--prefetch-max-concurrent", type=int, default=4)
    parser.add_argument("--skip-stop-peers", action="store_true")
    parser.add_argument("--skip-fabric-check", action="store_true")
    parser.add_argument("--keep-dsv4-running", action="store_true")
    parser.add_argument("--ready-timeout-s", type=float, default=900.0)
    parser.add_argument("--ready-poll-s", type=float, default=5.0)
    parser.add_argument("--completion-timeout-s", type=float, default=300.0)
    parser.add_argument("--connect-timeout-s", type=int, default=8)
    parser.add_argument("--stagger-s", type=float, default=2.0)
    parser.add_argument("--min-available-ratio", type=float, default=0.10)
    parser.add_argument("--min-available-mib", type=int, default=12288)
    parser.add_argument("--json", action="store_true")
    return parser.parse_args()


def _plan(args: argparse.Namespace, *, token: str) -> dict[str, object]:
    remote_env = _warmup_remote_env(token, args)
    peer_stop = [] if args.skip_stop_peers else [_lifecycle_cmd(args, service, ["stop"]) for service in PEER_SERVICES]
    return {
        "fabric_check": _fabric_cmd(args),
        "peer_stop": peer_stop,
        "dsv4_stop": _lifecycle_cmd(args, SERVICE_ID, ["stop"]),
        "dsv4_launch": _lifecycle_cmd(args, SERVICE_ID, ["write-scripts", "launch"], remote_env=remote_env),
        "warm_probe": "poll spark0 /v1/models, then issue one-token DSV4 warm completion",
        "cleanup": f"kill leftover compiler workers by name: {','.join(COMPILER_NAMES)}",
    }


def _warmup_remote_env(token: str, args: argparse.Namespace) -> list[tuple[str, str]]:
    env = [
        ("VLLM_DS4_KV_PREFETCH_API", "1"),
        ("VLLM_DS4_KV_PREFETCH_REQUIRE_TOKEN", "1"),
        ("VLLM_DS4_KV_PREFETCH_TOKEN", token),
        ("VLLM_DS4_KV_PREFETCH_MAX_CONCURRENT", str(args.prefetch_max_concurrent)),
    ]
    env.extend(sorted(COMPILE_ENV.items()))
    return env


def _fabric_cmd(args: argparse.Namespace) -> list[str]:
    if args.skip_fabric_check:
        return []
    return [sys.executable, str(ROOT / "scripts" / "ds4_check_spark_fabric_routes.py"), "--nodes", "8", "--timeout-s", "30"]


def _lifecycle_cmd(args: argparse.Namespace, service: str, actions: list[str], *, remote_env: list[tuple[str, str]] | None = None) -> list[str]:
    cmd = [
        sys.executable,
        str(ROOT / "scripts" / "ds4_pipeline_lifecycle.py"),
        "--service",
        service,
        "--remote-repo",
        args.remote_repo,
        "--connect-timeout-s",
        str(args.connect_timeout_s),
        "--stagger-s",
        str(args.stagger_s),
    ]
    for key, value in remote_env or []:
        cmd.extend(["--remote-env", f"{key}={value}"])
    cmd.extend(actions)
    if args.execute:
        cmd.append("--execute")
    return cmd


def _emit_plan(plan: dict[str, object], args: argparse.Namespace) -> None:
    clean = _redact(plan)
    if args.json:
        print(json.dumps(clean, indent=2, sort_keys=True))
        return
    print("dry-run only; add --execute to warm DSV4 JIT caches")
    for key, value in clean.items():
        print(f"{key}: {value}")


def _run_plan(commands: list[list[str]], args: argparse.Namespace, *, allow_fail: bool = False) -> None:
    for cmd in commands:
        if not cmd:
            continue
        _run(cmd, allow_fail=allow_fail)


def _run(cmd: list[str], *, allow_fail: bool = False, capture: bool = False) -> subprocess.CompletedProcess[str]:
    print("+ " + " ".join(shlex.quote(_redact_text(item)) for item in cmd))
    result = subprocess.run(cmd, text=True, stdout=subprocess.PIPE if capture else None, stderr=subprocess.PIPE if capture else None, check=False)
    if result.returncode != 0 and not allow_fail:
        if capture:
            sys.stderr.write(result.stdout)
            sys.stderr.write(result.stderr)
        raise SystemExit(result.returncode)
    return result


def _wait_models(service: dict[str, object], args: argparse.Namespace) -> None:
    deadline = time.time() + args.ready_timeout_s
    url = str(service["api_base_url"]).rstrip("/") + "/v1/models"
    while time.time() < deadline:
        result = _remote_json("spark0", _models_code(), {"URL": url, "T": str(args.ready_poll_s)}, args)
        if result.get("ok") is True:
            print(json.dumps({"phase": "dsv4-models-ready", "models": result.get("models", [])}, sort_keys=True))
            return
        print(json.dumps({"phase": "dsv4-models-wait", "error": result.get("error", "not ready")}, sort_keys=True))
        time.sleep(max(1.0, args.ready_poll_s))
    raise SystemExit(f"DSV4 did not expose /v1/models within {args.ready_timeout_s}s")


def _warm_completion(service: dict[str, object], args: argparse.Namespace) -> None:
    deployment = _load(DSV4_DEPLOYMENT)
    base = str(service["api_base_url"]).rstrip("/")
    model = str(deployment.get("served_model_name") or "deepseek-v4-flash-pp8")
    result = _remote_json("spark0", _completion_code(), {"BASE": base, "MODEL": model, "T": str(args.completion_timeout_s)}, args, allow_fail=True)
    if result.get("ok") is not True:
        raise SystemExit(f"DSV4 warm completion failed: {result}")
    print(json.dumps({"phase": "dsv4-warm-completion", "path": result.get("path"), "status": result.get("status")}, sort_keys=True))


def _check_memory(nodes: list[str], args: argparse.Namespace, *, phase: str) -> None:
    rows = []
    for node in nodes:
        row = _remote_json(node, _memory_code(), {}, args)
        row["node"] = node
        row["phase"] = phase
        rows.append(row)
    failures = []
    for row in rows:
        ratio = float(row.get("available_ratio", 0.0))
        available = int(row.get("available_mib", 0))
        if ratio < args.min_available_ratio or available < args.min_available_mib:
            failures.append(row)
    print(json.dumps({"phase": phase, "memory": rows}, indent=2 if args.json else None, sort_keys=True))
    if failures:
        raise SystemExit(f"{phase}: Spark memory floor failed for {[row['node'] for row in failures]}")


def _cleanup_compilers(nodes: list[str], args: argparse.Namespace) -> None:
    code = _cleanup_code()
    for node in nodes:
        result = _remote_json(node, code, {"NAMES": json.dumps(COMPILER_NAMES, separators=(",", ":"))}, args, allow_fail=True)
        print(json.dumps({"phase": "compiler-cleanup", "node": node, "result": result}, sort_keys=True))


def _remote_json(node: str, code: str, env: dict[str, str], args: argparse.Namespace, *, allow_fail: bool = False) -> dict[str, object]:
    exports = " ".join(f"{key}={shlex.quote(value)}" for key, value in env.items())
    script = f"{exports} python3 -c {shlex.quote(code)}" if exports else f"python3 -c {shlex.quote(code)}"
    argv = ["ssh", "-o", "BatchMode=yes", "-o", f"ConnectTimeout={args.connect_timeout_s}", node, "bash -lc " + shlex.quote(script)]
    result = _run(argv, allow_fail=allow_fail, capture=True)
    text = (result.stdout or "").strip()
    if not text:
        return {"ok": False, "returncode": result.returncode, "stderr": (result.stderr or "").strip()}
    try:
        return json.loads(text.splitlines()[-1])
    except json.JSONDecodeError:
        return {"ok": False, "returncode": result.returncode, "stdout": text[-2000:], "stderr": (result.stderr or "").strip()}


def _models_code() -> str:
    return "import json,os,urllib.request\ntry:\n r=urllib.request.urlopen(os.environ['URL'],timeout=float(os.environ['T']));data=json.loads(r.read().decode('utf-8'));print(json.dumps({'ok':True,'status':r.status,'models':[m.get('id') for m in data.get('data',[])]},sort_keys=True))\nexcept Exception as e:\n print(json.dumps({'ok':False,'error':str(e)},sort_keys=True))"


def _completion_code() -> str:
    return "import json,os,urllib.request\nbase=os.environ['BASE'].rstrip('/');model=os.environ['MODEL'];timeout=float(os.environ['T'])\ndef post(path,payload):\n req=urllib.request.Request(base+path,data=json.dumps(payload).encode('utf-8'),headers={'Content-Type':'application/json'})\n r=urllib.request.urlopen(req,timeout=timeout);body=r.read(512).decode('utf-8','replace');print(json.dumps({'ok':True,'path':path,'status':r.status,'body':body},sort_keys=True));raise SystemExit(0)\nerrors=[]\nfor path,payload in [('/v1/completions',{'model':model,'prompt':'warmup','max_tokens':1,'temperature':0,'stream':False}),('/v1/chat/completions',{'model':model,'messages':[{'role':'user','content':'warmup'}],'max_tokens':1,'temperature':0,'stream':False})]:\n try:\n  post(path,payload)\n except SystemExit:\n  raise\n except Exception as e:\n  errors.append({'path':path,'error':str(e)})\nprint(json.dumps({'ok':False,'errors':errors},sort_keys=True));raise SystemExit(1)"


def _memory_code() -> str:
    return "import json,subprocess\nout=subprocess.run(['free','-m'],text=True,stdout=subprocess.PIPE,check=True).stdout.splitlines();parts=out[1].split();total=int(parts[1]);available=int(parts[6]);swap=out[2].split() if len(out)>2 else ['Swap:','0','0','0'];print(json.dumps({'ok':True,'total_mib':total,'available_mib':available,'available_ratio':round(available/max(total,1),4),'swap_used_mib':int(swap[2])},sort_keys=True))"


def _cleanup_code() -> str:
    return "import json,os,signal,subprocess\nnames=set(json.loads(os.environ['NAMES']));killed=[]\nfor line in subprocess.run(['ps','-eo','pid=,comm='],text=True,stdout=subprocess.PIPE).stdout.splitlines():\n parts=line.strip().split(None,1)\n if len(parts)==2 and parts[1] in names:\n  pid=int(parts[0])\n  try:\n   os.kill(pid,signal.SIGKILL);killed.append(pid)\n  except ProcessLookupError:\n   pass\nprint(json.dumps({'ok':True,'killed':killed},sort_keys=True))"


def _load_token(args: argparse.Namespace) -> str:
    token = str(args.prefetch_token or "").strip()
    if token:
        return token
    path = Path(args.token_file)
    if path.exists():
        token = path.read_text(encoding="utf-8").strip()
    if not token:
        raise SystemExit("DSV4 warmup requires --prefetch-token, DS4_API_JIT_KV_PREFETCH_TOKEN, or --token-file")
    return token


def _dry_token(args: argparse.Namespace) -> str:
    return str(args.prefetch_token or "<required-at-execute>")


def _service(topology: dict[str, object], service_id: str) -> dict[str, object]:
    routing = topology.get("routing_policy") if isinstance(topology.get("routing_policy"), dict) else {}
    services = routing.get("pipeline_services") if isinstance(routing.get("pipeline_services"), dict) else {}
    service = services.get(service_id)
    if not isinstance(service, dict):
        raise SystemExit(f"missing pipeline service: {service_id}")
    parsed = urlparse(str(service.get("api_base_url", "")))
    if parsed.port is None:
        raise SystemExit(f"{service_id}: api_base_url must include a port")
    return service


def _load(path: str | Path) -> dict[str, object]:
    return json.loads(Path(path).read_text(encoding="utf-8"))


def _redact(value: object) -> object:
    if isinstance(value, dict):
        return {key: _redact(item) for key, item in value.items()}
    if isinstance(value, list):
        return [_redact(item) for item in value]
    if isinstance(value, str):
        return _redact_text(value)
    return value


def _redact_text(text: str) -> str:
    return SECRET_RE.sub(r"\1<redacted>", text)


if __name__ == "__main__":
    raise SystemExit(main())
