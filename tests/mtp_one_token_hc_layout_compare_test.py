import unittest

from scripts import compare_mtp_one_token_hc_layout as cmp


def _probe() -> dict:
	return {
		"runtime_repo": "repo",
		"runtime_commit": "deadbeef",
		"trunk_gguf_path": "/trunk.gguf",
		"mtp_sidecar_path": "/sidecar.gguf",
		"prompt": "hi",
		"base_next_token_id": 1,
		"mtp_draft_token_id": 2,
		"trunk_pre_hc_head_fnv64": "0000000000000000",
		"trunk_pre_hc_head_hc_major_fnv64": "1111111111111111",
	}


class MtpOneTokenHcLayoutCompareTest(unittest.TestCase):
	def test_compare_emits_pair_grid(self) -> None:
		a = _probe()
		b = _probe()
		out = cmp.compare_hc_layout(a, b)
		self.assertTrue(bool(out.get("ok", False)))
		pairs = out.get("pairs") or []
		self.assertTrue(any(p.get("b_key", "").endswith("_hc_major_fnv64") for p in pairs))

