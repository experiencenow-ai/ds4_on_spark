#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
from pathlib import Path
import re
import shlex
import subprocess
import sys
import time
from urllib.parse import urlparse

SCRIPT_DIR = Path(__file__).resolve().parent
if str(SCRIPT_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPT_DIR))
from ds4_prefetch_token import DEFAULT_PREFETCH_TOKEN_FILE, load_prefetch_token


ROOT = Path(__file__).resolve().parents[1]
REPO = ROOT.parent
TOPOLOGY = ROOT / "profiles" / "topology" / "static_sparks.json"
PROFILES = ROOT / "profiles" / "models"
SECRET_ASSIGN_RE = re.compile(r"([A-Za-z_][A-Za-z0-9_]*(?:TOKEN|SECRET|PASSWORD|KEY)[A-Za-z0-9_]*=)(?:'[^']*'|\"[^\"]*\"|[^ \n]+)")


def main() -> int:
    args = _args()
    entries = _select_entries(_load_entries(args.topology, args.profiles_dir), args.service)
    actions = _expand_actions(args.actions)
    if _is_dangerous_all_services(args, actions):
        raise SystemExit("refusing mutating --service all --execute; pass --allow-all-services only for planned fleet-wide maintenance")
    if any(item in {"pull", "stop", "write-scripts", "launch"} for item in actions) and not args.execute:
        for entry in entries:
            print(f"plan {entry['service_id']}: actions={','.join(actions)} nodes={','.join(entry['node_ids'])} deployment={entry['deployment_rel']}")
        print("dry-run only; add --execute to run side-effecting lifecycle actions")
        return 0
    for action in actions:
        _run_action(action, entries, args)
    return 0


def _args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Shared DS4 resident pipeline lifecycle runner.")
    parser.add_argument("actions", nargs="+", choices=("list", "audit", "status", "pull", "stop", "write-scripts", "launch", "probe", "relaunch"))
    parser.add_argument("--service", default="all")
    parser.add_argument("--topology", default=str(TOPOLOGY))
    parser.add_argument("--profiles-dir", default=str(PROFILES))
    parser.add_argument("--remote-repo", default="$HOME/src/ds4_on_spark")
    parser.add_argument("--launch-root", default="$HOME/.cache/ds4_pipeline_lifecycle")
    parser.add_argument("--log-dir", default="$HOME/ds4_logs/pipeline_lifecycle")
    parser.add_argument("--connect-timeout-s", type=int, default=8)
    parser.add_argument("--probe-timeout-s", type=float, default=15.0)
    parser.add_argument("--stagger-s", type=float, default=2.0)
    parser.add_argument("--remote-env", action="append", default=[], metavar="KEY=VALUE", help="export KEY=VALUE before launch scripts on each Spark node")
    parser.add_argument("--remote-arg", action="append", default=[], metavar="ARG", help="append ARG to each generated vLLM launch command before starting it")
    parser.add_argument("--remote-remove-arg", action="append", default=[], metavar="OPTION", help="remove an OPTION and its value from each generated vLLM launch command before starting it")
    parser.add_argument("--remote-set-arg", action="append", nargs=2, default=[], metavar=("OPTION", "VALUE"), help="set or replace an OPTION VALUE pair in each generated vLLM launch command before starting it")
    parser.add_argument("--remote-set-arg-kv", action="append", default=[], metavar="OPTION=VALUE", help="set or replace an OPTION VALUE pair; use this when OPTION starts with --")
    parser.add_argument("--prefetch-token-file", default=str(DEFAULT_PREFETCH_TOKEN_FILE), help="Local token file to inject into token-gated vLLM DS4 KV prefetch services; falls back to /tmp on Linux.")
    parser.add_argument("--execute", action="store_true")
    parser.add_argument("--allow-all-services", action="store_true")
    parser.add_argument("--json", action="store_true")
    return parser.parse_args()


def _expand_actions(actions: list[str]) -> list[str]:
    out: list[str] = []
    for action in actions:
        out.extend(["pull", "stop", "write-scripts", "launch", "probe"] if action == "relaunch" else [action])
    return out


def _is_dangerous_all_services(args: argparse.Namespace, actions: list[str]) -> bool:
    mutating = {"pull", "stop", "write-scripts", "launch"}
    return bool(args.execute and args.service == "all" and not args.allow_all_services and any(action in mutating for action in actions))


def _load_entries(topology_path: str, profiles_dir: str) -> list[dict[str, object]]:
    topology_file = _resolve_input_path(topology_path)
    profiles_path = _resolve_input_path(profiles_dir)
    topology = _load(topology_file)
    profiles = {str(data["profile_id"]): (path, data) for path, data in _profile_items(profiles_path)}
    services = topology["routing_policy"]["pipeline_services"]
    entries = []
    for service_id, service in services.items():
        profile_path, profile = profiles[str(service["profile_id"])]
        deployments = profile.get("routing", {}).get("optional_kv_cache_deployments", [])
        if len(deployments) != 1:
            raise ValueError(f"{service_id}: expected exactly one optional_kv_cache_deployment")
        deployment_rel = str(deployments[0])
        deployment = _load(ROOT / deployment_rel)
        port = urlparse(str(service["api_base_url"])).port
        if port is None:
            raise ValueError(f"{service_id}: api_base_url must include a port")
        entries.append({
            "service_id": str(service_id),
            "profile_id": str(service["profile_id"]),
            "model_id": str(service["model_id"]),
            "entry_node_id": str(service["entry_node_id"]),
            "node_ids": [str(node) for node in service["node_ids"]],
            "api_base_url": str(service["api_base_url"]),
            "http_port": int(port),
            "deployment_rel": deployment_rel,
            "profile_path": str(profile_path.relative_to(ROOT)),
            "service": service,
            "profile": profile,
            "deployment": deployment,
        })
    return sorted(entries, key=lambda item: str(item["service_id"]))


def _resolve_input_path(path: str) -> Path:
    item = Path(path)
    if not item.is_absolute():
        item = Path.cwd() / item
    return item.resolve()


def _profile_items(profiles_dir: Path) -> list[tuple[Path, dict[str, object]]]:
    return [(path, _load(path)) for path in sorted(profiles_dir.glob("*.json"))]


def _select_entries(entries: list[dict[str, object]], selector: str) -> list[dict[str, object]]:
    if selector == "all":
        return entries
    selected = [entry for entry in entries if selector in {entry["service_id"], entry["profile_id"], entry["model_id"]}]
    if not selected:
        raise ValueError(f"unknown pipeline service/profile/model: {selector}")
    return selected


def _run_action(action: str, entries: list[dict[str, object]], args: argparse.Namespace) -> None:
    if action == "list":
        _emit(entries, args)
    elif action == "audit":
        _audit(entries, args)
    elif action == "status":
        _status(entries, args)
    elif action == "pull":
        _local([str(REPO / "scripts" / "ds4_update_spark_nodes.sh"), "--code-only", *_nodes(entries)])
    elif action == "stop":
        for entry in entries:
            for node in entry["node_ids"]:
                _ssh(str(node), _remote_kill(entry), args)
    elif action == "write-scripts":
        for entry in entries:
            for node in entry["node_ids"]:
                _ssh(str(node), _remote_write(entry, args), args)
    elif action == "launch":
        for entry in entries:
            ranks = [(i, node) for i, node in enumerate(entry["node_ids"])]
            ranks = [item for item in ranks if item[1] != entry["entry_node_id"]] + [item for item in ranks if item[1] == entry["entry_node_id"]]
            for rank, node in ranks:
                _ssh(str(node), _remote_launch(entry, rank, str(node), args), args)
                time.sleep(max(0.0, args.stagger_s))
    elif action == "probe":
        _probe(entries, args)
    else:
        raise AssertionError(action)


def _emit(entries: list[dict[str, object]], args: argparse.Namespace) -> None:
    rows = [{key: entry[key] for key in ("service_id", "profile_id", "model_id", "entry_node_id", "node_ids", "api_base_url", "http_port", "deployment_rel", "profile_path")} for entry in entries]
    if args.json:
        print(json.dumps(rows, indent=2, sort_keys=True))
        return
    print("service profile port deployment nodes")
    for entry in rows:
        print(f"{entry['service_id']} {entry['profile_id']} {entry['http_port']} {entry['deployment_rel']} {','.join(entry['node_ids'])}")


def _audit(entries: list[dict[str, object]], args: argparse.Namespace) -> None:
    errors, checks = [], []
    for entry in entries:
        dep = entry["deployment"]
        nodes = dep.get("pipeline_nodes") or dep.get("worker_nodes") or [dep.get("spark_node")]
        _check(str(entry["profile"].get("routing", {}).get("pipeline", {}).get("service_id")) == entry["service_id"], f"{entry['service_id']}: profile pipeline id matches topology", errors, checks)
        _check(str(dep.get("profile_id")) == entry["profile_id"], f"{entry['service_id']}: KV deployment profile id matches", errors, checks)
        _check([str(node) for node in nodes] == entry["node_ids"], f"{entry['service_id']}: KV deployment nodes match topology", errors, checks)
        _check(int(dep.get("http_port", 0)) == entry["http_port"], f"{entry['service_id']}: KV deployment port matches topology", errors, checks)
        _check("{node}/src/ds4_on_spark/v2" in str(dep.get("working_directory", "")), f"{entry['service_id']}: KV deployment uses standard source checkout", errors, checks)
        _check("{node}/src/ds4_on_spark/v2/src" in str(dep.get("pythonpath", "")), f"{entry['service_id']}: KV deployment uses standard source PYTHONPATH", errors, checks)
        _check(str(dep.get("python_bin")) not in {"python3", "vllm"}, f"{entry['service_id']}: KV deployment python_bin is explicit", errors, checks)
        _check(str(dep.get("vllm_bin")) not in {"python3", "vllm"}, f"{entry['service_id']}: KV deployment vllm_bin is explicit", errors, checks)
        _check(str(dep.get("master_addr")) != entry["entry_node_id"], f"{entry['service_id']}: KV deployment master_addr avoids management hostname", errors, checks)
        service_kv = entry["service"].get("kv_cache") if isinstance(entry["service"].get("kv_cache"), dict) else {}
        deployment_connector = dep.get("connector") if isinstance(dep.get("connector"), dict) else {}
        if service_kv.get("connector_id"):
            _check(str(service_kv.get("connector_id")) == str(deployment_connector.get("connector_id")), f"{entry['service_id']}: topology connector matches KV deployment", errors, checks)
        if service_kv.get("cache_root"):
            directories = dep.get("cache_directories") if isinstance(dep.get("cache_directories"), list) else []
            _check(bool(directories) and str(directories[0]) == str(service_kv.get("cache_root")), f"{entry['service_id']}: topology cache root matches KV deployment", errors, checks)
    if args.json:
        print(json.dumps({"ok": not errors, "checks": checks, "errors": errors}, indent=2, sort_keys=True))
    else:
        for line in errors:
            print(f"FAIL: {line}")
        for line in checks:
            print(f"PASS: {line}")
    if errors:
        raise SystemExit(1)


def _check(ok: bool, label: str, errors: list[str], checks: list[str]) -> None:
    (checks if ok else errors).append(label)


def _status(entries: list[dict[str, object]], args: argparse.Namespace) -> None:
    rows = []
    for entry in entries:
        for node in entry["node_ids"]:
            result = _ssh(str(node), _remote_status(entry), args, capture=True)
            rows.append({"service_id": entry["service_id"], "node_id": node, "ok": result.returncode == 0, "out": result.stdout.strip(), "err": result.stderr.strip()})
    _emit_rows(rows, args)


def _probe(entries: list[dict[str, object]], args: argparse.Namespace) -> None:
    rows = []
    for entry in entries:
        url = f"http://127.0.0.1:{entry['http_port']}/v1/models"
        code = "import json,os,urllib.request\nu=os.environ['U'];t=float(os.environ['T'])\ntry:\n r=urllib.request.urlopen(u,timeout=t);print(json.dumps({'ok':True,'status':r.status,'body':r.read(512).decode('utf-8','replace')}))\nexcept Exception as e:\n print(json.dumps({'ok':False,'error':str(e)}))"
        result = _ssh(str(entry["entry_node_id"]), f"U={shlex.quote(url)} T={args.probe_timeout_s} python3 -c {shlex.quote(code)}", args, capture=True)
        rows.append({"service_id": entry["service_id"], "url": url, "ok": _probe_result_ok(result), "out": result.stdout.strip(), "err": result.stderr.strip()})
    _emit_rows(rows, args)
    if any(not row["ok"] for row in rows):
        raise SystemExit(1)


def _probe_result_ok(result: subprocess.CompletedProcess[str]) -> bool:
    if result.returncode != 0:
        return False
    try:
        body = json.loads(result.stdout.strip())
    except json.JSONDecodeError:
        return False
    return body.get("ok") is True


def _emit_rows(rows: list[dict[str, object]], args: argparse.Namespace) -> None:
    if args.json:
        print(json.dumps(rows, indent=2, sort_keys=True))
    else:
        for row in rows:
            print(" ".join(f"{key}={value}" for key, value in row.items()))


def _remote_write(entry: dict[str, object], args: argparse.Namespace) -> str:
    launch_dir = _remote_path_assign("launch_dir", args.launch_root, str(entry["service_id"]))
    return _repo(args) + f'\n{launch_dir}\nmkdir -p "$launch_dir"\nDS4_PIPELINE_LIFECYCLE=1 PYTHONPATH=src python3 -m ds4_kvcache.cli write-scripts --deployment {shlex.quote(str(entry["deployment_rel"]))} --output-dir "$launch_dir"'


def _remote_launch(entry: dict[str, object], rank: int, node: str, args: argparse.Namespace) -> str:
    stamp = time.strftime("%Y%m%dT%H%M%SZ", time.gmtime())
    log_dir = _remote_path_assign("log_dir", args.log_dir, str(entry["service_id"]))
    env_exports = _remote_env_exports(entry, args)
    if env_exports:
        env_exports = "\n" + env_exports
    script_overrides = _remote_launch_script_env_override(args)
    if script_overrides:
        script_overrides = "\n" + script_overrides
    return _remote_write(entry, args) + f'\n{log_dir}{env_exports}\ninstall="$launch_dir/00_install_kv_cache_deps.sh"\nscript="$launch_dir/start_vllm_rank{rank}_{node}.sh"\nlog="$log_dir/rank{rank}_{stamp}.log"\nmkdir -p "$log_dir"\ntest -x "$install"\ntest -x "$script"{script_overrides}\nDS4_NODE_ID={shlex.quote(node)} bash "$install"\nnohup bash "$script" > "$log" 2>&1 < /dev/null &\nprintf "started {entry["service_id"]} rank={rank} node={node} pid=%s log=%s\\n" "$!" "$log"'


def _remote_env_exports(entry: dict[str, object], args: argparse.Namespace) -> str:
    lines = []
    pairs = _parse_remote_env(getattr(args, "remote_env", []) or [])
    keys = {key for key, _value in pairs}
    if _entry_needs_prefetch_token(entry) and "VLLM_DS4_KV_PREFETCH_TOKEN" not in keys:
        pairs.append(("VLLM_DS4_KV_PREFETCH_TOKEN", _required_prefetch_token(args, service_id=str(entry["service_id"]))))
    for key, value in pairs:
        lines.append(f"export {key}={shlex.quote(value)}")
    return "\n".join(lines)


def _remote_launch_script_env_override(args: argparse.Namespace) -> str:
    pairs = _parse_remote_env(getattr(args, "remote_env", []) or [])
    remote_args = _parse_remote_args(getattr(args, "remote_arg", []) or [])
    remote_remove_args = _parse_remote_remove_args(getattr(args, "remote_remove_arg", []) or [])
    remote_set_args = _parse_remote_set_args(
        getattr(args, "remote_set_arg", []) or [],
        getattr(args, "remote_set_arg_kv", []) or [],
    )
    if not pairs and not remote_args and not remote_remove_args and not remote_set_args:
        return ""
    data = json.dumps(dict(pairs), separators=(",", ":"))
    arg_data = json.dumps(remote_args, separators=(",", ":"))
    remove_arg_data = json.dumps(remote_remove_args, separators=(",", ":"))
    set_arg_data = json.dumps(remote_set_args, separators=(",", ":"))
    code = _remote_launch_script_env_override_code()
    return f"DS4_REMOTE_ENV_OVERRIDES={shlex.quote(data)} DS4_REMOTE_ARG_OVERRIDES={shlex.quote(arg_data)} DS4_REMOTE_REMOVE_ARG_OVERRIDES={shlex.quote(remove_arg_data)} DS4_REMOTE_SET_ARG_OVERRIDES={shlex.quote(set_arg_data)} SCRIPT=\"$script\" python3 -c {shlex.quote(code)}"


def _remote_launch_script_env_override_code() -> str:
    code = (
        "import json,os,re,shlex\n"
        "path=os.environ['SCRIPT']\n"
        "overrides=json.loads(os.environ.get('DS4_REMOTE_ENV_OVERRIDES','{}'))\n"
        "extra_args=json.loads(os.environ.get('DS4_REMOTE_ARG_OVERRIDES','[]'))\n"
        "remove_args=json.loads(os.environ.get('DS4_REMOTE_REMOVE_ARG_OVERRIDES','[]'))\n"
        "set_args=json.loads(os.environ.get('DS4_REMOTE_SET_ARG_OVERRIDES','[]'))\n"
        "with open(path,encoding='utf-8') as f:\n"
        "    text=f.read()\n"
        "def rewrite_exec_env(line,key,value):\n"
        "    if not line.startswith('exec env '):\n"
        "        return line\n"
        "    parts=shlex.split(line)\n"
        "    insert_at=2\n"
        "    found=False\n"
        "    for i in range(2,len(parts)):\n"
        "        if '=' not in parts[i]:\n"
        "            break\n"
        "        insert_at=i+1\n"
        "        name=parts[i].split('=',1)[0]\n"
        "        if name == key:\n"
        "            parts[i]=f'{key}={value}'\n"
        "            found=True\n"
        "    if not found:\n"
        "        parts.insert(insert_at,f'{key}={value}')\n"
        "    return shlex.join(parts)\n"
        "def rewrite_exec_args(line,args):\n"
        "    if not line.startswith('exec env '):\n"
        "        return line\n"
        "    parts=shlex.split(line)\n"
        "    for arg in args:\n"
        "        if arg not in parts:\n"
        "            parts.append(arg)\n"
        "    return shlex.join(parts)\n"
        "def rewrite_exec_remove_args(line,args):\n"
        "    if not line.startswith('exec env '):\n"
        "        return line\n"
        "    parts=shlex.split(line)\n"
        "    out=[]\n"
        "    i=0\n"
        "    while i < len(parts):\n"
        "        part=parts[i]\n"
        "        removed=False\n"
        "        for opt in args:\n"
        "            if part == opt:\n"
        "                i+=1\n"
        "                if i < len(parts) and not parts[i].startswith('--'):\n"
        "                    i+=1\n"
        "                removed=True\n"
        "                break\n"
        "            if part.startswith(opt+'='):\n"
        "                i+=1\n"
        "                removed=True\n"
        "                break\n"
        "        if not removed:\n"
        "            out.append(part)\n"
        "            i+=1\n"
        "    return shlex.join(out)\n"
        "def rewrite_exec_set_args(line,args):\n"
        "    if not line.startswith('exec env '):\n"
        "        return line\n"
        "    parts=shlex.split(line)\n"
        "    for opt,value in args:\n"
        "        replaced=False\n"
        "        prefix=opt+'='\n"
        "        for i,part in enumerate(parts):\n"
        "            if part == opt:\n"
        "                if i+1 < len(parts) and not parts[i+1].startswith('--'):\n"
        "                    parts[i+1]=value\n"
        "                else:\n"
        "                    parts.insert(i+1,value)\n"
        "                replaced=True\n"
        "                break\n"
        "            if part.startswith(prefix):\n"
        "                parts[i]=prefix+value\n"
        "                replaced=True\n"
        "                break\n"
        "        if not replaced:\n"
        "            parts.extend([opt,value])\n"
        "    return shlex.join(parts)\n"
        "for key,value in overrides.items():\n"
        "    line=f'export {key}={value!r}'\n"
        "    text,count=re.subn(rf'^export {re.escape(key)}=.*$',line,text,flags=re.M)\n"
        "    if count == 0:\n"
        "        text=text.replace('\\n','\\n'+line+'\\n',1)\n"
        "    had_newline=text.endswith('\\n')\n"
        "    text='\\n'.join(rewrite_exec_env(line,key,value) for line in text.splitlines())\n"
        "    if had_newline:\n"
        "        text+='\\n'\n"
        "if extra_args:\n"
        "    had_newline=text.endswith('\\n')\n"
        "    text='\\n'.join(rewrite_exec_args(line,extra_args) for line in text.splitlines())\n"
        "    if had_newline:\n"
        "        text+='\\n'\n"
        "if remove_args:\n"
        "    had_newline=text.endswith('\\n')\n"
        "    text='\\n'.join(rewrite_exec_remove_args(line,remove_args) for line in text.splitlines())\n"
        "    if had_newline:\n"
        "        text+='\\n'\n"
        "if set_args:\n"
        "    had_newline=text.endswith('\\n')\n"
        "    text='\\n'.join(rewrite_exec_set_args(line,set_args) for line in text.splitlines())\n"
        "    if had_newline:\n"
        "        text+='\\n'\n"
        "with open(path,'w',encoding='utf-8') as f:\n"
        "    f.write(text)\n"
    )
    return code


def _entry_needs_prefetch_token(entry: dict[str, object]) -> bool:
    deployment = entry.get("deployment") if isinstance(entry.get("deployment"), dict) else {}
    extra_env = deployment.get("extra_env") if isinstance(deployment.get("extra_env"), dict) else {}
    return _truthy(extra_env.get("VLLM_DS4_KV_PREFETCH_API")) and _truthy(extra_env.get("VLLM_DS4_KV_PREFETCH_REQUIRE_TOKEN"))


def _truthy(value: object) -> bool:
    return str(value or "").strip().lower() in {"1", "true", "yes", "on"}


def _required_prefetch_token(args: argparse.Namespace, *, service_id: str) -> str:
    token = load_prefetch_token(getattr(args, "prefetch_token_file", str(DEFAULT_PREFETCH_TOKEN_FILE)))
    if token:
        return token
    raise ValueError(f"{service_id}: missing vLLM DS4 KV prefetch token; set --prefetch-token-file or --remote-env VLLM_DS4_KV_PREFETCH_TOKEN=...")


def _parse_remote_env(items: list[str]) -> list[tuple[str, str]]:
    out = []
    for item in items:
        if "=" not in item:
            raise ValueError("--remote-env requires KEY=VALUE")
        key, value = item.split("=", 1)
        if not _valid_env_name(key):
            raise ValueError(f"invalid --remote-env name: {key}")
        out.append((key, value))
    return out


def _parse_remote_args(items: list[str]) -> list[str]:
    out = []
    for item in items:
        if not item or "\n" in item or "\x00" in item:
            raise ValueError(f"invalid --remote-arg value: {item!r}")
        out.append(item)
    return out


def _parse_remote_remove_args(items: list[str]) -> list[str]:
    out = []
    for item in items:
        if not item.startswith("--") or "=" in item or "\n" in item or "\x00" in item:
            raise ValueError(f"invalid --remote-remove-arg value: {item!r}")
        out.append(item)
    return out


def _parse_remote_set_args(items: list[list[str]], kv_items: list[str] | None = None) -> list[list[str]]:
    out = []
    for opt, value in items:
        _append_remote_set_arg(out, opt, value, "--remote-set-arg")
    for item in kv_items or []:
        if "=" not in item:
            raise ValueError(f"invalid --remote-set-arg-kv value: {item!r}")
        opt, value = item.split("=", 1)
        _append_remote_set_arg(out, opt, value, "--remote-set-arg-kv")
    return out


def _append_remote_set_arg(out: list[list[str]], opt: str, value: str, label: str) -> None:
    if not opt.startswith("--") or not value or "\n" in opt or "\n" in value or "\x00" in opt or "\x00" in value:
        raise ValueError(f"invalid {label} value: {opt!r} {value!r}")
    out.append([opt, value])


def _valid_env_name(name: str) -> bool:
    return bool(name and (name[0].isalpha() or name[0] == "_") and all(ch.isalnum() or ch == "_" for ch in name))


def _remote_status(entry: dict[str, object]) -> str:
    code = "import json,os,subprocess\nn=json.loads(os.environ['N']);rows=[]\ndef is_vllm_serve(cmd):\n return (' -m vllm.entrypoints.cli.main serve ' in (' '+cmd+' ')) or (' vllm serve ' in (' '+cmd+' '))\nfor l in subprocess.run(['ps','-eo','pid=,args='],text=True,stdout=subprocess.PIPE).stdout.splitlines():\n p=l.strip().split(None,1)\n if len(p)==2 and is_vllm_serve(p[1]) and any(x and x in p[1] for x in n): rows.append({'pid':int(p[0]),'cmd':p[1]})\nprint(json.dumps(rows,sort_keys=True))"
    return f"N={shlex.quote(json.dumps(_needles(entry), separators=(',', ':')))} python3 -c {shlex.quote(code)}"


def _remote_kill(entry: dict[str, object]) -> str:
    code = "import json,os,signal,subprocess,time\nn=json.loads(os.environ['N']);parents=[];children={}\ndef is_vllm_serve(cmd):\n return (' -m vllm.entrypoints.cli.main serve ' in (' '+cmd+' ')) or (' vllm serve ' in (' '+cmd+' '))\nfor l in subprocess.run(['ps','-eo','pid=,ppid=,args='],text=True,stdout=subprocess.PIPE).stdout.splitlines():\n p=l.strip().split(None,2)\n if len(p)<3: continue\n pid=int(p[0]);ppid=int(p[1]);cmd=p[2]\n children.setdefault(ppid,[]).append(pid)\n if is_vllm_serve(cmd) and any(x and x in cmd for x in n): parents.append(pid)\nt=[];stack=list(parents)\nwhile stack:\n pid=stack.pop()\n if pid in t: continue\n t.append(pid);stack.extend(children.get(pid,[]))\nfor p in t:\n try: os.kill(p,signal.SIGTERM)\n except ProcessLookupError: pass\ntime.sleep(2)\nfor p in t:\n try: os.kill(p,0); os.kill(p,signal.SIGKILL)\n except ProcessLookupError: pass\nprint(json.dumps({'killed':t},sort_keys=True))"
    return f"N={shlex.quote(json.dumps(_needles(entry), separators=(',', ':')))} python3 -c {shlex.quote(code)}"


def _needles(entry: dict[str, object]) -> list[str]:
    dep = entry["deployment"]
    raw = {str(entry["service_id"]), str(entry["profile_id"]), str(entry["model_id"]), str(dep.get("model_id", "")), str(dep.get("served_model_name", "")), str(dep.get("master_port", ""))}
    needles = set()
    for item in raw:
        text = str(item).replace("{node}", "").strip()
        if len(text) >= 6:
            needles.add(text)
        leaf = text.rstrip("/").split("/")[-1]
        if len(leaf) >= 6:
            needles.add(leaf)
    return sorted(needles)


def _repo(args: argparse.Namespace) -> str:
    repo = shlex.quote(args.remote_repo)
    return f'set -euo pipefail\nrepo={repo}\nrepo="${{repo/#\\~/$HOME}}"\nrepo="${{repo/#\\$HOME/$HOME}}"\ncd "$repo/v2"'


def _ssh(node: str, script: str, args: argparse.Namespace, *, capture: bool = False) -> subprocess.CompletedProcess[str]:
    argv = ["ssh", "-o", "BatchMode=yes", "-o", f"ConnectTimeout={args.connect_timeout_s}", node, "bash -lc " + shlex.quote(script)]
    return _local(argv, capture=capture)


def _local(argv: list[str], *, capture: bool = False) -> subprocess.CompletedProcess[str]:
    if capture:
        return subprocess.run(argv, text=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE, check=False)
    print("+ " + " ".join(shlex.quote(_redact_secrets(item)) for item in argv))
    return subprocess.run(argv, text=True, check=True)


def _redact_secrets(text: str) -> str:
    return SECRET_ASSIGN_RE.sub(r"\1<redacted>", text)


def _nodes(entries: list[dict[str, object]]) -> list[str]:
    return sorted({str(node) for entry in entries for node in entry["node_ids"]}, key=lambda node: int("".join(ch for ch in node if ch.isdigit()) or 0))


def _remote_path(root: str, leaf: str) -> str:
    return root.rstrip("/") + "/" + leaf


def _remote_path_assign(name: str, root: str, leaf: str) -> str:
    path = _remote_path(root, leaf)
    return f'{name}={shlex.quote(path)}\n{name}="${{{name}/#\\~/$HOME}}"\n{name}="${{{name}/#\\$HOME/$HOME}}"'


def _load(path: Path) -> dict[str, object]:
    return json.loads(path.read_text(encoding="utf-8"))


if __name__ == "__main__":
    raise SystemExit(main())
