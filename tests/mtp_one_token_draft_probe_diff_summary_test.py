import unittest

from scripts import summarize_mtp_one_token_draft_probe_diff as summary


def _base_probe() -> dict:
	return {
		"runtime_repo": "repo",
		"runtime_commit": "deadbeef",
		"trunk_gguf_path": "/trunk.gguf",
		"mtp_sidecar_path": "/sidecar.gguf",
		"prompt": "hi",
		"base_next_token_id": 1,
		"mtp_draft_token_id": 2,
		"trunk_token_embd_fnv64": "0000000000000000",
		"trunk_token_embd_nbytes": 16,
		"trunk_token_embd_shape": [4, 1, 1],
		"trunk_token_embd_sample_f32": [0.0, 1.0, 2.0, 3.0],
	}


class MtpOneTokenProbeDiffSummaryTest(unittest.TestCase):
	def test_summary_marks_sample_mismatch_by_default(self) -> None:
		a = _base_probe()
		b = _base_probe()
		b["trunk_token_embd_sample_f32"] = [0.0, 1.0, 2.0, 3.1]
		res = summary.summarize_one_token_mtp_probe_diff(a, b, stage_order=["trunk_token_embd"])
		self.assertFalse(bool(res.get("ok", True)))
		first = res.get("first_mismatch") or {}
		self.assertEqual(first.get("kind"), "sample")
		self.assertEqual(first.get("prefix"), "trunk_token_embd")

	def test_summary_respects_relaxed_sample_tol(self) -> None:
		a = _base_probe()
		b = _base_probe()
		b["trunk_token_embd_sample_f32"] = [0.0, 1.0, 2.0, 3.1]
		res = summary.summarize_one_token_mtp_probe_diff(a, b, stage_order=["trunk_token_embd"], sample_tol=0.11)
		self.assertTrue(bool(res.get("ok", False)))
