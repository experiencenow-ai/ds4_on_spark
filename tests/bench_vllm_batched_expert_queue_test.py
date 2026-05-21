import argparse
import copy
import tempfile
import unittest
from pathlib import Path

from scripts import bench_vllm_batched_expert_queue as bench
from scripts import validate_centaur_standard_runtime_benchmark as validator


def blocked_args() -> argparse.Namespace:
	return argparse.Namespace(
		benchmark_id=bench.DEFAULT_BENCHMARK_ID,
		provider_id=bench.DEFAULT_PROVIDER_ID,
		model_id="deepseek-ai/DeepSeek-V4-Flash",
		runtime_version="0.1.dev16581+gdda4668b5.d20260521",
		launch_command="DS4_VLLM_FORCE_NO_DP_BATCHED_MARLIN=1 run",
		endpoint="http://10.20.0.14:8000/v1/completions",
		created_utc="2026-05-21T12:10:00Z",
		blocker_detail="patched server did not reach /v1/models",
		error_signature="ConnectionRefusedError and spark4 SSH banner timeout",
		raw_evidence=["curl: failed to connect", "Connection timed out during banner exchange"],
	)


class BenchVllmBatchedExpertQueueTest(unittest.TestCase):
	def test_blocked_artifact_validates_as_standard_runtime(self) -> None:
		obj = bench.build_blocked_artifact(blocked_args())
		errors = validator.validate_benchmark(obj, Path("blocked.json"))
		self.assertEqual(errors, [])
		self.assertEqual(obj["blocker_kind"], "endpoint_unavailable")
		self.assertIsNone(obj["tokens_per_second"])
		self.assertFalse(obj["parse_valid"])

	def test_hash_mismatch_rejected(self) -> None:
		obj = bench.build_blocked_artifact(blocked_args())
		obj = copy.deepcopy(obj)
		obj["provider_id"] = "tampered"
		errors = validator.validate_benchmark(obj, Path("blocked.json"))
		self.assertTrue(any("artifact_sha256" in item for item in errors))

	def test_main_writes_blocked_artifact(self) -> None:
		with tempfile.TemporaryDirectory() as tmp:
			out = Path(tmp) / "blocked.json"
			args = bench.parse_args([
				"--blocked",
				"--output",
				str(out),
				"--blocker-detail",
				"patched server did not reach /v1/models",
				"--error-signature",
				"ConnectionRefusedError and spark4 SSH banner timeout",
				"--raw-evidence",
				"curl: failed to connect",
			])
			bench.run(args)
			obj = validator.load_benchmark(out)
			self.assertEqual(validator.validate_benchmark(obj, out), [])


if __name__ == "__main__":
	unittest.main()
