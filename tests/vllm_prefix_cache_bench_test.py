import json
import tempfile
import unittest
from pathlib import Path

from scripts import validate_centaur_standard_runtime_benchmark as validator
from scripts import vllm_prefix_cache_bench as bench


class VllmPrefixCacheBenchTest(unittest.TestCase):
	def test_prompts_share_system_prefix_and_vary_user_suffix(self) -> None:
		prompt0 = bench.build_prompt(0, 20, 12)
		prompt1 = bench.build_prompt(1, 20, 12)
		prefix0, suffix0 = prompt0.split("<|user|>\n", 1)
		prefix1, suffix1 = prompt1.split("<|user|>\n", 1)
		self.assertEqual(prefix0, prefix1)
		self.assertNotEqual(suffix0, suffix1)
		self.assertTrue(prompt0.endswith("<|assistant|>\n"))

	def test_metric_parser_computes_cached_prompt_token_delta(self) -> None:
		before = bench.prefix_metric_snapshot(
			"vllm:prompt_tokens_total 100\n"
			"vllm:prompt_tokens_by_source_total{source=\"local_compute\"} 100\n"
			"vllm:prompt_tokens_cached_total 10\n"
			"vllm:prefix_cache_hits_total 1\n"
			"vllm:prefix_cache_hits_created 999\n"
		)
		after = bench.prefix_metric_snapshot(
			"vllm:prompt_tokens_total 300\n"
			"vllm:prompt_tokens_by_source_total{source=\"local_compute\"} 300\n"
			"vllm:prompt_tokens_cached_total 160\n"
			"vllm:prefix_cache_hits_total 51\n"
			"vllm:prefix_cache_hits_created 999\n"
		)
		delta = bench.delta_metrics(before, after)
		self.assertEqual(delta["prompt_tokens_total"], 200.0)
		self.assertEqual(delta["prompt_tokens_cached_total"], 150.0)
		self.assertEqual(delta["prefix_cache_hits_total"], 50.0)

	def test_api_base_from_endpoint_preserves_v1(self) -> None:
		self.assertEqual(
			bench.api_base_from_endpoint("http://127.0.0.1:8000/v1/completions"),
			"http://127.0.0.1:8000/v1",
		)

	def test_blocked_artifact_validates_and_hashes(self) -> None:
		with tempfile.TemporaryDirectory() as tmp:
			path = Path(tmp) / "blocked.json"
			args = bench.parse_args([
				"--output",
				str(path),
				"--blocked",
				"--blocker-detail",
				"spark4 ssh timed out",
				"--created-utc",
				"2026-05-21T10:00:00Z",
				"--spark3-ssh",
				"ok",
				"--spark4-ssh",
				"banner timeout",
				"--spark5-ssh",
				"ok",
				"--models-endpoint",
				"connection refused",
				"--rescue-endpoint",
				"timeout",
				"--raw-evidence",
				"ssh spark4 hostname -> rc=255",
			])
			obj = bench.run(args)
			self.assertEqual(obj["benchmark_status"], "blocked")
			self.assertEqual(obj["artifact_sha256"], bench.canonical_hash(obj))
			result = validator.validate_paths([path])
			self.assertTrue(result["ok"], result["errors"])

	def test_tampered_blocked_artifact_fails_hash_validation(self) -> None:
		with tempfile.TemporaryDirectory() as tmp:
			path = Path(tmp) / "blocked.json"
			args = bench.parse_args([
				"--output",
				str(path),
				"--blocked",
				"--blocker-detail",
				"spark4 unavailable",
			])
			obj = bench.run(args)
			obj["model_id"] = "tampered"
			path.write_text(json.dumps(obj, indent=2, sort_keys=True) + "\n", encoding="utf-8")
			result = validator.validate_paths([path])
			self.assertFalse(result["ok"])
			self.assertTrue(any("artifact_sha256 does not match" in item for item in result["errors"]))


if __name__ == "__main__":
	unittest.main()
