#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
import subprocess
import sys
import time
from urllib import request


ROOT = Path(__file__).resolve().parents[1]
DSV4_PRODUCTION_PROFILE = ROOT / "profiles" / "production" / "dsv4_flash_pp8_resident128.json"
FIRST3_MEMORY_BUDGET = ROOT / "profiles" / "production" / "first3_resident_memory_budget.json"
STATIC_SPARKS_TOPOLOGY = ROOT / "profiles" / "topology" / "static_sparks.json"
DEFAULT_COORDINATOR_PYTHON = Path("/home/spark0/ds4-vllm-local/bin/python")
DEFAULT_PREFETCH_TOKEN_FILE = Path("/private/tmp/ds4_jit_kv_token")


def main() -> int:
    args = _parse_args()
    script_path = Path(__file__).resolve()
    v2_dir = script_path.parents[1]
    repo_dir = v2_dir.parent
    if not args.skip_pull:
        _run(["git", "pull", "--ff-only", "origin", args.branch], cwd=repo_dir)
    if not args.skip_build:
        _build(repo_dir, v2_dir, skip_tests=args.skip_tests)
    _run([sys.executable, str(script_path.with_name("ds4_stop_coordinator_api.py")), "--timeout-s", str(args.stop_timeout_s)], cwd=v2_dir)
    log_path = _log_path(args.log_path)
    log_path.parent.mkdir(parents=True, exist_ok=True)
    env = _coordinator_env(args, v2_dir)
    coordinator_python = _coordinator_python(args)
    argv = [
        coordinator_python,
        "-m",
        "ds4_infer.api",
        "--host",
        args.host,
        "--port",
        str(args.port),
        "--queue-dir",
        args.queue_dir,
        "--profiles-dir",
        args.profiles_dir,
        "--topology",
        args.topology,
        "--runner-kind",
        args.runner_kind,
    ]
    with log_path.open("ab") as log_handle:
        process = subprocess.Popen(argv, cwd=v2_dir, env=env, stdin=subprocess.DEVNULL, stdout=log_handle, stderr=subprocess.STDOUT, start_new_session=True)
    _pid_path(args.pid_file).write_text(str(process.pid) + "\n", encoding="utf-8")
    print(f"ds4 coordinator relaunch: started pid={process.pid} log={log_path}")
    if not _wait_health(args.port, timeout_s=args.health_timeout_s, poll_s=args.health_poll_s):
        print(f"ds4 coordinator relaunch: health check failed; see {log_path}")
        return 1
    print("ds4 coordinator relaunch: healthy")
    return 0


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Pull, build, stop, and relaunch the spark0 DS4 coordinator API.")
    parser.add_argument("--branch", default="main")
    parser.add_argument("--skip-pull", action="store_true")
    parser.add_argument("--skip-build", action="store_true")
    parser.add_argument("--skip-tests", action="store_true")
    parser.add_argument("--profile", choices=("throughput", "production", "resident128", "resident256"), default="resident128")
    parser.add_argument("--env", action="append", default=[], metavar="KEY=VALUE", help="Extra coordinator environment override; repeatable.")
    parser.add_argument("--prefetch-token-file", default=os.environ.get("DS4_API_JIT_KV_PREFETCH_TOKEN_FILE", str(DEFAULT_PREFETCH_TOKEN_FILE)), help="Token file used when DS4 JIT KV prefetch API is enabled.")
    parser.add_argument("--host", default=os.environ.get("HOST", "0.0.0.0"))
    parser.add_argument("--port", type=int, default=int(os.environ.get("PORT", "8700") or "8700"))
    parser.add_argument("--queue-dir", default=os.environ.get("QUEUE_DIR", str(Path.home() / "ds4_queue")))
    parser.add_argument("--profiles-dir", default=os.environ.get("PROFILES_DIR", "profiles/models"))
    parser.add_argument("--topology", default=os.environ.get("TOPOLOGY", "profiles/topology/static_sparks.json"))
    parser.add_argument("--runner-kind", default=os.environ.get("RUNNER_KIND", "pipeline"))
    parser.add_argument("--coordinator-python", default=os.environ.get("DS4_COORDINATOR_PYTHON", ""), help="Python executable for the long-running coordinator process.")
    parser.add_argument("--log-path", default=os.environ.get("DS4_COORDINATOR_LOG", ""))
    parser.add_argument("--pid-file", default=os.environ.get("DS4_COORDINATOR_PID_FILE", ""))
    parser.add_argument("--stop-timeout-s", type=float, default=8.0)
    parser.add_argument("--health-timeout-s", type=float, default=30.0)
    parser.add_argument("--health-poll-s", type=float, default=0.5)
    return parser.parse_args()


def _coordinator_python(args: argparse.Namespace, *, default_path: Path = DEFAULT_COORDINATOR_PYTHON) -> str:
    requested = str(getattr(args, "coordinator_python", "") or "").strip()
    if requested:
        return requested
    if default_path.exists():
        return str(default_path)
    return sys.executable


def _build(repo_dir: Path, v2_dir: Path, *, skip_tests: bool) -> None:
    makefile = repo_dir / "Makefile"
    v2_makefile = v2_dir / "Makefile"
    if makefile.exists():
        _run(["make"], cwd=repo_dir)
    elif v2_makefile.exists():
        _run(["make"], cwd=v2_dir)
    else:
        _run([sys.executable, "-m", "compileall", "-q", "src"], cwd=v2_dir, extra_env={"PYTHONPATH": str(v2_dir / "src")})
        if not skip_tests:
            _run([sys.executable, "-m", "unittest", "tests.test_pipeline_coalesced_dispatch", "-v"], cwd=v2_dir, extra_env={"PYTHONPATH": str(v2_dir / "src")})


def _coordinator_env(args: argparse.Namespace, v2_dir: Path) -> dict[str, str]:
    env = dict(os.environ)
    env["PYTHONPATH"] = str(v2_dir / "src") if not env.get("PYTHONPATH") else f"{v2_dir / 'src'}:{env['PYTHONPATH']}"
    defaults = _profile_defaults(args.profile)
    for key, value in defaults.items():
        if key in _SAFETY_PROFILE_DEFAULTS:
            env[key] = value
        else:
            env.setdefault(key, value)
    for key, value in _parse_env_overrides(getattr(args, "env", []) or []).items():
        env[key] = value
    if _truthy(env.get("DS4_API_JIT_KV_PREFETCH_API")) and not env.get("DS4_API_JIT_KV_PREFETCH_TOKEN"):
        token = _load_prefetch_token(getattr(args, "prefetch_token_file", str(DEFAULT_PREFETCH_TOKEN_FILE)))
        if not token:
            raise ValueError("DS4_API_JIT_KV_PREFETCH_API=1 requires DS4_API_JIT_KV_PREFETCH_TOKEN, --env DS4_API_JIT_KV_PREFETCH_TOKEN=..., or --prefetch-token-file")
        env["DS4_API_JIT_KV_PREFETCH_TOKEN"] = token
    return env


_SAFETY_PROFILE_DEFAULTS = {
    "DS4_API_DISPATCH_COHORT_WORKERS",
    "DS4_API_DISPATCH_KV_CAPACITY_BYTES",
    "DS4_API_RENDER_CHAT_WITH_TOKENIZER",
    "DS4_API_REQUIRE_TOKENIZER_CHAT_RENDER",
    "DS4_API_RESIDENT_MULTIMODEL",
    "DS4_API_RESIDENT_SERVICE_IDS",
    "DS4_API_TRANSPORT_MAX_ATTEMPTS",
    "DS4_API_JIT_KV_RECOVER_ON_STARTUP",
    "DS4_API_JIT_KV_RECOVERY_STALE_S",
    "DS4_API_JIT_KV_CIRCUIT_BREAKER",
    "DS4_API_JIT_KV_CIRCUIT_WINDOW_S",
    "DS4_API_JIT_KV_CIRCUIT_MIN_SAMPLES",
    "DS4_API_JIT_KV_CIRCUIT_FAILURE_RATIO",
    "DS4_API_JIT_KV_CIRCUIT_COOLDOWN_S",
    "DS4_COMPUTE_LEASE_QUANTUM_S",
    "DS4_PIPELINE_INTERNAL_STREAM_ALL_COHORTS",
    "DS4_PIPELINE_COMPLETION_COHORT_TOKEN_BUDGET",
    "DS4_PIPELINE_COMPLETION_BISECT_ON_FAILURE",
    "DS4_PIPELINE_COMPLETION_PP_SAFE_COHORT_MAX",
    "DS4_PIPELINE_COMPLETION_CHUNK_CONCURRENCY",
    "DS4_PIPELINE_COMPLETION_COHORT_BUDGET_INCLUDE_OUTPUT",
    "DS4_PIPELINE_COMPLETION_USE_TOKEN_HINTS",
    "DS4_PIPELINE_COMPLETION_TOKEN_ESTIMATE_MODE",
    "DS4_PIPELINE_COMPLETION_STREAM_WALL_TIMEOUT_S",
}


def _profile_defaults(profile: str) -> dict[str, str]:
    dsv4 = _load_dsv4_production_profile()
    common = _common_profile_defaults(dsv4)
    if profile in {"throughput", "production", "resident128", "resident256"}:
        common.update(_dsv4_profile_defaults(dsv4, profile))
    return common


def _common_profile_defaults(dsv4: dict[str, object]) -> dict[str, str]:
    return {
        "DS4_API_BACKGROUND_DISPATCH": "1",
        "DS4_API_DISPATCH_COHORT_WORKERS": "16",
        "DS4_API_RENDER_CHAT_WITH_TOKENIZER": "1",
        "DS4_API_REQUIRE_TOKENIZER_CHAT_RENDER": "1",
        "DS4_API_RESIDENT_MULTIMODEL": "1",
        "DS4_API_RESIDENT_SERVICE_IDS": "qwen27_bf16_pp8,gemma4_26b_a4b_pp8,dsv4_flash_pp8",
        "DS4_API_DEPLOYMENT_STRICT": "0",
        "DS4_API_JIT_KV_PREFETCH_API": "0",
        "DS4_API_JIT_KV_RECOVER_ON_STARTUP": "1",
        "DS4_API_JIT_KV_RECOVERY_STALE_S": "0",
        "DS4_API_JIT_KV_CIRCUIT_BREAKER": "1",
        "DS4_API_JIT_KV_CIRCUIT_WINDOW_S": "60",
        "DS4_API_JIT_KV_CIRCUIT_MIN_SAMPLES": "8",
        "DS4_API_JIT_KV_CIRCUIT_FAILURE_RATIO": "0.5",
        "DS4_API_JIT_KV_CIRCUIT_COOLDOWN_S": "120",
        "DS4_PIPELINE_COHORT_COMPLETIONS": "1",
        "DS4_PIPELINE_INTERNAL_STREAM_ALL_COHORTS": "1",
        "DS4_PIPELINE_COMPLETION_COHORT_TOKEN_BUDGET": "32768",
        "DS4_PIPELINE_COMPLETION_BISECT_ON_FAILURE": "1",
        "DS4_PIPELINE_COMPLETION_PP_SAFE_COHORT_MAX": "128",
        "DS4_PIPELINE_COMPLETION_CHUNK_CONCURRENCY": "1",
        "DS4_PIPELINE_COMPLETION_STREAM_WALL_TIMEOUT_S": "600",
        "DS4_PIPELINE_COMPLETION_USE_TOKEN_HINTS": "1",
        "DS4_PIPELINE_COMPLETION_TOKEN_ESTIMATE_MODE": "conservative",
        "DS4_COMPUTE_LEASE_QUANTUM_S": "180",
        "DS4_API_TRANSPORT_TIMEOUT_S": "3600",
        "DS4_API_TRANSPORT_MAX_ATTEMPTS": "1",
        "DS4_API_DISPATCH_KV_CAPACITY_BYTES": str(dsv4["coordinator"]["dispatch_kv_capacity_bytes"]),
    }


def _dsv4_profile_defaults(dsv4: dict[str, object], profile: str) -> dict[str, str]:
    coordinator = dict(_load_first3_memory_budget().get("coordinator") or {})
    if profile == "resident256":
        coordinator.update(
            {
                "dispatch_window": 256,
                "dispatch_refill_batch": 256,
                "completion_cohort_max": 256,
                "completion_token_budget": 98304,
                "completion_pp_safe_cohort_max": 256,
                "completion_chunk_concurrency": 4,
            }
        )
    return {
        "DS4_API_DISPATCH_WINDOW": str(coordinator["dispatch_window"]),
        "DS4_API_DISPATCH_REFILL_BATCH": str(coordinator["dispatch_refill_batch"]),
        "DS4_API_DISPATCH_BATCH_LINGER_S": "0.05",
        "DS4_PIPELINE_COMPLETION_COHORT_MAX": str(coordinator["completion_cohort_max"]),
        "DS4_PIPELINE_COMPLETION_COHORT_TOKEN_BUDGET": str(coordinator["completion_token_budget"]),
        "DS4_PIPELINE_COMPLETION_PP_SAFE_COHORT_MAX": str(coordinator["completion_pp_safe_cohort_max"]),
        "DS4_PIPELINE_COMPLETION_CHUNK_CONCURRENCY": str(coordinator["completion_chunk_concurrency"]),
        "DS4_API_DISPATCH_KV_CAPACITY_BYTES": str(coordinator["dispatch_kv_capacity_bytes"]),
        "DS4_API_BATCH_LIMITS_JSON": json.dumps(_pipeline_batch_limits(overrides={str(dsv4["service_id"]): int(dsv4["max_num_seqs"])}), separators=(",", ":")),
    }


def _load_dsv4_production_profile() -> dict[str, object]:
    return json.loads(DSV4_PRODUCTION_PROFILE.read_text(encoding="utf-8"))


def _load_first3_memory_budget() -> dict[str, object]:
    return json.loads(FIRST3_MEMORY_BUDGET.read_text(encoding="utf-8"))


def _pipeline_batch_limits(*, topology_path: Path = STATIC_SPARKS_TOPOLOGY, overrides: dict[str, int] | None = None) -> dict[str, int]:
    topology = json.loads(topology_path.read_text(encoding="utf-8"))
    routing = topology.get("routing_policy") if isinstance(topology.get("routing_policy"), dict) else {}
    services = routing.get("pipeline_services") if isinstance(routing.get("pipeline_services"), dict) else {}
    limits: dict[str, int] = {}
    for service_id, service in services.items():
        if not isinstance(service, dict):
            continue
        scheduler = service.get("scheduler") if isinstance(service.get("scheduler"), dict) else {}
        raw = scheduler.get("vllm_max_num_seqs") or service.get("max_batch_size") or scheduler.get("queue_limit")
        if raw is None:
            continue
        limits[str(service_id)] = int(raw)
    limits.update(overrides or {})
    return dict(sorted(limits.items()))


def _parse_env_overrides(items: list[str]) -> dict[str, str]:
    out: dict[str, str] = {}
    for item in items:
        if "=" not in item:
            raise ValueError(f"--env must be KEY=VALUE, got {item!r}")
        key, value = item.split("=", 1)
        key = key.strip()
        if not key:
            raise ValueError(f"--env key must not be empty, got {item!r}")
        out[key] = value
    return out


def _truthy(value: object) -> bool:
    return str(value or "").strip().lower() in {"1", "true", "yes", "on"}


def _load_prefetch_token(raw_path: str) -> str:
    if not raw_path:
        return ""
    path = Path(raw_path).expanduser()
    if not path.exists():
        return ""
    return path.read_text(encoding="utf-8").strip()


def _log_path(raw: str) -> Path:
    if raw:
        return Path(raw).expanduser()
    stamp = time.strftime("%Y%m%dT%H%M%SZ", time.gmtime())
    return Path.home() / "ds4_logs" / f"ds4_coordinator_api_{stamp}.log"


def _pid_path(raw: str) -> Path:
    if raw:
        path = Path(raw).expanduser()
    else:
        path = Path.home() / "ds4_logs" / "ds4_coordinator_api.pid"
    path.parent.mkdir(parents=True, exist_ok=True)
    return path


def _wait_health(port: int, *, timeout_s: float, poll_s: float) -> bool:
    deadline = time.time() + max(0.0, timeout_s)
    url = f"http://127.0.0.1:{port}/ds4/dispatcher/status"
    while time.time() < deadline:
        try:
            with request.urlopen(url, timeout=max(0.2, min(2.0, poll_s))) as response:
                data = json.loads(response.read().decode("utf-8"))
            if data.get("running") is True:
                return True
        except Exception:
            time.sleep(max(0.1, poll_s))
    return False


def _run(argv: list[str], *, cwd: Path, extra_env: dict[str, str] | None = None) -> None:
    env = dict(os.environ)
    env.update(extra_env or {})
    print(f"+ {' '.join(argv)}")
    subprocess.run(argv, cwd=cwd, env=env, check=True)


if __name__ == "__main__":
    raise SystemExit(main())
