import unittest

from scripts import summarize_mtp_one_token_draft_probe_diff as summarize
from scripts import verify_mtp_one_token_draft_probe_captures as captures


def _probe_with_captures() -> dict:
	out = {
		"runtime_repo": "repo",
		"runtime_commit": "deadbeef",
		"trunk_gguf_path": "/trunk.gguf",
		"mtp_sidecar_path": "/sidecar.gguf",
		"prompt": "hi",
		"base_next_token_id": 1,
		"mtp_draft_token_id": 2,
	}
	for prefix in captures.DEFAULT_REQUIRED_PREFIXES:
		out[f"{prefix}_fnv64"] = "0000000000000000"
		out[f"{prefix}_nbytes"] = 16
		out[f"{prefix}_shape"] = [4, 1, 1]
	return out


class MtpOneTokenProbeCaptureGateTest(unittest.TestCase):
	def test_capture_gate_ok_with_defaults(self) -> None:
		probe = _probe_with_captures()
		res = captures.verify_required_captures(probe, required_prefixes=list(captures.DEFAULT_REQUIRED_PREFIXES))
		self.assertTrue(bool(res.get("ok", False)))
		self.assertEqual(res.get("errors"), [])

	def test_capture_gate_allows_optional_sample_f32(self) -> None:
		probe = _probe_with_captures()
		probe["mtp_head_norm_sample_f32"] = [0.0, 1.25, -2.5]
		res = captures.verify_required_captures(probe, required_prefixes=list(captures.DEFAULT_REQUIRED_PREFIXES))
		self.assertTrue(bool(res.get("ok", False)))

	def test_capture_gate_rejects_empty_sample_f32(self) -> None:
		probe = _probe_with_captures()
		probe["mtp_head_norm_sample_f32"] = []
		res = captures.verify_required_captures(probe, required_prefixes=list(captures.DEFAULT_REQUIRED_PREFIXES))
		self.assertFalse(bool(res.get("ok", True)))
		errors = res.get("errors") or []
		self.assertTrue(any("mtp_head_norm_sample_f32" in str(e) for e in errors))

	def test_capture_gate_fails_when_missing_prefix(self) -> None:
		probe = _probe_with_captures()
		for suffix in ("_fnv64", "_nbytes", "_shape"):
			probe.pop("mtp_block_out_hc" + suffix, None)
		res = captures.verify_required_captures(probe, required_prefixes=list(captures.DEFAULT_REQUIRED_PREFIXES))
		self.assertFalse(bool(res.get("ok", True)))
		errors = res.get("errors") or []
		self.assertTrue(any("missing capture prefix: mtp_block_out_hc" in str(e) for e in errors))

	def test_diff_summary_reports_first_capture_mismatch(self) -> None:
		a = _probe_with_captures()
		b = _probe_with_captures()
		b["mtp_input_hc_fnv64"] = "0000000000000001"
		res = summarize.summarize_one_token_mtp_probe_diff(a, b, stage_order=list(summarize.DEFAULT_STAGE_ORDER))
		self.assertFalse(bool(res.get("ok", True)))
		first = res.get("first_mismatch") or {}
		self.assertEqual(first.get("kind"), "capture")
		self.assertEqual(first.get("prefix"), "mtp_input_hc")

	def test_diff_summary_reports_sample_mismatch_before_capture(self) -> None:
		a = _probe_with_captures()
		b = _probe_with_captures()
		a["mtp_input_hc_sample_f32"] = [0.0, 1.0]
		b["mtp_input_hc_sample_f32"] = [0.0, 1.1]
		res = summarize.summarize_one_token_mtp_probe_diff(a, b, stage_order=list(summarize.DEFAULT_STAGE_ORDER))
		self.assertFalse(bool(res.get("ok", True)))
		first = res.get("first_mismatch") or {}
		self.assertEqual(first.get("kind"), "sample")
		self.assertEqual(first.get("prefix"), "mtp_input_hc")

	def test_diff_summary_reports_token_mismatch_first(self) -> None:
		a = _probe_with_captures()
		b = _probe_with_captures()
		b["mtp_draft_token_id"] = 999
		res = summarize.summarize_one_token_mtp_probe_diff(a, b, stage_order=list(summarize.DEFAULT_STAGE_ORDER))
		self.assertFalse(bool(res.get("ok", True)))
		first = res.get("first_mismatch") or {}
		self.assertEqual(first.get("kind"), "token")
		self.assertEqual(first.get("key"), "mtp_draft_token_id")
