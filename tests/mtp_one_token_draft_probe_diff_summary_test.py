import unittest

from scripts import summarize_mtp_one_token_draft_probe_diff as summ


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
		"trunk_pre_hc_head_fnv64": "0000000000000000",
		"trunk_pre_hc_head_nbytes": 16,
		"trunk_pre_hc_head_shape": [4, 1, 1],
		"mtp_input_hc_fnv64": "0000000000000000",
		"mtp_input_hc_nbytes": 16,
		"mtp_input_hc_shape": [4, 1, 1],
		"mtp_block_out_hc_fnv64": "0000000000000000",
		"mtp_block_out_hc_nbytes": 16,
		"mtp_block_out_hc_shape": [4, 1, 1],
		"mtp_head_norm_fnv64": "0000000000000000",
		"mtp_head_norm_nbytes": 16,
		"mtp_head_norm_shape": [4, 1, 1],
	}


class MtpOneTokenProbeDiffSummaryTest(unittest.TestCase):
	def test_first_diverge_null_when_equal(self) -> None:
		a = _base_probe()
		b = _base_probe()
		out = summ.summarize_one_token_diff(a, b, sample_tol=1.0e-5)
		self.assertTrue(bool(out.get("ok", False)))
		self.assertIsNone(out.get("first_diverge", None))

	def test_first_diverge_reports_mismatch_prefix(self) -> None:
		a = _base_probe()
		b = _base_probe()
		b["mtp_input_hc_fnv64"] = "0000000000000001"
		out = summ.summarize_one_token_diff(a, b, sample_tol=1.0e-5)
		self.assertFalse(bool(out.get("ok", True)))
		self.assertEqual(out.get("first_diverge", None), "mtp_input_hc")

