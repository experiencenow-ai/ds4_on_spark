import unittest

from scripts import compare_mtp_one_token_hc_layout as compare


def _oracle_probe() -> dict:
	return {
		"trunk_token_embd_fnv64": "0000000000000001",
		"trunk_pre_hc_head_fnv64": "0000000000000002",
		"mtp_input_hc_fnv64": "0000000000000003",
		"mtp_block_out_hc_fnv64": "0000000000000004",
	}


def _candidate_probe() -> dict:
	return {
		"trunk_token_embd_fnv64": "0000000000000001",
		"trunk_pre_hc_head_fnv64": "ffffffffffffffff",
		"trunk_pre_hc_head_hc_major_fnv64": "0000000000000002",
		"mtp_input_hc_fnv64": "ffffffffffffffff",
		"mtp_input_hc_hc_major_fnv64": "0000000000000003",
		"mtp_block_out_hc_fnv64": "ffffffffffffffff",
		"mtp_block_out_hc_hc_major_fnv64": "0000000000000004",
	}


class MtpOneTokenHcLayoutCompareTest(unittest.TestCase):
	def test_compare_ok_when_hc_major_matches(self) -> None:
		res = compare.compare(_oracle_probe(), _candidate_probe())
		self.assertTrue(bool(res.get("ok", False)))
		self.assertTrue(bool(res.get("layout_matches_all_hc", False)))
		self.assertTrue(bool(res.get("trunk_token_embd_raw_match", False)))

	def test_compare_fails_when_hc_major_missing(self) -> None:
		oracle = _oracle_probe()
		cand = _candidate_probe()
		cand.pop("mtp_input_hc_hc_major_fnv64", None)
		res = compare.compare(oracle, cand)
		self.assertFalse(bool(res.get("ok", True)))
		self.assertFalse(bool(res.get("layout_matches_all_hc", True)))

