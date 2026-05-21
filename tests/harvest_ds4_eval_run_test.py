import gzip
import io
import json
import tempfile
import unittest
from contextlib import redirect_stdout
from pathlib import Path

from scripts import harvest_ds4_eval_run as harvest

from tests.pipeline_quality_regression_test import DS4_EVAL_TRACE


class HarvestDs4EvalRunTest(unittest.TestCase):
	def test_harvest_writes_quality_throughput_and_raw_artifacts(self) -> None:
		with tempfile.TemporaryDirectory() as d:
			root = Path(d)
			trace = root / "run.trace"
			stdout = root / "run.stdout"
			rc = root / "run.rc"
			out_dir = root / "fixtures"
			trace.write_text(DS4_EVAL_TRACE, encoding="utf-8")
			stdout.write_text("stdout evidence\n", encoding="utf-8")
			rc.write_text("0\n", encoding="utf-8")
			with redirect_stdout(io.StringIO()) as buf:
				code = harvest.main([
					"--run-id", "unit-ds4-eval-run",
					"--runner-id", "unit-runner",
					"--trace", str(trace),
					"--stdout", str(stdout),
					"--rc", str(rc),
					"--out-dir", str(out_dir),
					"--command", "ssh spark6 ./ds4-eval --cuda",
				])
			self.assertEqual(code, 0)
			result = json.loads(buf.getvalue())
			self.assertEqual(result["question_count"], 2)
			self.assertEqual(result["passed"], 1)
			self.assertEqual(result["failed"], 1)
			self.assertEqual(result["ds4_eval_returncode"], 0)
			self.assertEqual(result["trace_wall_elapsed_sec"], 3.5)
			artifacts = {name: Path(path) for name, path in result["artifacts"].items()}
			for path in artifacts.values():
				self.assertTrue(path.exists(), path)
			summary = json.loads(artifacts["summary"].read_text(encoding="utf-8"))
			throughput = json.loads(artifacts["throughput"].read_text(encoding="utf-8"))
			self.assertEqual(summary["ds4_eval_command"], "ssh spark6 ./ds4-eval --cuda")
			self.assertEqual(throughput["trace_wall_elapsed_sec"], 3.5)
			self.assertEqual(throughput["ds4_eval_returncode"], 0)
			self.assertEqual(artifacts["rc"].read_text(encoding="utf-8"), "0\n")
			with gzip.open(artifacts["stdout"], "rt", encoding="utf-8") as f:
				self.assertEqual(f.read(), "stdout evidence\n")

	def test_harvest_rejects_unsafe_run_id(self) -> None:
		with tempfile.TemporaryDirectory() as d:
			root = Path(d)
			trace = root / "run.trace"
			stdout = root / "run.stdout"
			rc = root / "run.rc"
			trace.write_text(DS4_EVAL_TRACE, encoding="utf-8")
			stdout.write_text("stdout evidence\n", encoding="utf-8")
			rc.write_text("0\n", encoding="utf-8")
			with self.assertRaises(ValueError):
				harvest.harvest(harvest.build_parser().parse_args([
					"--run-id", "../bad",
					"--trace", str(trace),
					"--stdout", str(stdout),
					"--rc", str(rc),
					"--out-dir", str(root / "fixtures"),
				]))


if __name__ == "__main__":
	unittest.main()
