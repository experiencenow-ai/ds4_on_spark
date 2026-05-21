#!/usr/bin/env python3
"""Classify vLLM container health without trusting Docker's Up status alone."""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
import urllib.error
import urllib.request
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


FORMAT = "ds4-vllm-container-health-v1"
HEALTHY = "healthy"
BLOCKED = "blocked"
DEGRADED = "degraded"
UNKNOWN = "unknown"

def utc_now() -> str:
	return(datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00","Z"))


def read_text_files(paths: list[Path]) -> str:
	out: list[str] = []
	for path in paths:
		out.append(path.read_text(encoding="utf-8", errors="replace"))
	return("\n".join(out))


def run_cmd(cmd: list[str], timeout: float) -> dict[str, Any]:
	try:
		p = subprocess.run(cmd, text=True, capture_output=True, timeout=timeout)
		return({"cmd": cmd, "rc": p.returncode, "stdout": p.stdout, "stderr": p.stderr})
	except subprocess.TimeoutExpired as e:
		return({"cmd": cmd, "rc": None, "stdout": e.stdout or "", "stderr": e.stderr or "", "timeout": True})
	except OSError as e:
		return({"cmd": cmd, "rc": None, "stdout": "", "stderr": str(e), "os_error": True})


def probe_api(endpoint: str, timeout: float) -> tuple[str, str]:
	try:
		with urllib.request.urlopen(endpoint, timeout=timeout) as r:
			if 200 <= r.status < 300:
				return(HEALTHY, f"http_{r.status}")
			return(DEGRADED, f"http_{r.status}")
	except urllib.error.HTTPError as e:
		return(DEGRADED, f"http_{e.code}")
	except Exception as e:
		return(BLOCKED, type(e).__name__ + ": " + str(e))


def detect_container_up(docker_ps: str) -> bool:
	return(any("Up" in line for line in docker_ps.splitlines()))


def detect_sleep_only_container(docker_ps: str) -> bool:
	return("sleep infinity" in docker_ps or '"sleep infinity"' in docker_ps or "'sleep infinity'" in docker_ps)


def detect_process_alive(process_text: str) -> bool:
	needle = process_text.lower()
	return("vllm" in needle and ("serve" in needle or "api_server" in needle or "openai" in needle))


def detect_log_signals(log_text: str) -> list[str]:
	signals: list[str] = []
	lower = log_text.lower()
	if "failed engine init" in lower or "engine init failed" in lower:
		signals.append("rank0_engine_init_failed")
	if "tcpstore" in lower and "broken pipe" in lower:
		signals.append("tcpstore_broken_pipe")
	if "nv_err_no_memory" in lower or "allocation failed" in lower:
		signals.append("nvidia_no_memory")
	if "assertionerror: 256 == 128" in lower:
		signals.append("assertion_256_128")
	return(signals)


def recommended_fix(signals: list[str], sleep_only: bool) -> str:
	if "nvidia_no_memory" in signals or "assertion_256_128" in signals:
		return("stop the sleep-only containers, relaunch with a guard-passed DS4 Flash profile, keep prefix cache disabled, and reduce graph/KV pressure before retrying c512")
	if sleep_only:
		return("treat Docker Up as insufficient; require /v1/models and a live vllm serve process before benchmarking")
	return("inspect rank0 logs and relaunch only through scripts/run_guarded_spark_vllm_recipe.py")


def classify_snapshot(container: str, endpoint: str, docker_ps: str, process_text: str, log_text: str, api_status: str, api_detail: str) -> dict[str, Any]:
	container_up = detect_container_up(docker_ps)
	sleep_only = detect_sleep_only_container(docker_ps)
	process_alive = detect_process_alive(process_text)
	signals = detect_log_signals(log_text)
	issues: list[dict[str, str]] = []
	if not container_up:
		issues.append({"kind": "container_not_up", "detail": f"{container} is not reported Up by docker ps"})
	if api_status != HEALTHY:
		issues.append({"kind": "api_not_listening", "detail": api_detail})
	if not process_alive:
		issues.append({"kind": "vllm_process_not_alive", "detail": "no vllm serve/api process detected inside the container"})
	if sleep_only:
		issues.append({"kind": "sleep_only_container", "detail": "container command can be Up while the vllm serve subprocess is dead"})
	for signal in signals:
		issues.append({"kind": signal, "detail": "matched vLLM failure signature in rank logs"})
	if container_up and api_status != HEALTHY and (not process_alive or "rank0_engine_init_failed" in signals):
		blocker = "vllm_engine_dead_container_up"
	elif "nvidia_no_memory" in signals:
		blocker = "gpu_allocation_failure"
	elif "assertion_256_128" in signals:
		blocker = "launch_profile_shape_mismatch"
	elif issues:
		blocker = issues[0]["kind"]
	else:
		blocker = ""
	status = HEALTHY if not issues else BLOCKED
	return({
		"format": FORMAT,
		"checked_at": utc_now(),
		"container": container,
		"endpoint": endpoint,
		"status": status,
		"container_up": container_up,
		"container_command_only_sleep": sleep_only,
		"api_status": api_status,
		"api_detail": api_detail,
		"vllm_process_alive": process_alive,
		"log_signals": signals,
		"issues": issues,
		"blocker_kind": blocker,
		"blocker_detail": "; ".join(issue["kind"] for issue in issues),
		"recommended_fix": recommended_fix(signals,sleep_only) if issues else "",
	})


def parse_args() -> argparse.Namespace:
	p = argparse.ArgumentParser(description=__doc__)
	p.add_argument("--container", default="vllm_deepseek_v4_flash")
	p.add_argument("--endpoint", default="http://127.0.0.1:8000/v1/models")
	p.add_argument("--timeout", type=float, default=3.0)
	p.add_argument("--docker-ps-file", type=Path)
	p.add_argument("--process-file", type=Path)
	p.add_argument("--log-file", type=Path, action="append", default=[])
	p.add_argument("--api-status", choices=(HEALTHY, BLOCKED, DEGRADED, UNKNOWN))
	return(p.parse_args())


def main() -> int:
	args = parse_args()
	command_results: dict[str, Any] = {}
	if args.docker_ps_file is not None:
		docker_ps = args.docker_ps_file.read_text(encoding="utf-8", errors="replace")
	else:
		cmd = ["docker","ps","--filter",f"name={args.container}","--format","{{.Names}}\t{{.Status}}\t{{.Command}}\t{{.Ports}}"]
		command_results["docker_ps"] = run_cmd(cmd,args.timeout)
		docker_ps = command_results["docker_ps"]["stdout"]
	if args.process_file is not None:
		process_text = args.process_file.read_text(encoding="utf-8", errors="replace")
	else:
		cmd = ["docker","exec",args.container,"sh","-lc","pgrep -af 'vllm|api_server|openai' || true"]
		command_results["docker_exec_process"] = run_cmd(cmd,args.timeout)
		process_text = command_results["docker_exec_process"]["stdout"]
	if args.log_file:
		log_text = read_text_files(args.log_file)
	else:
		cmd = ["docker","logs","--tail","400",args.container]
		command_results["docker_logs"] = run_cmd(cmd,args.timeout)
		log_text = command_results["docker_logs"]["stdout"] + command_results["docker_logs"]["stderr"]
	if args.api_status is not None:
		api_status = args.api_status
		api_detail = "provided_by_cli"
	else:
		api_status, api_detail = probe_api(args.endpoint,args.timeout)
	result = classify_snapshot(args.container,args.endpoint,docker_ps,process_text,log_text,api_status,api_detail)
	result["command_results"] = command_results
	print(json.dumps(result, indent=2, sort_keys=True))
	return(0 if result["status"] == HEALTHY else 2)


if __name__ == "__main__":
	raise SystemExit(main())
