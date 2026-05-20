import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

from scripts import pipeline_kv_cache as kv


PATCH = Path("docs/antirez-patches/ds4-3630e64-cuda-stage-kv-checkpoint.patch")


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
			"DS4_STAGE_KV_SHARD_MAGIC",
			"DS4_STAGE_KV_SHARD_VERSION",
			"DS4_STAGE_KV_IO_CHUNK",
			"stage_kv_payload_live_tensor_bytes",
			"stage_kv_save_graph",
			"stage_kv_restore_graph",
			"stage_save_kv",
			"stage_restore_kv",
			"save_kv",
			"restore_kv",
			"layer_raw_cache",
			"layer_attn_comp_cache",
			"layer_attn_state_kv",
			"layer_attn_state_score",
			"layer_index_comp_cache",
			"layer_index_state_kv",
			"layer_index_state_score",
			"layer_n_comp",
			"layer_n_index_comp",
			"ds4_gpu_tensor_read",
			"ds4_gpu_tensor_write",
			"kv_cache_hit",
		]
		for needle in required:
			with self.subTest(needle=needle):
				self.assertIn(needle, text)
		self.assertNotIn("placeholder", text.lower())
		self.assertNotIn("memset(buf, 0", text)


if __name__ == "__main__":
	unittest.main()
