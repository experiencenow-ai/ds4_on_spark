import copy
import tempfile
import unittest
from pathlib import Path

from scripts import validate_ds4_perf_icebergs as icebergs


FIX = Path("fixtures/perf_icebergs")


class PerfIcebergsTest(unittest.TestCase):
	def test_perf_iceberg_fixtures_validate(self) -> None:
		for path in sorted(FIX.glob("*.json")):
			with self.subTest(path=path.name):
				obj = icebergs.load_json(path)
				self.assertEqual(icebergs.validate_artifact(obj), [])

	def test_hash_tampering_fails_validation(self) -> None:
		obj = copy.deepcopy(icebergs.load_json(FIX / "full_stack_80_tok_success.example.json"))
		obj["best_full_stack_tok_s"] = 81.0
		errors = icebergs.validate_summary(obj)
		self.assertTrue(any("artifact_sha256" in item for item in errors))

	def test_component_only_409_does_not_count_as_decode(self) -> None:
		obj = icebergs.load_json(FIX / "component_409_only_not_full_stack.example.json")
		self.assertIsNone(obj["best_full_stack_tok_s"])
		self.assertFalse(obj["exceeds_15_tok_s"])

	def test_baseline_does_not_exceed_target(self) -> None:
		obj = icebergs.load_json(FIX / "full_stack_13_3_baseline.example.json")
		self.assertEqual(obj["best_full_stack_tok_s"], 13.3)
		self.assertFalse(obj["exceeds_15_tok_s"])

	def test_full_stack_success_crosses_baseline(self) -> None:
		obj = icebergs.load_json(FIX / "full_stack_80_tok_success.example.json")
		self.assertTrue(obj["exceeds_15_tok_s"])
		self.assertGreater(obj["realization_ratio_vs_409"], 0.19)

	def test_output_head_cap_is_surfaced(self) -> None:
		obj = icebergs.load_json(FIX / "output_head_cap.example.json")
		self.assertEqual(obj["current_primary_blocker"], "output_head_cap")
		self.assertLess(obj["output_head_cap_tok_s"], 409.0)

	def test_input_prefill_cap_is_surfaced(self) -> None:
		obj = icebergs.load_json(FIX / "input_prefill_cap.example.json")
		self.assertEqual(obj["current_primary_blocker"], "prefix_prefill_cap")
		self.assertEqual(obj["current_secondary_blocker"], "suffix_prefill_cap")

	def test_residency_blocker_is_surfaced(self) -> None:
		obj = icebergs.load_json(FIX / "full_stack_blocked_residency.example.json")
		self.assertEqual(obj["current_primary_blocker"], "lazy_moe_range_upload")
		self.assertIn("residency", obj["next_code_change_required"].lower())

	def test_success_full_stack_requires_output_hash(self) -> None:
		obj = copy.deepcopy(icebergs.load_json(FIX / "full_stack_80_tok_success.example.json"))
		obj["best_full_stack_output_hash"] = ""
		obj["artifact_sha256"] = icebergs.artifact_sha256(obj)
		errors = icebergs.validate_summary(obj)
		self.assertTrue(any("output hash" in item for item in errors))

	def test_top_level_world_size_is_rejected(self) -> None:
		obj = copy.deepcopy(icebergs.load_json(FIX / "full_stack_80_tok_success.example.json"))
		obj["world_size"] = 3
		obj["artifact_sha256"] = icebergs.artifact_sha256(obj)
		errors = icebergs.validate_summary(obj)
		self.assertTrue(any("fixed Spark count" in item for item in errors))

	def test_record_builder_parses_output_head_probe(self) -> None:
		with tempfile.TemporaryDirectory() as d:
			root = Path(d)
			out = root / "head.out"
			err = root / "head.err"
			out.write_text(
				'{"cuda_output_head_probe":true,"best_ms":2.579,"best_heads_per_s":387.807,'
				'"logits_fnv64":"d99730a7a09d8f8a","logits_nonfinite":0}\n',
				encoding="utf-8",
			)
			err.write_text("", encoding="utf-8")
			args = self._args(root, out, err)
			args.component_kind = "output_head"
			args.case_id = "unit-head"
			args.includes_output_head = True
			args.component_only = True
			obj = icebergs.build_record(args)
			self.assertEqual(icebergs.validate_record(obj), [])
			self.assertEqual(obj["failure_status"], "success")
			self.assertEqual(obj["output_hash"], "fnv64:d99730a7a09d8f8a")

	def test_record_builder_classifies_residency_failure(self) -> None:
		with tempfile.TemporaryDirectory() as d:
			root = Path(d)
			out = root / "stack.out"
			err = root / "stack.err"
			out.write_text("", encoding="utf-8")
			err.write_text("CUDA model range upload sync failed for stack_stage layer 9\n", encoding="utf-8")
			args = self._args(root, out, err)
			args.component_kind = "full_stack_batch_with_head"
			args.case_id = "unit-stack"
			args.batch_size = 16
			args.layers_executed = 43
			args.includes_output_head = True
			args.includes_attention = True
			args.includes_kv = True
			args.rc = 1
			obj = icebergs.build_record(args)
			self.assertEqual(icebergs.validate_record(obj), [])
			self.assertEqual(obj["failure_status"], "failed")
			self.assertEqual(obj["blocker_kind"], "lazy_moe_range_upload")

	def test_prefill_timing_success_does_not_require_output_hash(self) -> None:
		with tempfile.TemporaryDirectory() as d:
			root = Path(d)
			out = root / "prefill.out"
			err = root / "prefill.err"
			out.write_text("ds4: prefill: 18.4 t/s\n", encoding="utf-8")
			err.write_text("", encoding="utf-8")
			args = self._args(root, out, err)
			args.component_kind = "prefix_miss_prefill"
			args.case_id = "unit-prefill"
			args.component_only = True
			args.input_tokens = 512
			obj = icebergs.build_record(args)
			self.assertEqual(icebergs.validate_record(obj), [])
			self.assertEqual(obj["failure_status"], "success")
			self.assertEqual(obj["prefill_tokens_per_second"], 18.4)

	def _args(self, root: Path, out: Path, err: Path):
		args = type("Args", (), {})()
		args.stdout = str(out)
		args.stderr = str(err)
		args.rc = 0
		args.run_id = "unit-run"
		args.case_id = "unit-case"
		args.model_id = "deepseek-ai/DeepSeek-V4-Flash"
		args.runtime_id = "unit-runtime"
		args.quantization_id = "unit.gguf"
		args.spark_node = "spark-unit"
		args.component_kind = "output_head"
		args.batch_size = 1
		args.input_tokens = 0
		args.context_tokens = 0
		args.active_sessions = 0
		args.layers_executed = 0
		args.includes_output_head = False
		args.includes_attention = False
		args.includes_kv = False
		args.includes_sampling = False
		args.component_only = False
		args.prefix_hit = "unknown"
		args.prefix_tier = ""
		args.prefix_load_ms = None
		args.suffix_prefill_ms = None
		args.kv_bytes_reserved = 0
		args.failure_status = ""
		args.blocker_kind = ""
		args.blocker_detail = ""
		args.warmup_policy = "unit"
		args.residency_policy = "unit"
		return args


if __name__ == "__main__":
	unittest.main()
