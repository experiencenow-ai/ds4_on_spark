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


PRODUCTION_COHORT_LIMIT = 256
THROUGHPUT_COHORT_LIMIT = 256
PRODUCTION_KV_ADMISSION_BYTES = 8589934592
THROUGHPUT_KV_ADMISSION_BYTES = 8589934592
COHORT_TOKEN_BUDGET = 262144


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
    argv = [
        sys.executable,
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
    parser.add_argument("--profile", choices=("throughput", "production"), default="throughput")
    parser.add_argument("--host", default=os.environ.get("HOST", "0.0.0.0"))
    parser.add_argument("--port", type=int, default=int(os.environ.get("PORT", "8700") or "8700"))
    parser.add_argument("--queue-dir", default=os.environ.get("QUEUE_DIR", str(Path.home() / "ds4_queue")))
    parser.add_argument("--profiles-dir", default=os.environ.get("PROFILES_DIR", "profiles/models"))
    parser.add_argument("--topology", default=os.environ.get("TOPOLOGY", "profiles/topology/static_sparks.json"))
    parser.add_argument("--runner-kind", default=os.environ.get("RUNNER_KIND", "pipeline"))
    parser.add_argument("--log-path", default=os.environ.get("DS4_COORDINATOR_LOG", ""))
    parser.add_argument("--pid-file", default=os.environ.get("DS4_COORDINATOR_PID_FILE", ""))
    parser.add_argument("--stop-timeout-s", type=float, default=8.0)
    parser.add_argument("--health-timeout-s", type=float, default=30.0)
    parser.add_argument("--health-poll-s", type=float, default=0.5)
    return parser.parse_args()


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
    return env


_SAFETY_PROFILE_DEFAULTS = {
    "DS4_API_DISPATCH_KV_CAPACITY_BYTES",
    "DS4_API_TRANSPORT_MAX_ATTEMPTS",
    "DS4_PIPELINE_COMPLETION_CHUNK_CONCURRENCY",
    "DS4_PIPELINE_COMPLETION_COHORT_TOKEN_BUDGET",
    "DS4_PIPELINE_COMPLETION_BISECT_ON_FAILURE",
    "DS4_PIPELINE_COMPLETION_PP_SAFE_COHORT_MAX",
}


def _profile_defaults(profile: str) -> dict[str, str]:
    common = {
        "DS4_API_BACKGROUND_DISPATCH": "1",
        "DS4_PIPELINE_COHORT_COMPLETIONS": "1",
        "DS4_PIPELINE_COMPLETION_COHORT_TOKEN_BUDGET": str(COHORT_TOKEN_BUDGET),
        "DS4_PIPELINE_COMPLETION_BISECT_ON_FAILURE": "1",
        "DS4_PIPELINE_COMPLETION_CHUNK_CONCURRENCY": "2",
        "DS4_PIPELINE_COMPLETION_PP_SAFE_COHORT_MAX": str(PRODUCTION_COHORT_LIMIT),
        "DS4_API_TRANSPORT_TIMEOUT_S": "3600",
        "DS4_API_TRANSPORT_MAX_ATTEMPTS": "1",
        "DS4_API_DISPATCH_KV_CAPACITY_BYTES": str(PRODUCTION_KV_ADMISSION_BYTES),
    }
    if profile == "production":
        common.update(
            {
                "DS4_API_DISPATCH_WINDOW": str(PRODUCTION_COHORT_LIMIT),
                "DS4_API_DISPATCH_REFILL_BATCH": str(PRODUCTION_COHORT_LIMIT),
                "DS4_API_DISPATCH_BATCH_LINGER_S": "0.03",
                "DS4_PIPELINE_COMPLETION_COHORT_MAX": str(PRODUCTION_COHORT_LIMIT),
            }
        )
    else:
        common.update(
            {
                "DS4_API_DISPATCH_WINDOW": str(THROUGHPUT_COHORT_LIMIT),
                "DS4_API_DISPATCH_REFILL_BATCH": str(THROUGHPUT_COHORT_LIMIT),
                "DS4_API_DISPATCH_BATCH_LINGER_S": "0.10",
                "DS4_PIPELINE_COMPLETION_COHORT_MAX": str(THROUGHPUT_COHORT_LIMIT),
                "DS4_PIPELINE_COMPLETION_COHORT_TOKEN_BUDGET": str(COHORT_TOKEN_BUDGET),
                "DS4_PIPELINE_COMPLETION_CHUNK_CONCURRENCY": "4",
                "DS4_PIPELINE_COMPLETION_PP_SAFE_COHORT_MAX": str(THROUGHPUT_COHORT_LIMIT),
                "DS4_API_DISPATCH_KV_CAPACITY_BYTES": str(THROUGHPUT_KV_ADMISSION_BYTES),
            }
        )
    return common


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
