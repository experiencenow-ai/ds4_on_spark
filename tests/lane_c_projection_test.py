import json
import math
from pathlib import Path
import statistics
import unittest


FIXTURE = Path("fixtures/pipeline_one_prompt/lane_a2_64tok_spark234_pp3_20260521T0200Z.stdout")
VLLM_FIXTURE = Path("fixtures/standard_runtime_benchmarks/vllm_deepseek_v4_flash_tp2_no_mtp_spark45_batch_sweep_20260521.example.json")
ROUNDED_TARGET_TOK_S = 310.0


def load_pp3_record(path: Path) -> dict:
	text = path.read_text(encoding="utf-8")
	start = text.index("{")
	record, _ = json.JSONDecoder().raw_decode(text[start:])
	return record


def load_json_record(path: Path) -> dict:
	return json.loads(path.read_text(encoding="utf-8"))


def vllm_concurrency_target_tok_s(record: dict, concurrency: int) -> float:
	for summary in record["concurrency_summaries"]:
		if summary["concurrency"] == concurrency:
			return float(summary["mean_aggregate_tps"])
	raise ValueError(f"missing concurrency {concurrency}")


def bottleneck_stage_mean_ms(stage_elapsed_ms: list[list[float]]) -> tuple[int, float, list[float]]:
	if len(stage_elapsed_ms) < 2:
		raise ValueError("stage_elapsed_ms must include step0 plus steady steps")
	stage_count = len(stage_elapsed_ms[0])
	steady = stage_elapsed_ms[1:]
	stage_means = [
		statistics.mean(row[stage_id] for row in steady)
		for stage_id in range(stage_count)
	]
	bottleneck = max(range(stage_count), key=lambda idx: stage_means[idx])
	return bottleneck, stage_means[bottleneck], stage_means


def projected_tok_s(k: int, bottleneck_ms: float) -> float:
	return float(k) * 1000.0 / bottleneck_ms


def minimum_k_to_beat(target_tok_s: float, bottleneck_ms: float) -> int:
	return math.floor(target_tok_s * bottleneck_ms / 1000.0) + 1


class LaneCProjectionTest(unittest.TestCase):
	def test_stage_bottleneck_projection_formula(self) -> None:
		record = load_pp3_record(FIXTURE)
		vllm_record = load_json_record(VLLM_FIXTURE)
		target_tok_s = vllm_concurrency_target_tok_s(vllm_record, 64)
		stage_elapsed_ms = [step["stage_elapsed_ms"] for step in record["steps"]]
		stage_id, bottleneck_ms, stage_means = bottleneck_stage_mean_ms(stage_elapsed_ms)
		k_min = minimum_k_to_beat(target_tok_s, bottleneck_ms)
		self.assertAlmostEqual(target_tok_s, 310.31684000791483)
		self.assertEqual(stage_id, 0)
		self.assertAlmostEqual(stage_means[0], 1988.8237936507937)
		self.assertAlmostEqual(stage_means[1], 1936.084492063492)
		self.assertAlmostEqual(stage_means[2], 1933.0659047619047)
		self.assertEqual(k_min, 618)
		self.assertLessEqual(projected_tok_s(k_min - 1, bottleneck_ms), target_tok_s)
		self.assertGreater(projected_tok_s(k_min, bottleneck_ms), target_tok_s)
		self.assertAlmostEqual(projected_tok_s(512, bottleneck_ms), 257.4385934211622)

	def test_naive_b1_projection_is_not_the_stage_bottleneck_projection(self) -> None:
		record = load_pp3_record(FIXTURE)
		steady_tok_s = float(record["steady_tok_s_excluding_step0"])
		naive_k = math.floor(ROUNDED_TARGET_TOK_S / steady_tok_s) + 1
		self.assertAlmostEqual(steady_tok_s, 0.7765547550855313)
		self.assertEqual(naive_k, 400)


if __name__ == "__main__":
	unittest.main()
