import json
import tempfile
import unittest
from collections import Counter
import contextlib
import io
from pathlib import Path
import sys

from scripts import bench_pipeline_batch_vs_serial as bench
from scripts.pipeline_batch_scheduler import (
	DecodeRow,
	DecodeToken,
	PipelineBatchScheduler,
	PipelineBatchSchedulerError,
	PromptRequest,
)


PATCH = Path("docs/antirez-patches/ds4-3630e64-cuda-pipeline-row-replacement.patch")


class FakeBatchBackend:
	def __init__(self, token_ids_by_request: dict[str, tuple[int, ...]], k: int):
		self.token_ids_by_request = token_ids_by_request
		self.k = k
		self.active_rows: dict[int, str] = {}
		self.decode_batch_widths: list[int] = []
		self.prefill_log: list[tuple[int, str]] = []
		self.reset_log: list[int] = []

	def prefill_row(self, row_index: int, request: PromptRequest) -> None:
		if row_index in self.active_rows:
			raise AssertionError(f"row {row_index} reused before reset")
		self.active_rows[row_index] = request.request_id
		self.prefill_log.append((row_index, request.request_id))

	def decode_batch(self, rows: list[DecodeRow]) -> list[DecodeToken]:
		if len(rows) != self.k:
			raise AssertionError(f"decode width {len(rows)} != k {self.k}")
		self.decode_batch_widths.append(len(rows))
		outputs: list[DecodeToken] = []
		for row in rows:
			if not row.active:
				continue
			if self.active_rows.get(row.row_index) != row.request_id:
				raise AssertionError(f"row {row.row_index} active request mismatch")
			tokens = self.token_ids_by_request[row.request_id]
			pos = len(row.generated_token_ids)
			if pos >= len(tokens):
				outputs.append(DecodeToken(row.row_index, None, True))
			else:
				outputs.append(DecodeToken(row.row_index, tokens[pos], False, f"{tokens[pos]} "))
		return outputs

	def reset_row(self, row_index: int) -> None:
		if row_index not in self.active_rows:
			raise AssertionError(f"row {row_index} reset while inactive")
		self.reset_log.append(row_index)
		del self.active_rows[row_index]


def make_requests(count: int) -> list[PromptRequest]:
	lengths = [5, 8, 13, 21, 34, 55, 80, 7, 11, 17]
	return [
		PromptRequest(f"req{i}", f"prompt {i} with distinct content", lengths[i % len(lengths)])
		for i in range(count)
	]


def serial_tokens(requests: list[PromptRequest]) -> dict[str, tuple[int, ...]]:
	return {
		request.request_id: tuple((idx + 1) * 100000 + j for j in range(request.max_tokens))
		for idx, request in enumerate(requests)
	}


def read_events(path: Path) -> list[dict[str, object]]:
	return [
		json.loads(line)
		for line in path.read_text(encoding="utf-8").splitlines()
		if line.strip()
	]


class PipelineBatchSchedulerTest(unittest.TestCase):
	def test_k8_eight_prompt_token_match_against_serial(self) -> None:
		requests = make_requests(8)
		expected = serial_tokens(requests)
		backend = FakeBatchBackend(expected, 8)
		with tempfile.TemporaryDirectory() as td:
			events_path = Path(td) / "scheduler_events.jsonl"
			summary = PipelineBatchScheduler(backend, 8).run(requests, events_path)
		self.assertEqual(summary.request_count, 8)
		self.assertEqual(len(summary.results), 8)
		for result in summary.results:
			self.assertEqual(result.token_ids, expected[result.request_id])
		self.assertTrue(all(width == 8 for width in backend.decode_batch_widths))

	def test_scheduler_is_parametric_and_churns_rows(self) -> None:
		for k in (2, 4, 8):
			requests = make_requests(k + 2)
			expected = serial_tokens(requests)
			backend = FakeBatchBackend(expected, k)
			with tempfile.TemporaryDirectory() as td:
				events_path = Path(td) / "scheduler_events.jsonl"
				summary = PipelineBatchScheduler(backend, k).run(requests, events_path)
				events = read_events(events_path)
			self.assertEqual(summary.k, k)
			self.assertEqual(len(summary.results), len(requests))
			self.assertTrue(all(width == k for width in backend.decode_batch_widths))
			for result in summary.results:
				self.assertEqual(result.token_ids, expected[result.request_id])
			self.assertTrue(any(event["event"] == "admit" for event in events))
			self.assertTrue(any(event["event"] == "evict" for event in events))
			for event in events:
				self.assertIn("row_index", event)
				self.assertIn("wall_time", event)
				self.assertIn("wall_time_ns", event)
			admit_counts = Counter(int(event["row_index"]) for event in events if event["event"] == "admit")
			self.assertGreaterEqual(max(admit_counts.values()), 2)

	def test_reuse_requires_reset_before_prefill(self) -> None:
		requests = make_requests(3)
		expected = serial_tokens(requests)
		backend = FakeBatchBackend(expected, 2)
		with tempfile.TemporaryDirectory() as td:
			PipelineBatchScheduler(backend, 2).run(requests, Path(td) / "scheduler_events.jsonl")
		self.assertIn(0, backend.reset_log)
		self.assertEqual(backend.prefill_log[0][0], 0)
		self.assertEqual(backend.prefill_log[2][0], 0)

	def test_rejects_duplicate_ids_and_bad_k(self) -> None:
		backend = FakeBatchBackend({"dup": (1,)}, 1)
		with self.assertRaises(PipelineBatchSchedulerError):
			PipelineBatchScheduler(backend, 0)
		with self.assertRaises(PipelineBatchSchedulerError):
			PipelineBatchScheduler(backend, 1).run(
				[
					PromptRequest("dup", "one", 1),
					PromptRequest("dup", "two", 1),
				],
				None,
			)

	def test_row_replacement_patch_contract(self) -> None:
		text = PATCH.read_text(encoding="utf-8")
		for needle in (
			"DS4_CUDA_STACK_PROBE_ROW_REPLACEMENT",
			"DS4_CUDA_STACK_PROBE_SLOT_RESET_ROWS",
			"cuda_stack_probe_reset_slot_row(",
			"ds4_gpu_tensor_write(g->prefill_tokens,",
			"ds4_gpu_tensor_write(g->batch_cur_hc,",
			"row_replacement_enabled",
			"row_replace_count",
		):
			self.assertIn(needle, text)
		self.assertNotIn("K=3", text)
		self.assertNotIn("spark_count", text)
		self.assertNotIn("production_generation_eligible", text)

	def test_bench_cli_runs_fake_b8_multiplexer(self) -> None:
		module_text = """
from scripts.pipeline_batch_scheduler import DecodeToken

class FakeBackend:
\tdef __init__(self, requests):
\t\tself.tokens = {r.request_id: tuple((i + 1) * 1000 + j for j in range(r.max_tokens)) for i, r in enumerate(requests)}
\tdef prefill_row(self, row_index, request):
\t\treturn None
\tdef decode_batch(self, rows):
\t\tout = []
\t\tfor row in rows:
\t\t\tif not row.active:
\t\t\t\tcontinue
\t\t\tpos = len(row.generated_token_ids)
\t\t\ttokens = self.tokens[row.request_id]
\t\t\tif pos >= len(tokens):
\t\t\t\tout.append(DecodeToken(row.row_index, None, True))
\t\t\telse:
\t\t\t\tout.append(DecodeToken(row.row_index, tokens[pos], False, str(tokens[pos])))
\t\treturn out
\tdef reset_row(self, row_index):
\t\treturn None

_requests = ()

def run_serial_pp1_baseline(args, requests):
\tglobal _requests
\t_requests = tuple(requests)
\treturn [
\t\t{
\t\t\t\"request_id\": r.request_id,
\t\t\t\"token_ids\": [(i + 1) * 1000 + j for j in range(r.max_tokens)],
\t\t\t\"tok_s\": 1.0,
\t\t\t\"wall_seconds\": float(r.max_tokens),
\t\t}
\t\tfor i, r in enumerate(requests)
\t]

def make_pipeline_batch_backend(args):
\treturn FakeBackend(_requests)
"""
		with tempfile.TemporaryDirectory() as td:
			root = Path(td)
			(root / "fake_lane_c_backend.py").write_text(module_text, encoding="utf-8")
			sys.path.insert(0, td)
			try:
				with contextlib.redirect_stdout(io.StringIO()):
					rc = bench.main([
						"--out-dir",
						str(root / "out"),
						"--backend-module",
						"fake_lane_c_backend",
						"--k",
						"8",
						"--min-speedup",
						"2.0",
					])
			finally:
				sys.path.remove(td)
			self.assertEqual(rc, 0)
			obj = json.loads((root / "out" / "bench_pipeline_batch_vs_serial.json").read_text(encoding="utf-8"))
			self.assertTrue(obj["token_id_match"])
			self.assertGreaterEqual(obj["speedup_vs_sum_serial"], 2.0)
			self.assertTrue((root / "out" / "scheduler_events.jsonl").exists())

	def test_bench_cli_accepts_pipeline_session_style_backend(self) -> None:
		module_text = """
from scripts.pipeline_batch_scheduler import DecodeToken

def _tokens(prompt, n):
\tbase = sum(ord(c) for c in prompt)
\treturn [base + i for i in range(n)]

class PromptRun:
\tdef __init__(self, prompt, token_ids):
\t\tself.prompt = prompt
\t\tself.generated_token_ids = token_ids

def load_stage_manifest(path):
\treturn [path]

class PipelineSession:
\tdef __init__(self, stages=None):
\t\tself.stages = stages
\t\tself.rows = {}
\tdef run_pp1_baseline(self, prompt, max_tokens, out_dir):
\t\treturn PromptRun(prompt, _tokens(prompt, max_tokens))
\tdef prefill_row(self, row_index, request):
\t\tself.rows[row_index] = request
\tdef decode_batch(self, rows):
\t\tout = []
\t\tfor row in rows:
\t\t\tif not row.active:
\t\t\t\tcontinue
\t\t\trequest = self.rows[row.row_index]
\t\t\tpos = len(row.generated_token_ids)
\t\t\tout.append(DecodeToken(row.row_index, _tokens(request.prompt, request.max_tokens)[pos], False, \"\"))
\t\treturn out
\tdef reset_row(self, row_index):
\t\tdel self.rows[row_index]
"""
		with tempfile.TemporaryDirectory() as td:
			root = Path(td)
			(root / "fake_session_backend.py").write_text(module_text, encoding="utf-8")
			requests_path = root / "requests.json"
			requests_path.write_text(json.dumps([
				{"request_id": "a", "prompt": "alpha", "max_tokens": 3},
				{"request_id": "b", "prompt": "beta", "max_tokens": 5},
			]), encoding="utf-8")
			manifest_path = root / "manifest.json"
			manifest_path.write_text("[]", encoding="utf-8")
			sys.path.insert(0, td)
			try:
				with contextlib.redirect_stdout(io.StringIO()):
					rc = bench.main([
						"--requests",
						str(requests_path),
						"--out-dir",
						str(root / "out"),
						"--backend-module",
						"fake_session_backend",
						"--stage-manifest",
						str(manifest_path),
						"--k",
						"2",
						"--min-speedup",
						"0",
					])
			finally:
				sys.path.remove(td)
			self.assertEqual(rc, 0)
			obj = json.loads((root / "out" / "bench_pipeline_batch_vs_serial.json").read_text(encoding="utf-8"))
			self.assertTrue(obj["token_id_match"])


if __name__ == "__main__":
	unittest.main()
