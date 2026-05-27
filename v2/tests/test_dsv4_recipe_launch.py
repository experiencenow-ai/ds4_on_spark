import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


class Dsv4RecipeLaunchTests(unittest.TestCase):
    def test_docker_recipe_preserves_known_good_hma_shape(self) -> None:
        recipe = (ROOT / "recipes" / "deepseek-v4-flash-spark45.yaml").read_text()
        self.assertIn("d240cdbcf3de175be57c108fd9cbfce04009ec29", recipe)
        self.assertIn("dda4668b59567416f86956cfe7bbc1eab371a61e", recipe)
        self.assertIn("max_model_len: 262144", recipe)
        self.assertIn("max_num_batched_tokens: 8192", recipe)
        self.assertIn("max_num_seqs: 2", recipe)
        self.assertIn("gpu_memory_utilization: 0.8", recipe)
        self.assertIn("kv_offloading_size: 8", recipe)
        self.assertIn("--block-size {block_size}", recipe)
        self.assertIn("--kv-cache-dtype fp8", recipe)
        self.assertIn("--enable-prefix-caching", recipe)
        self.assertIn("--no-disable-hybrid-kv-cache-manager", recipe)
        self.assertIn("--kv-offloading-size {kv_offloading_size}", recipe)
        self.assertIn("--kv-offloading-backend native", recipe)
        self.assertIn("--kv-cache-metrics", recipe)
        self.assertIn("--enable-logging-iteration-details", recipe)
        self.assertIn("--enforce-eager", recipe)
        self.assertIn("--speculative-config", recipe)
        self.assertIn("deepseek_mtp", recipe)
        self.assertIn("--distributed-executor-backend mp", recipe)
        self.assertIn("NCCL_IB_DISABLE", recipe)
        self.assertNotIn("--kv-transfer-config", recipe)
        self.assertNotIn("LMCacheConnectorV1Dynamic", recipe)
        self.assertNotIn("LMCACHE_USE_EXPERIMENTAL", recipe)

    def test_docker_systemd_unit_launches_recipe_wrapper(self) -> None:
        service = (ROOT / "deploy" / "systemd-user" / "ds4-dsv4-docker-legacy.service").read_text()
        self.assertIn("Docker-lineage recipe service", service)
        self.assertIn("ds4_dsv4_recipe_spark45.sh start", service)
        self.assertIn("Conflicts=ds4-dsv4-local-head.service", service)

    def test_local_launcher_matches_256k_docker_lineage_shape(self) -> None:
        script = (ROOT / "scripts" / "ds4_dsv4_spark45_local_vllm.sh").read_text()
        head = (ROOT / "deploy" / "systemd-user" / "ds4-dsv4-local-head.service").read_text()
        worker = (ROOT / "deploy" / "systemd-user" / "ds4-dsv4-local-worker.service").read_text()
        self.assertIn('local_ip="${DS4_DSV4_LOCAL_IP:-${DS4_DSV4_HEAD_IP:-10.20.0.14}}"', script)
        self.assertIn('local_ip="${DS4_DSV4_LOCAL_IP:-${DS4_DSV4_WORKER_IP:-10.20.0.15}}"', script)
        self.assertIn('model_path="${DS4_DSV4_MODEL_PATH:-$HOME/.cache/huggingface/hub/models--deepseek-ai--DeepSeek-V4-Flash/snapshots/6976c7ff1b30a1b2cb7805021b8ba4684041f136}"', script)
        self.assertIn('max_model_len="${DS4_DSV4_MAX_MODEL_LEN:-262144}"', script)
        self.assertIn('kv_offload_size="${DS4_DSV4_KV_OFFLOAD_SIZE:-8}"', script)
        self.assertIn('gpu_memory_utilization="${DS4_DSV4_GPU_MEMORY_UTILIZATION:-0.8}"', script)
        self.assertIn('max_num_batched_tokens="${DS4_DSV4_MAX_NUM_BATCHED_TOKENS:-8192}"', script)
        self.assertIn('max_num_seqs="${DS4_DSV4_MAX_NUM_SEQS:-2}"', script)
        self.assertIn("--kv-cache-metrics", script)
        self.assertIn("--enable-logging-iteration-details", script)
        self.assertIn("--distributed-executor-backend mp", script)
        self.assertIn("deepseek_mtp", script)
        self.assertIn("ds4-dsv4-docker-legacy.service", head)
        self.assertIn("ds4_dsv4_spark45_local_vllm.sh worker", worker)

    def test_service_wrapper_uses_pinned_recipe_runner(self) -> None:
        script = (ROOT / "scripts" / "ds4_dsv4_recipe_spark45.sh").read_text()
        self.assertIn("Docker-lineage DSV4 recipe path", script)
        self.assertIn("refs/remotes/origin/pr/219", script)
        self.assertIn("+refs/pull/219/head:refs/remotes/origin/pr/219", script)
        self.assertIn("vllm-node-dsv4-lmcache-rankfix", script)
        self.assertIn("CONTAINER_NCCL_IB_DISABLE=1", script)
        self.assertIn("CONTAINER_PYTHONHASHSEED", script)
        self.assertIn("ds4_spark_launch_ed25519", script)
        self.assertIn("DS4_DSV4_WORKER_IDENTITY_FILE", script)
        self.assertIn("DS4_DSV4_FORCE_BUILD", script)
        self.assertIn("--force-build", script)
        self.assertIn("--no-ray --no-cache-dirs -d", script)
        self.assertIn("DS4_DSV4_PERSIST_STORE", script)
        self.assertIn("VLLM_SIMPLE_KV_OFFLOAD_PERSIST_ROOT", script)
        self.assertIn("persistent_mod_name=\"ds4-dsv4-persistent-simple-offload\"", script)
        self.assertIn("DS4_DSV4_ENABLE_PERSISTENT_RUNTIME_MOD", script)
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

    def test_topology_doc_records_256k_feature_complete_target(self) -> None:
        doc = (ROOT / "docs" / "static-spark-topology.md").read_text()
        self.assertIn("experiencenow-ai/vllm", doc)
        self.assertIn("d240cdbcf3de175be57c108fd9cbfce04009ec29", doc)
        self.assertIn("dda4668b59567416f86956cfe7bbc1eab371a61e", doc)
        self.assertIn("SimpleCPUOffloadConnector", doc)
        self.assertIn("LMCacheConnectorV1Dynamic", doc)
        self.assertIn("turns off vLLM's hybrid KV cache manager", doc)
        self.assertIn("Do not replace this with a Ray vLLM service", doc)
        self.assertIn("max_model_len=262144", doc)
        self.assertIn("MTP speculative decoding enabled", doc)
        self.assertIn("KV cache metrics and iteration details enabled", doc)


if __name__ == "__main__":
    unittest.main()
