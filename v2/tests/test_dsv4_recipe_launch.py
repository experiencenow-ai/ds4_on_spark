import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


class Dsv4RecipeLaunchTests(unittest.TestCase):
    def test_dsv4_recipe_preserves_known_good_no_ray_mtp_shape(self) -> None:
        recipe = (ROOT / "recipes" / "deepseek-v4-flash-spark45.yaml").read_text()
        self.assertIn("--distributed-executor-backend mp", recipe)
        self.assertIn("deepseek_mtp", recipe)
        self.assertIn("num_speculative_tokens", recipe)
        self.assertIn("max_model_len: 1048576", recipe)
        self.assertIn("max_num_seqs: 2", recipe)
        self.assertIn("dda4668b59567416f86956cfe7bbc1eab371a61e", recipe)
        self.assertIn("vllm-node-dsv4-lmcache-rankfix", recipe)
        self.assertIn("VLLM_USE_SIMPLE_KV_OFFLOAD", recipe)
        self.assertIn("--no-disable-hybrid-kv-cache-manager", recipe)
        self.assertIn("--kv-offloading-size 16", recipe)
        self.assertIn("--kv-offloading-backend native", recipe)
        self.assertIn('NCCL_IB_DISABLE: "1"', recipe)
        self.assertNotIn("--kv-transfer-config", recipe)
        self.assertNotIn("LMCacheConnectorV1Dynamic", recipe)
        self.assertNotIn("LMCACHE_USE_EXPERIMENTAL", recipe)

    def test_service_wrapper_uses_pinned_recipe_runner(self) -> None:
        script = (ROOT / "scripts" / "ds4_dsv4_recipe_spark45.sh").read_text()
        self.assertIn("refs/remotes/origin/pr/219", script)
        self.assertIn("+refs/pull/219/head:refs/remotes/origin/pr/219", script)
        self.assertIn("vllm-node-dsv4-lmcache-rankfix", script)
        self.assertIn("CONTAINER_NCCL_IB_DISABLE=1", script)
        self.assertIn("CONTAINER_PYTHONHASHSEED", script)
        self.assertIn("ds4_spark_launch_ed25519", script)
        self.assertIn("--no-ray --no-cache-dirs -d", script)
        self.assertIn("DS4_DSV4_PERSIST_STORE", script)
        self.assertIn("VLLM_SIMPLE_KV_OFFLOAD_PERSIST_ROOT", script)
        self.assertIn("persistent_mod_name=\"ds4-dsv4-persistent-simple-offload\"", script)
        self.assertIn("mods/$persistent_mod_name", script)
        self.assertIn("VLLM_SPARK_EXTRA_DOCKER_ARGS", script)
        self.assertNotIn("CONTAINER_LMCACHE_CONFIG_FILE", script)
        self.assertNotIn("write_lmcache_config", script)
        self.assertNotIn("export_lmcache_mounts", script)

    def test_persistent_simple_offload_runtime_mod_patches_native_hma_offload(self) -> None:
        mod = ROOT / "runtime_mods" / "dsv4_persistent_simple_offload"
        patcher = (mod / "patch_vllm.py").read_text()
        store = (mod / "persistent_disk.py").read_text()
        run = (mod / "run.sh").read_text()
        self.assertIn("SimpleCPUOffloadScheduler", patcher)
        self.assertIn("SimpleCPUOffloadWorker", patcher)
        self.assertIn("load_block_hashes", patcher)
        self.assertIn("store_block_hashes", patcher)
        self.assertIn("PersistentSimpleOffloadStore", patcher)
        self.assertIn("lookup_hashes_to_load", patcher)
        self.assertIn("guard_tokens", patcher)
        self.assertIn("raw_tokens", patcher)
        self.assertIn("restore_worker_blocks", store)
        self.assertIn("persist_worker_blocks", store)
        self.assertIn("validate_loaded_blocks", store)
        self.assertIn("VLLM_SIMPLE_KV_OFFLOAD_PERSIST_ROOT", store)
        self.assertIn("hashlib.sha256", store)
        self.assertIn("python3 patch_vllm.py", run)

    def test_lmcache_image_extensions_are_documented(self) -> None:
        base = (ROOT / "docker" / "dsv4-lmcache.Dockerfile").read_text()
        rankfix = (ROOT / "docker" / "dsv4-lmcache-rankfix.Dockerfile").read_text()
        self.assertIn("FROM vllm-node-dsv4:latest", base)
        self.assertIn("LMCache.git", base)
        self.assertIn("v0.4.5", base)
        self.assertIn("FROM vllm-node-dsv4-lmcache:latest", rankfix)
        self.assertIn("tp_size > num_gpus", rankfix)
        self.assertIn("local_worker_id = global_rank % num_gpus", rankfix)

    def test_topology_doc_warns_against_ray_and_no_mtp_regressions(self) -> None:
        doc = (ROOT / "docs" / "static-spark-topology.md").read_text()
        self.assertIn("distributed_executor_backend=mp", doc)
        self.assertIn("SimpleCPUOffloadConnector", doc)
        self.assertIn("LMCacheConnectorV1Dynamic", doc)
        self.assertIn("turns off vLLM's hybrid KV cache manager", doc)
        self.assertIn("Do not replace this with a Ray vLLM service", doc)
        self.assertIn('Do not "simplify" the DSV4 lane by disabling MTP', doc)


if __name__ == "__main__":
    unittest.main()
