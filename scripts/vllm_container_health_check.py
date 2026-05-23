#!/usr/bin/env python3
"""Classify vLLM container health without trusting Docker's Up status alone."""

from __future__ import annotations

import argparse
import json
import re
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
TIMEOUT = "timeout"

def append_issue(issues: list[dict[str, str]], kind: str, detail: str) -> None:
	issues.append({"kind": kind, "detail": detail})

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


def probe_text(endpoint: str, timeout: float) -> tuple[str, str, str]:
	try:
		with urllib.request.urlopen(endpoint, timeout=timeout) as r:
			body = r.read(1048576).decode("utf-8", errors="replace")
			if 200 <= r.status < 300:
				return(HEALTHY, f"http_{r.status}", body)
			return(DEGRADED, f"http_{r.status}", body)
	except urllib.error.HTTPError as e:
		body = e.read(65536).decode("utf-8", errors="replace")
		return(DEGRADED, f"http_{e.code}", body)
	except Exception as e:
		return(BLOCKED, type(e).__name__ + ": " + str(e), "")


def probe_json_post(endpoint: str, payload: dict[str, Any], timeout: float) -> tuple[str, str, dict[str, Any]]:
	data = json.dumps(payload).encode("utf-8")
	req = urllib.request.Request(endpoint, data=data, headers={"Content-Type": "application/json"}, method="POST")
	try:
		with urllib.request.urlopen(req, timeout=timeout) as r:
			body = r.read(65536).decode("utf-8", errors="replace")
			if 200 <= r.status < 300:
				try:
					return(HEALTHY, f"http_{r.status}", json.loads(body))
				except json.JSONDecodeError:
					return(DEGRADED, f"http_{r.status}_invalid_json", {"raw_body": body[:4096]})
			return(DEGRADED, f"http_{r.status}", {"raw_body": body[:4096]})
	except TimeoutError as e:
		return(TIMEOUT, type(e).__name__ + ": " + str(e), {})
	except urllib.error.HTTPError as e:
		body = e.read(4096).decode("utf-8", errors="replace")
		return(DEGRADED, f"http_{e.code}", {"raw_body": body})
	except Exception as e:
		if type(e).__name__ == "TimeoutError":
			return(TIMEOUT, type(e).__name__ + ": " + str(e), {})
		return(BLOCKED, type(e).__name__ + ": " + str(e), {})


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


def parse_metric_value(line: str) -> float | None:
	parts = line.rsplit(None, 1)
	if len(parts) != 2:
		return(None)
	try:
		return(float(parts[1]))
	except ValueError:
		return(None)


def parse_queue_depth(metrics_text: str, log_text: str) -> dict[str, Any]:
	running: float | None = None
	waiting: float | None = None
	source = ""
	for raw_line in metrics_text.splitlines():
		line = raw_line.strip()
		if line == "" or line.startswith("#"):
			continue
		name = line.split("{", 1)[0].split(None, 1)[0]
		value = parse_metric_value(line)
		if value is None:
			continue
		normalized = name.replace(":", "_").replace("-", "_").lower()
		if normalized.endswith("num_requests_running") or normalized.endswith("requests_running"):
			running = value
			source = "metrics"
		elif normalized.endswith("num_requests_waiting") or normalized.endswith("requests_waiting"):
			waiting = value
			source = "metrics"
	if running is None or waiting is None:
		m = re.search(r"Running:\s*(\d+)\s*reqs,\s*Waiting:\s*(\d+)\s*reqs", log_text, re.IGNORECASE)
		if m is not None:
			if running is None:
				running = float(m.group(1))
			if waiting is None:
				waiting = float(m.group(2))
			source = "logs"
	return({
		"running_requests": None if running is None else int(running),
		"waiting_requests": None if waiting is None else int(waiting),
		"source": source,
	})


def classify_completion_payload(payload: dict[str, Any]) -> tuple[bool, str]:
	choices = payload.get("choices")
	if not isinstance(choices, list) or len(choices) == 0:
		return(False, "missing_choices")
	first = choices[0]
	if not isinstance(first, dict):
		return(False, "invalid_choice")
	if isinstance(first.get("text"), str) and first["text"] != "":
		return(True, "text")
	message = first.get("message")
	if isinstance(message, dict) and isinstance(message.get("content"), str) and message["content"] != "":
		return(True, "message_content")
	return(False, "empty_completion")


def classify_serving_readiness(health_status: str, health_detail: str, metrics_status: str, metrics_detail: str, queue_depth: dict[str, Any], completion_status: str, completion_detail: str, completion_payload: dict[str, Any], max_ready_running: int, max_ready_waiting: int, completion_required: bool) -> dict[str, Any]:
	issues: list[dict[str, str]] = []
	if health_status != HEALTHY:
		append_issue(issues,"health_not_ready",health_detail)
	if metrics_status not in (HEALTHY, UNKNOWN):
		append_issue(issues,"metrics_unavailable",metrics_detail)
	running = queue_depth.get("running_requests")
	waiting = queue_depth.get("waiting_requests")
	if running is not None and running > max_ready_running:
		append_issue(issues,"serving_queue_backlog",f"running_requests={running} exceeds {max_ready_running}")
	if waiting is not None and waiting > max_ready_waiting:
		append_issue(issues,"serving_queue_backlog",f"waiting_requests={waiting} exceeds {max_ready_waiting}")
	completion_ok = False
	completion_kind = "not_run"
	if completion_status == UNKNOWN:
		if completion_required:
			append_issue(issues,"completion_probe_not_run","completion probe is required")
	elif completion_status == TIMEOUT:
		append_issue(issues,"completion_probe_timeout",completion_detail)
	elif completion_status != HEALTHY:
		append_issue(issues,"completion_probe_failed",completion_detail)
	else:
		completion_ok, completion_kind = classify_completion_payload(completion_payload)
		if not completion_ok:
			append_issue(issues,"completion_probe_empty",completion_kind)
	return({
		"serving_ready": len(issues) == 0,
		"health_status": health_status,
		"health_detail": health_detail,
		"metrics_status": metrics_status,
		"metrics_detail": metrics_detail,
		"queue_depth": queue_depth,
		"completion_probe": {
			"status": completion_status,
			"detail": completion_detail,
			"payload_kind": completion_kind,
		},
		"issues": issues,
	})


def recommended_fix(signals: list[str], sleep_only: bool) -> str:
	if "nvidia_no_memory" in signals or "assertion_256_128" in signals:
		return("stop the sleep-only containers, relaunch with a guard-passed DS4 Flash profile, keep prefix cache disabled, and reduce graph/KV pressure before retrying c512")
	if sleep_only:
		return("treat Docker Up as insufficient; require /v1/models and a live vllm serve process before benchmarking")
	return("inspect rank0 logs and relaunch only through scripts/run_guarded_spark_vllm_recipe.py")


def classify_snapshot(container: str, endpoint: str, docker_ps: str, process_text: str, log_text: str, api_status: str, api_detail: str, serving_readiness: dict[str, Any] | None = None) -> dict[str, Any]:
	container_up = detect_container_up(docker_ps)
	sleep_only = detect_sleep_only_container(docker_ps)
	process_alive = detect_process_alive(process_text)
	signals = detect_log_signals(log_text)
	issues: list[dict[str, str]] = []
	if not container_up:
		append_issue(issues,"container_not_up",f"{container} is not reported Up by docker ps")
	if api_status != HEALTHY:
		append_issue(issues,"api_not_listening",api_detail)
	if not process_alive:
		append_issue(issues,"vllm_process_not_alive","no vllm serve/api process detected inside the container")
	if sleep_only:
		append_issue(issues,"sleep_only_container","container command can be Up while the vllm serve subprocess is dead")
	for signal in signals:
		append_issue(issues,signal,"matched vLLM failure signature in rank logs")
	if serving_readiness is not None:
		for issue in serving_readiness["issues"]:
			append_issue(issues,issue["kind"],issue["detail"])
	if container_up and api_status != HEALTHY and (not process_alive or "rank0_engine_init_failed" in signals):
		blocker = "vllm_engine_dead_container_up"
	elif "nvidia_no_memory" in signals:
		blocker = "gpu_allocation_failure"
	elif "assertion_256_128" in signals:
		blocker = "launch_profile_shape_mismatch"
	elif serving_readiness is not None and not serving_readiness["serving_ready"]:
		blocker = serving_readiness["issues"][0]["kind"]
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
		"serving_readiness": serving_readiness or {},
		"issues": issues,
		"blocker_kind": blocker,
		"blocker_detail": "; ".join(issue["kind"] for issue in issues),
		"recommended_fix": recommended_fix(signals,sleep_only) if issues else "",
	})


def parse_args() -> argparse.Namespace:
	p = argparse.ArgumentParser(description=__doc__)
	p.add_argument("--container", default="vllm_deepseek_v4_flash")
	p.add_argument("--endpoint", default="http://127.0.0.1:8000/v1/models")
	p.add_argument("--health-endpoint", default="http://127.0.0.1:8000/health")
	p.add_argument("--metrics-endpoint", default="http://127.0.0.1:8000/metrics")
	p.add_argument("--completion-endpoint", default="http://127.0.0.1:8000/v1/chat/completions")
	p.add_argument("--model", default="")
	p.add_argument("--prompt", default="ping")
	p.add_argument("--max-tokens", type=int, default=1)
	p.add_argument("--timeout", type=float, default=3.0)
	p.add_argument("--completion-timeout", type=float, default=10.0)
	p.add_argument("--max-ready-running", type=int, default=8)
	p.add_argument("--max-ready-waiting", type=int, default=0)
	p.add_argument("--skip-serving-readiness", action="store_true")
	p.add_argument("--completion-probe", action="store_true")
	p.add_argument("--skip-completion-probe", action="store_true")
	p.add_argument("--require-completion-probe", action="store_true")
	p.add_argument("--docker-ps-file", type=Path)
	p.add_argument("--process-file", type=Path)
	p.add_argument("--log-file", type=Path, action="append", default=[])
	p.add_argument("--metrics-file", type=Path)
	p.add_argument("--completion-file", type=Path)
	p.add_argument("--api-status", choices=(HEALTHY, BLOCKED, DEGRADED, UNKNOWN))
	p.add_argument("--health-status", choices=(HEALTHY, BLOCKED, DEGRADED, UNKNOWN))
	p.add_argument("--metrics-status", choices=(HEALTHY, BLOCKED, DEGRADED, UNKNOWN))
	p.add_argument("--completion-status", choices=(HEALTHY, BLOCKED, DEGRADED, UNKNOWN, TIMEOUT))
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
	serving_readiness: dict[str, Any] | None = None
	if not args.skip_serving_readiness:
		if args.health_status is not None:
			health_status = args.health_status
			health_detail = "provided_by_cli"
		else:
			health_status, health_detail = probe_api(args.health_endpoint,args.timeout)
		if args.metrics_file is not None:
			metrics_text = args.metrics_file.read_text(encoding="utf-8", errors="replace")
			metrics_status = args.metrics_status or HEALTHY
			metrics_detail = "provided_by_file"
		elif args.metrics_status is not None:
			metrics_text = ""
			metrics_status = args.metrics_status
			metrics_detail = "provided_by_cli"
		else:
			metrics_status, metrics_detail, metrics_text = probe_text(args.metrics_endpoint,args.timeout)
		completion_payload: dict[str, Any] = {}
		should_probe_completion = args.completion_probe or args.model != "" or args.require_completion_probe or args.completion_file is not None or args.completion_status is not None
		if args.skip_completion_probe or not should_probe_completion:
			completion_status = UNKNOWN
			completion_detail = "skipped"
		elif args.completion_file is not None:
			completion_payload = json.loads(args.completion_file.read_text(encoding="utf-8"))
			completion_status = args.completion_status or HEALTHY
			completion_detail = "provided_by_file"
		elif args.completion_status is not None:
			completion_status = args.completion_status
			completion_detail = "provided_by_cli"
		else:
			model = args.model or "readiness-probe"
			payload = {"model": model, "messages": [{"role": "user", "content": args.prompt}], "max_tokens": args.max_tokens, "temperature": 0}
			completion_status, completion_detail, completion_payload = probe_json_post(args.completion_endpoint,payload,args.completion_timeout)
		queue_depth = parse_queue_depth(metrics_text,log_text)
		serving_readiness = classify_serving_readiness(health_status,health_detail,metrics_status,metrics_detail,queue_depth,completion_status,completion_detail,completion_payload,args.max_ready_running,args.max_ready_waiting,args.require_completion_probe)
	result = classify_snapshot(args.container,args.endpoint,docker_ps,process_text,log_text,api_status,api_detail,serving_readiness)
	result["command_results"] = command_results
	print(json.dumps(result, indent=2, sort_keys=True))
	return(0 if result["status"] == HEALTHY else 2)


if __name__ == "__main__":
	raise SystemExit(main())
