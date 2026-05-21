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
		]
		result = subprocess.run(cmd, text=True, capture_output=True)
		self.assertEqual(result.returncode, 2, result.stdout + result.stderr)
		payload = json.loads(result.stdout)
		self.assertEqual(payload["format"], health.FORMAT)
		self.assertEqual(payload["blocker_kind"], "vllm_engine_dead_container_up")
		self.assertEqual(payload["command_results"], {})


if __name__ == "__main__":
	unittest.main()
