import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

from scripts import pipeline_kv_cache as kv


PATCH = Path("docs/antirez-patches/ds4-3630e64-cuda-stage-kv-checkpoint.patch")
LIVE_FIXTURE = Path("fixtures/pipeline_kv_cache/lane_b_spark1_kv_restore_20260520T2148Z")
SPARK2_STAGE_FIXTURE = Path("fixtures/pipeline_kv_cache/lane_b_spark2_stage0_kv_restore_20260520T2220Z")
PP3_RESTORE_FIXTURE = Path("fixtures/pipeline_kv_cache/lane_b_pp3_kv_restore_spark263_20260521T035944Z")


class PipelineKvCacheTest(unittest.TestCase):
	def _write_stage_shards(self, root: Path) -> list[kv.StageShard]:
		shards: list[kv.StageShard] = []
		for idx in range(3):
			path = root / f"stage{idx}.kv"
			path.write_bytes((f"stage-{idx}-real-kv-bytes\n").encode("utf-8") * (idx + 1))
			shards.append(kv.stage_shard_from_file(idx, path))
		return shards

	def test_store_and_exact_lookup_hash_checks_stage_shards(self) -> None:
		with tempfile.TemporaryDirectory() as td:
			root = Path(td)
			cache = kv.PipelineKvCache(root / "cache")
			token_ids = list(range(1000, 1050))
			shards = self._write_stage_shards(root)
			cache.store_entry("prompt text", token_ids, shards, prefill_wall_ms=125.0)
			result = cache.lookup("prompt text", token_ids)
			self.assertTrue(result.kv_cache_hit)
			self.assertEqual(result.hit_token_count, 50)
			self.assertEqual(result.stage_kv_paths, [str(root / "stage0.kv"), str(root / "stage1.kv"), str(root / "stage2.kv")])
			self.assertEqual(result.prefill_wall_ms, 125.0)

	def test_longer_prompt_hits_exact_cached_prefix_length(self) -> None:
		with tempfile.TemporaryDirectory() as td:
			root = Path(td)
			cache = kv.PipelineKvCache(root / "cache")
			cached = list(range(50))
			cache.store_entry("fifty token prompt", cached, self._write_stage_shards(root))
			result = cache.lookup("fifty one token prompt", cached + [9999])
			self.assertTrue(result.kv_cache_hit)
			self.assertEqual(result.hit_token_count, 50)

	def test_token_49_difference_misses(self) -> None:
		with tempfile.TemporaryDirectory() as td:
			root = Path(td)
			cache = kv.PipelineKvCache(root / "cache")
			token_ids = list(range(50))
			cache.store_entry("fifty token prompt", token_ids, self._write_stage_shards(root))
			changed = list(token_ids)
			changed[49] = 123456
			result = cache.lookup("mutated fifty token prompt", changed)
			self.assertFalse(result.kv_cache_hit)
			self.assertEqual(result.hit_token_count, 0)

	def test_stage_shard_tamper_turns_hit_into_miss(self) -> None:
		with tempfile.TemporaryDirectory() as td:
			root = Path(td)
			cache = kv.PipelineKvCache(root / "cache")
			token_ids = list(range(50))
			cache.store_entry("prompt text", token_ids, self._write_stage_shards(root))
			(root / "stage1.kv").write_bytes(b"tampered")
			result = cache.lookup("prompt text", token_ids)
			self.assertFalse(result.kv_cache_hit)
			self.assertIn("hash mismatch", result.reason)

	def test_identity_mismatch_misses(self) -> None:
		with tempfile.TemporaryDirectory() as td:
			root = Path(td)
			cache = kv.PipelineKvCache(root / "cache")
			token_ids = list(range(50))
			cache.store_entry(
				"prompt text",
				token_ids,
				self._write_stage_shards(root),
				identity={"model_id": "ds4", "runtime_id": "cuda-a"},
			)
			result = cache.lookup("prompt text", token_ids, identity={"model_id": "ds4", "runtime_id": "cuda-b"})
			self.assertFalse(result.kv_cache_hit)

	def test_identity_required_when_cache_entry_declares_identity(self) -> None:
		with tempfile.TemporaryDirectory() as td:
			root = Path(td)
			cache = kv.PipelineKvCache(root / "cache")
			token_ids = list(range(50))
			cache.store_entry(
				"prompt text",
				token_ids,
				self._write_stage_shards(root),
				identity={"model_id": "ds4", "runtime_id": "cuda-a"},
			)
			result = cache.lookup("prompt text", token_ids)
			self.assertFalse(result.kv_cache_hit)

	def test_save_restore_round_trip_comparison_is_byte_for_byte_on_token_ids(self) -> None:
		same = kv.compare_token_runs([1, 2, 3, 4, 5], [1, 2, 3, 4, 5])
		diff = kv.compare_token_runs([1, 2, 3, 4, 5], [1, 2, 7, 4, 5])
		self.assertTrue(same["match"])
		self.assertFalse(diff["match"])

	def test_prefill_speedup_requires_measured_five_x(self) -> None:
		self.assertTrue(kv.prefill_speedup_ok(125.0, 25.0))
		self.assertFalse(kv.prefill_speedup_ok(125.0, 26.0))

	def test_callbacks_save_and_restore_stage_paths(self) -> None:
		with tempfile.TemporaryDirectory() as td:
			root = Path(td)
			cache = kv.PipelineKvCache(root / "cache")
			saved: list[tuple[int, Path]] = []
			restored: list[tuple[int, Path]] = []

			def save_stage(stage_index: int, path: Path) -> None:
				saved.append((stage_index, path))
				path.write_bytes(f"stage{stage_index}-payload".encode("utf-8"))

			def restore_stage(stage_index: int, path: Path) -> None:
				restored.append((stage_index, path))
				self.assertTrue(path.exists())

			entry = kv.save_stage_checkpoints(cache, "prompt text", list(range(50)), 3, save_stage)
			result = cache.lookup("prompt text", list(range(50)))
			kv.restore_stage_checkpoints(result, restore_stage)
			self.assertEqual([idx for idx, _ in saved], [0, 1, 2])
			self.assertEqual([idx for idx, _ in restored], [0, 1, 2])
			self.assertEqual(entry["token_count"], 50)

	def test_cli_store_and_lookup(self) -> None:
		with tempfile.TemporaryDirectory() as td:
			root = Path(td)
			shards = self._write_stage_shards(root)
			args = [
				sys.executable,
				"scripts/pipeline_kv_cache.py",
				"store",
				str(root / "cache"),
				"--rendered-prompt",
				"prompt",
				"--token-ids",
				",".join(str(v) for v in range(50)),
			]
			for shard in shards:
				args.extend(["--stage-shard", f"{shard.stage_index}:{shard.path}"])
			subprocess.run(args, check=True, capture_output=True, text=True)
			proc = subprocess.run(
				[
					sys.executable,
					"scripts/pipeline_kv_cache.py",
					"lookup",
					str(root / "cache"),
					"--rendered-prompt",
					"prompt plus suffix",
					"--token-ids",
					",".join(str(v) for v in list(range(50)) + [999]),
				],
				check=True,
				capture_output=True,
				text=True,
			)
			obj = json.loads(proc.stdout)
			self.assertTrue(obj["kv_cache_hit"])
			self.assertEqual(obj["hit_token_count"], 50)

	def test_stage_kv_checkpoint_patch_contract(self) -> None:
		text = PATCH.read_text(encoding="utf-8")
		required = [
			"DS4_PIPELINE_SESSION_SAVE_KV_PATH",
			"DS4_PIPELINE_SESSION_RESTORE_KV_PATH",
			"DS4_PIPELINE_SESSION_WAIT_AFTER_SAVE",
			"DS4_PIPELINE_STAGE_KV_MAGIC",
			"ds4_pipeline_stage_kv_header",
			"pipeline_stage_kv_save",
			"pipeline_stage_kv_restore",
			"raw_live_rows",
			"pipeline_session_step",
			"save_kv_waiting",
		]
		for needle in required:
			with self.subTest(needle=needle):
				self.assertIn(needle, text)
		self.assertNotIn("placeholder", text.lower())
		self.assertNotIn("memset(buf, 0", text)

	def test_live_spark2_stage_restore_fixture_tokens_match(self) -> None:
		live = (SPARK2_STAGE_FIXTURE / "live.log").read_text(encoding="utf-8")
		save = (SPARK2_STAGE_FIXTURE / "save_wait.log").read_text(encoding="utf-8")
		restore = (SPARK2_STAGE_FIXTURE / "restore.log").read_text(encoding="utf-8")
		sha = (SPARK2_STAGE_FIXTURE / "stage0_50tok.kv.sha256").read_text(encoding="utf-8")
		self.assertIn('"event":"prefill_chunk"', live)
		self.assertIn('"logits_fnv64":"8126f4f352ec7b0b"', live)
		self.assertIn('"event":"save_kv"', save)
		self.assertIn('"bytes":17772116', save)
		self.assertIn('"event":"save_kv_waiting"', save)
		self.assertIn('"event":"restore_decode"', restore)
		self.assertIn('"decode_token_ids":[1162,344,260,73615,126664]', live)
		self.assertIn('"decode_token_ids":[1162,344,260,73615,126664]', restore)
		self.assertIn("45acee5378108707dd22810e712c9c658034679f47d91115144bef7e0600ddf0", sha)

	def test_live_pp3_stage_kv_restore_fixture_tokens_match(self) -> None:
		acceptance = json.loads((PP3_RESTORE_FIXTURE / "acceptance.json").read_text(encoding="utf-8"))
		self.assertEqual(acceptance["prompt_token_count"], 50)
		self.assertTrue(acceptance["tokens_match"])
		self.assertEqual(acceptance["live_token_ids"], acceptance["restore_token_ids"])
		self.assertEqual(acceptance["live_token_ids"], [22, 1, 0, 5, 223])
		for stage_id in ("0", "1", "2"):
			self.assertGreater(acceptance["kv_shards"][stage_id]["bytes"], 0)

	def test_live_spark1_kv_restore_fixture_has_cache_hit_after_restart(self) -> None:
		server1 = (LIVE_FIXTURE / "server1.log").read_text(encoding="utf-8")
		server2 = (LIVE_FIXTURE / "server2_after_restart.log").read_text(encoding="utf-8")
		trace2 = (LIVE_FIXTURE / "trace2_after_restart.txt").read_text(encoding="utf-8")
		self.assertIn("kv cache stored tokens=50", server1)
		self.assertIn("kv cache hit text tokens=50", server1)
		self.assertIn("shutdown requested", server1)
		self.assertIn("kv cache hit text tokens=50", server2)
		self.assertIn("completion ctx=50..50:0 prompt done 0.000s", server2)
		self.assertIn("live_tokens_before: 0", trace2)
		self.assertIn("cache_source: disk-text", trace2)
		self.assertIn("disk_cached_tokens: 50", trace2)

	def test_live_spark1_kv_restore_fixture_tokens_match(self) -> None:
		def response_text(path: Path) -> str:
			first = path.read_text(encoding="utf-8").splitlines()[0]
			return json.loads(first)["choices"][0]["text"]

		cold = response_text(LIVE_FIXTURE / "response_rendered50_nothink_1.txt")
		hit = response_text(LIVE_FIXTURE / "response_rendered50_nothink_2_cachehit.txt")
		after_restart = response_text(LIVE_FIXTURE / "response_rendered50_nothink_after_restart.txt")
		self.assertEqual(cold, "I'm here to help")
		self.assertEqual(hit, cold)
		self.assertEqual(after_restart, cold)
		token_dump = (LIVE_FIXTURE / "generated_text_token_ids.txt").read_text(encoding="utf-8")
		self.assertIn("[43, 4571, 2155, 304, 1694]", token_dump)


if __name__ == "__main__":
	unittest.main()
