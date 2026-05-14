import json
import subprocess
import tempfile
import unittest
from pathlib import Path

from scripts import analyze_ds4_moe_profile as analyze


class AnalyzeDs4MoeProfileTest(unittest.TestCase):
	def test_runtime_diagnostics_capture_cuda_failures(self) -> None:
		text = "\n".join([
			"ds4: CUDA startup model cache prepared 20.25 GiB from model tensor spans in 8.50s",
			"ds4: CUDA MoE expert slice cache prepared 6 selected experts (912.50 MiB)",
			"ds4: CUDA tensor alloc failed: the launch timed out and was terminated",
			"ds4: CUDA model range alloc failed for moe_gate: an illegal memory access was encountered",
		])
		result = analyze.analyze_runtime_text(text)
		self.assertEqual(result["launch_timeout_count"], 1)
		self.assertEqual(result["illegal_memory_count"], 1)
		self.assertEqual(result["tensor_alloc_failed_count"], 1)
		self.assertEqual(result["range_alloc_failed_count"], 1)
		self.assertEqual(result["expert_slice_events"], [{"experts": 6, "mib": 912.5}])
		self.assertEqual(result["startup_ready_events"], [{"gib": 20.25, "seconds": 8.5}])

	def test_json_cli_reports_profiles_and_recommendations(self) -> None:
		with tempfile.TemporaryDirectory() as tmp:
			path = Path(tmp) / "ds4.err"
			path.write_text("\n".join([
				"ds4: CUDA MoE profile tokens=12 pairs=72 xq=0.100 sort=0.200 gateup=1.300 midq=0.400 down=0.700 sum=0.050 total=2.750 ms",
				"ds4: CUDA MoE profile tokens=12 pairs=72 xq=0.200 sort=0.300 gateup=1.500 midq=0.600 down=0.900 sum=0.070 total=3.570 ms",
				"ds4: accelerator stopped startup model cache after 11.00 GiB at tensor span 9",
				"ds4: CUDA tensor alloc failed: the launch timed out and was terminated",
			]), encoding="utf-8")
			proc = subprocess.run(
				["python3", "scripts/analyze_ds4_moe_profile.py", "--json", str(path)],
				stdout=subprocess.PIPE,
				stderr=subprocess.PIPE,
				text=True,
				check=True,
			)
		payload = json.loads(proc.stdout)
		entry = payload["logs"][0]
		self.assertEqual(entry["profiles"][0]["tokens"], 12)
		self.assertEqual(entry["profiles"][0]["records"], 2)
		self.assertAlmostEqual(entry["profiles"][0]["total_ms_median"], 3.16)
		self.assertEqual(entry["runtime"]["launch_timeout_count"], 1)
		self.assertEqual(entry["runtime"]["startup_stop_events"], [{"gib": 11.0, "tensor_span": 9}])
		self.assertTrue(entry["runtime"]["recommendations"])


if __name__ == "__main__":
	unittest.main()
