import unittest

from scripts import diff_mtp_one_token_draft_probe as diff


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
	}


class MtpOneTokenProbeDiffTest(unittest.TestCase):
	def test_diff_ok_when_equal(self) -> None:
		a = _base_probe()
		b = _base_probe()
		res = diff.diff_one_token_mtp_probes(a, b)
		self.assertTrue(bool(res.get("ok", False)))
		self.assertEqual(res.get("errors"), [])
		self.assertEqual(res.get("mismatches"), [])

	def test_diff_detects_token_mismatch(self) -> None:
		a = _base_probe()
		b = _base_probe()
		b["mtp_draft_token_id"] = 9
		res = diff.diff_one_token_mtp_probes(a, b)
		self.assertFalse(bool(res.get("ok", True)))
		mismatches = res.get("mismatches") or []
		keys = [m.get("key") for m in mismatches]
		self.assertIn("mtp_draft_token_id", keys)

	def test_diff_detects_capture_mismatch(self) -> None:
		a = _base_probe()
		b = _base_probe()
		b["trunk_token_embd_fnv64"] = "0000000000000001"
		res = diff.diff_one_token_mtp_probes(a, b)
		self.assertFalse(bool(res.get("ok", True)))
		mismatches = res.get("mismatches") or []
		keys = [m.get("key") for m in mismatches]
		self.assertIn("trunk_token_embd_fnv64", keys)

	def test_diff_rejects_bad_fnv_hex(self) -> None:
		a = _base_probe()
		b = _base_probe()
		b["trunk_token_embd_fnv64"] = "XYZ"
		res = diff.diff_one_token_mtp_probes(a, b)
		self.assertFalse(bool(res.get("ok", True)))
		errors = res.get("errors") or []
		self.assertTrue(any("not a 16-nybble" in str(e) for e in errors))

