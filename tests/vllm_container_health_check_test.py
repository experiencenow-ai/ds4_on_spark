import json
import subprocess
import tempfile
import unittest
from pathlib import Path

from scripts import vllm_container_health_check as health


DOCKER_UP_SLEEP = 'vllm_deepseek_v4_flash\tUp 2 hours\t"sleep infinity"\t0.0.0.0:8000->8000/tcp\n'
PROCESS_DEAD = ""
PROCESS_LIVE = "123 python -m vllm.entrypoints.openai.api_server --model /models/deepseek-v4-flash\n"
FAILED_LOGS = """
rank0 failed engine init
AssertionError: 256 == 128
NVRM: NVIDIA allocation failed: NV_ERR_NO_MEMORY
rank1 TCPStore broken pipe after rank0 died
"""
BACKLOG_METRICS = """
# HELP vllm:num_requests_running Number of requests currently running
vllm:num_requests_running{model_name="deepseek-v4-flash"} 101
vllm:num_requests_waiting{model_name="deepseek-v4-flash"} 0
"""
READY_METRICS = """
vllm:num_requests_running{model_name="deepseek-v4-flash"} 0
vllm:num_requests_waiting{model_name="deepseek-v4-flash"} 0
"""
COMPLETION_OK = {"choices": [{"message": {"content": "pong"}}]}


class VllmContainerHealthCheckTest(unittest.TestCase):
	def test_container_up_api_down_is_blocked(self) -> None:
		result = health.classify_snapshot("vllm_deepseek_v4_flash", "http://127.0.0.1:8000/v1/models", DOCKER_UP_SLEEP, PROCESS_DEAD, FAILED_LOGS, health.BLOCKED, "connection refused")
		self.assertEqual(result["status"], health.BLOCKED)
		self.assertEqual(result["blocker_kind"], "vllm_engine_dead_container_up")
		self.assertTrue(result["container_up"])
		self.assertFalse(result["vllm_process_alive"])
		self.assertIn("rank0_engine_init_failed", result["log_signals"])
		self.assertIn("nvidia_no_memory", result["log_signals"])
		self.assertIn("assertion_256_128", result["log_signals"])
		self.assertIn("guard-passed", result["recommended_fix"])

	def test_healthy_container_requires_api_and_process(self) -> None:
		result = health.classify_snapshot("vllm_deepseek_v4_flash", "http://127.0.0.1:8000/v1/models", DOCKER_UP_SLEEP.replace("sleep infinity", "vllm serve"), PROCESS_LIVE, "", health.HEALTHY, "http_200")
		self.assertEqual(result["status"], health.HEALTHY)
		self.assertEqual(result["blocker_kind"], "")
		self.assertTrue(result["vllm_process_alive"])
		self.assertFalse(result["container_command_only_sleep"])

	def test_health_200_with_backlog_is_not_serving_ready(self) -> None:
		queue = health.parse_queue_depth(BACKLOG_METRICS, "")
		serving = health.classify_serving_readiness(health.HEALTHY, "http_200", health.HEALTHY, "http_200", queue, health.HEALTHY, "http_200", COMPLETION_OK, 8, 0, False)
		result = health.classify_snapshot("vllm_deepseek_v4_flash", "http://127.0.0.1:8000/v1/models", DOCKER_UP_SLEEP.replace("sleep infinity", "vllm serve"), PROCESS_LIVE, "", health.HEALTHY, "http_200", serving)
		self.assertEqual(result["status"], health.BLOCKED)
		self.assertFalse(result["serving_readiness"]["serving_ready"])
		self.assertEqual(result["blocker_kind"], "serving_queue_backlog")
		self.assertEqual(result["serving_readiness"]["queue_depth"]["running_requests"], 101)

	def test_health_200_with_tiny_completion_timeout_is_not_ready(self) -> None:
		queue = health.parse_queue_depth(READY_METRICS, "")
		serving = health.classify_serving_readiness(health.HEALTHY, "http_200", health.HEALTHY, "http_200", queue, health.TIMEOUT, "TimeoutError: timed out", {}, 8, 0, False)
		result = health.classify_snapshot("vllm_deepseek_v4_flash", "http://127.0.0.1:8000/v1/models", DOCKER_UP_SLEEP.replace("sleep infinity", "vllm serve"), PROCESS_LIVE, "", health.HEALTHY, "http_200", serving)
		self.assertEqual(result["status"], health.BLOCKED)
		self.assertEqual(result["blocker_kind"], "completion_probe_timeout")

	def test_ready_metrics_and_completion_success_are_healthy(self) -> None:
		queue = health.parse_queue_depth(READY_METRICS, "")
		serving = health.classify_serving_readiness(health.HEALTHY, "http_200", health.HEALTHY, "http_200", queue, health.HEALTHY, "http_200", COMPLETION_OK, 8, 0, False)
		result = health.classify_snapshot("vllm_deepseek_v4_flash", "http://127.0.0.1:8000/v1/models", DOCKER_UP_SLEEP.replace("sleep infinity", "vllm serve"), PROCESS_LIVE, "", health.HEALTHY, "http_200", serving)
		self.assertEqual(result["status"], health.HEALTHY)
		self.assertTrue(result["serving_readiness"]["serving_ready"])
		self.assertEqual(result["serving_readiness"]["completion_probe"]["payload_kind"], "message_content")

	def test_queue_depth_can_parse_log_fallback(self) -> None:
		queue = health.parse_queue_depth("", "INFO Running: 12 reqs, Waiting: 3 reqs")
		self.assertEqual(queue["running_requests"], 12)
		self.assertEqual(queue["waiting_requests"], 3)
		self.assertEqual(queue["source"], "logs")

	def test_cli_offline_files(self) -> None:
		tmp = Path(tempfile.mkdtemp())
		ps = tmp / "ps.txt"
		proc = tmp / "proc.txt"
		logs = tmp / "logs.txt"
		ps.write_text(DOCKER_UP_SLEEP, encoding="utf-8")
		proc.write_text(PROCESS_DEAD, encoding="utf-8")
		logs.write_text(FAILED_LOGS, encoding="utf-8")
		cmd = [
			"python3",
			"scripts/vllm_container_health_check.py",
			"--docker-ps-file",
			str(ps),
			"--process-file",
			str(proc),
			"--log-file",
			str(logs),
			"--api-status",
			health.BLOCKED,
			"--skip-serving-readiness",
		]
		result = subprocess.run(cmd, text=True, capture_output=True)
		self.assertEqual(result.returncode, 2, result.stdout + result.stderr)
		payload = json.loads(result.stdout)
		self.assertEqual(payload["format"], health.FORMAT)
		self.assertEqual(payload["blocker_kind"], "vllm_engine_dead_container_up")
		self.assertEqual(payload["command_results"], {})

	def test_cli_offline_serving_readiness_files(self) -> None:
		tmp = Path(tempfile.mkdtemp())
		ps = tmp / "ps.txt"
		proc = tmp / "proc.txt"
		metrics = tmp / "metrics.txt"
		completion = tmp / "completion.json"
		ps.write_text(DOCKER_UP_SLEEP.replace("sleep infinity", "vllm serve"), encoding="utf-8")
		proc.write_text(PROCESS_LIVE, encoding="utf-8")
		metrics.write_text(BACKLOG_METRICS, encoding="utf-8")
		completion.write_text(json.dumps(COMPLETION_OK), encoding="utf-8")
		cmd = [
			"python3",
			"scripts/vllm_container_health_check.py",
			"--docker-ps-file",
			str(ps),
			"--process-file",
			str(proc),
			"--api-status",
			health.HEALTHY,
			"--health-status",
			health.HEALTHY,
			"--metrics-file",
			str(metrics),
			"--completion-file",
			str(completion),
		]
		result = subprocess.run(cmd, text=True, capture_output=True)
		self.assertEqual(result.returncode, 2, result.stdout + result.stderr)
		payload = json.loads(result.stdout)
		self.assertEqual(payload["blocker_kind"], "serving_queue_backlog")
		self.assertFalse(payload["serving_readiness"]["serving_ready"])
		self.assertEqual(payload["serving_readiness"]["queue_depth"]["running_requests"], 101)


if __name__ == "__main__":
	unittest.main()
