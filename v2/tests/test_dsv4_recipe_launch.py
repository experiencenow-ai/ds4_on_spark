import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


class Dsv4RecipeLaunchTests(unittest.TestCase):
    def test_local_source_launch_preserves_known_good_no_ray_mtp_shape(self) -> None:
        script = (ROOT / "scripts" / "ds4_dsv4_spark45_local_vllm.sh").read_text()
        self.assertIn("d523ead071132cd291e66e3dfd68f55446c27357", script)
        self.assertIn("kv_offload_size=\"${DS4_DSV4_KV_OFFLOAD_SIZE:-8}\"", script)
        self.assertIn("VLLM_USE_SIMPLE_KV_OFFLOAD", script)
        self.assertIn("VLLM_SIMPLE_KV_OFFLOAD_PERSIST_ROOT", script)
        self.assertIn("--max-model-len 1048576", script)
        self.assertIn("--max-num-seqs 2", script)
        self.assertIn("--max-num-batched-tokens 8192", script)
        self.assertIn("--block-size 256", script)
        self.assertIn("--kv-cache-dtype fp8", script)
        self.assertIn("--enable-prefix-caching", script)
        self.assertIn("--no-disable-hybrid-kv-cache-manager", script)
        self.assertIn("--kv-offloading-size \"$kv_offload_size\"", script)
        self.assertIn("--kv-offloading-backend native", script)
        self.assertIn("--enforce-eager", script)
        self.assertIn("--nnodes 2", script)
        self.assertIn("--node-rank \"$node_rank\"", script)
        self.assertIn("--headless", script)
        self.assertIn("deepseek_mtp", script)
        self.assertIn("NCCL_IB_DISABLE=1", script)
        self.assertNotIn("--kv-transfer-config", script)
        self.assertNotIn("LMCacheConnectorV1Dynamic", script)
        self.assertNotIn("LMCACHE_USE_EXPERIMENTAL", script)

    def test_local_systemd_units_launch_source_built_scripts(self) -> None:
        head = (ROOT / "deploy" / "systemd-user" / "ds4-dsv4-local-head.service").read_text()
        worker = (ROOT / "deploy" / "systemd-user" / "ds4-dsv4-local-worker.service").read_text()
        compat = (ROOT / "deploy" / "systemd-user" / "ds4-dsv4-vllm.service").read_text()
        self.assertIn("ds4_dsv4_spark45_local_vllm.sh head", head)
        self.assertIn("ds4_dsv4_spark45_local_vllm.sh worker", worker)
        self.assertIn("ds4_dsv4_spark45_local_vllm.sh head", compat)
        self.assertNotIn("ds4_dsv4_recipe_spark45.sh start", compat)

    def test_legacy_docker_recipe_is_quarantined(self) -> None:
        recipe = (ROOT / "recipes" / "deepseek-v4-flash-spark45.yaml").read_text()
        service = (ROOT / "deploy" / "systemd-user" / "ds4-dsv4-docker-legacy.service").read_text()
        self.assertIn("LEGACY Docker fallback recipe", recipe)
        self.assertIn("vllm-node-dsv4-lmcache-rankfix", recipe)
        self.assertIn("--kv-offloading-size 8", recipe)
        self.assertIn("--enforce-eager", recipe)
        self.assertIn("ds4_dsv4_recipe_spark45.sh start", service)
        self.assertNotIn("--kv-offloading-size 16", recipe)

    def test_service_wrapper_uses_pinned_recipe_runner(self) -> None:
        script = (ROOT / "scripts" / "ds4_dsv4_recipe_spark45.sh").read_text()
        self.assertIn("legacy Docker recipe path", script)
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
        self.assertIn("experiencenow-ai/vllm", doc)
        self.assertIn("d523ead071132cd291e66e3dfd68f55446c27357", doc)
        self.assertIn("SimpleCPUOffloadConnector", doc)
        self.assertIn("LMCacheConnectorV1Dynamic", doc)
        self.assertIn("turns off vLLM's hybrid KV cache manager", doc)
        self.assertIn("Do not replace this with a Ray vLLM service", doc)
        self.assertIn('Do not "simplify" the DSV4 lane by disabling MTP', doc)


if __name__ == "__main__":
    unittest.main()
