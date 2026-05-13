import unittest

from scripts import verify_mtp_one_token_draft_probe_captures as cap


def _probe_with(prefixes: list[str]) -> dict:
	out: dict = {
		"runtime_repo": "repo",
		"runtime_commit": "deadbeef",
		"trunk_gguf_path": "/trunk.gguf",
		"mtp_sidecar_path": "/sidecar.gguf",
		"prompt": "hi",
		"seed": 1,
		"temperature": 0.0,
		"top_k": 1,
		"top_p": 1.0,
		"verify_step_idx": 0,
		"base_next_token_id": 1,
		"mtp_draft_token_id": 2,
		"ok": True,
		"errors": [],
		"mtp_params": {},
	}
	for p in prefixes:
		out[f"{p}_fnv64"] = "0000000000000000"
		out[f"{p}_nbytes"] = 16
		out[f"{p}_shape"] = [1, 1, 4]
	return out


class MtpOneTokenProbeCapturesTest(unittest.TestCase):
	def test_default_profile_requires_prefixes(self) -> None:
		probe = _probe_with(["trunk_token_embd"])
		res = cap.verify_probe_captures(probe, profile="default")
		self.assertFalse(bool(res.get("ok", True)))
		missing = res.get("missing_prefixes") or []
		self.assertIn("trunk_pre_hc_head", missing)

	def test_extended_profile_requires_deeper_captures(self) -> None:
		probe = _probe_with(cap.DEFAULT_PREFIXES)
		res = cap.verify_probe_captures(probe, profile="extended")
		self.assertFalse(bool(res.get("ok", True)))
		missing = res.get("missing_prefixes") or []
		self.assertIn("mtp_eproj_hc", missing)

	def test_ok_when_all_default_prefixes_present(self) -> None:
		probe = _probe_with(cap.DEFAULT_PREFIXES)
		res = cap.verify_probe_captures(probe, profile="default")
		self.assertTrue(bool(res.get("ok", False)))
		self.assertEqual(res.get("missing_prefixes"), [])

