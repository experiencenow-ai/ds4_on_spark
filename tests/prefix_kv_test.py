import copy
import unittest
from pathlib import Path

from scripts import validate_ds4_prefix_kv as prefix_kv


FIX = Path("fixtures/prefix_kv")


class PrefixKvTest(unittest.TestCase):
	def test_prefix_kv_fixtures_validate(self) -> None:
		for path in sorted(FIX.glob("*.json")):
			with self.subTest(path=path.name):
				self.assertEqual(prefix_kv.validate_artifact(prefix_kv.load_json(path)), [])

	def test_cache_hit_rejects_token_sha_mismatch(self) -> None:
		obj = copy.deepcopy(prefix_kv.load_json(FIX / "prefix_cache_hit.example.json"))
		obj["token_ids_sha256"] = "sha256:different-prefix-tokens"
		errors = prefix_kv.validate_artifact(obj)
		self.assertTrue(any("token SHA mismatch" in error for error in errors))

	def test_cache_hit_rejects_identity_mismatch(self) -> None:
		obj = copy.deepcopy(prefix_kv.load_json(FIX / "prefix_cache_hit.example.json"))
		obj["runtime_id"] = "different-runtime"
		errors = prefix_kv.validate_artifact(obj)
		self.assertTrue(any("runtime_id" in error for error in errors))

	def test_prefix_required_miss_must_defer_or_reject(self) -> None:
		obj = copy.deepcopy(prefix_kv.load_json(FIX / "prefix_prepare_blocked_missing_runtime.example.json"))
		obj["status"] = "miss"
		obj["miss_policy"] = "none"
		errors = prefix_kv.validate_artifact(obj)
		self.assertTrue(any("prefix_required=true" in error for error in errors))

	def test_invalid_continuation_must_block(self) -> None:
		obj = copy.deepcopy(prefix_kv.load_json(FIX / "session_append_blocked_missing_runtime.example.json"))
		obj["continuation_valid"] = False
		obj["status"] = "appended"
		obj["blocker_detail"] = "none"
		errors = prefix_kv.validate_artifact(obj)
		self.assertTrue(any("invalid continuation" in error for error in errors))

	def test_fragment_kv_concat_is_rejected(self) -> None:
		obj = copy.deepcopy(prefix_kv.load_json(FIX / "session_append_blocked_missing_runtime.example.json"))
		obj["kv_concat_mode"] = "fragment_concat"
		errors = prefix_kv.validate_artifact(obj)
		self.assertTrue(any("fragment KV concatenation" in error for error in errors))

	def test_blocked_prefix_op_names_exact_runtime_hook(self) -> None:
		obj = prefix_kv.load_json(FIX / "prefix_prepare_blocked_missing_runtime.example.json")
		self.assertEqual(obj["runtime_hook"], "ds4_runtime_prefix_prepare")
		obj = copy.deepcopy(obj)
		obj["runtime_hook"] = "ds4_runtime_session_decode"
		errors = prefix_kv.validate_artifact(obj)
		self.assertTrue(any("runtime_hook must be ds4_runtime_prefix_prepare" in error for error in errors))

	def test_blocked_session_decode_names_exact_runtime_hook(self) -> None:
		obj = prefix_kv.load_json(FIX / "session_decode_blocked_missing_runtime.example.json")
		self.assertEqual(obj["runtime_hook"], "ds4_runtime_session_decode")

	def test_all_required_prefix_kv_operations_have_exact_blocker_hooks(self) -> None:
		cases = {
			"prefix_prepare_blocked_missing_runtime.example.json": ("prefix_prepare", "ds4_runtime_prefix_prepare"),
			"prefix_pin_blocked_missing_runtime.example.json": ("prefix_pin", "ds4_runtime_prefix_pin"),
			"prefix_fork_blocked_missing_runtime.example.json": ("prefix_fork", "ds4_runtime_prefix_fork"),
			"session_append_blocked_missing_runtime.example.json": ("session_append", "ds4_runtime_session_append"),
			"session_decode_blocked_missing_runtime.example.json": ("session_decode", "ds4_runtime_session_decode"),
			"session_release_blocked_missing_runtime.example.json": ("session_release", "ds4_runtime_session_release"),
			"prefix_release_blocked_missing_runtime.example.json": ("prefix_release", "ds4_runtime_prefix_release"),
		}
		for fixture, (operation, hook) in cases.items():
			with self.subTest(fixture=fixture):
				obj = prefix_kv.load_json(FIX / fixture)
				self.assertEqual(obj["operation"], operation)
				self.assertEqual(obj["runtime_hook"], hook)


if __name__ == "__main__":
	unittest.main()
