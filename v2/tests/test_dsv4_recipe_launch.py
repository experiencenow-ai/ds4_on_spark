import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


class Dsv4RecipeLaunchTests(unittest.TestCase):
    def test_deprecated_local_source_launch_is_disabled(self) -> None:
        script = (ROOT / "scripts" / "ds4_dsv4_spark45_local_vllm.sh").read_text()
        self.assertIn("deprecated spark4/spark5 DSV4 launcher is disabled", script)
        self.assertIn("ds4_pipeline_lifecycle.py --service dsv4_flash_pp8 relaunch --execute", script)
        self.assertIn("exit 64", script)

    def test_deprecated_systemd_units_point_at_disabled_launcher(self) -> None:
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

    def test_legacy_docker_recipe_wrapper_is_disabled(self) -> None:
        script = (ROOT / "scripts" / "ds4_dsv4_recipe_spark45.sh").read_text()
        self.assertIn("deprecated spark4/spark5 Docker DSV4 recipe is disabled", script)
        self.assertIn("ds4_pipeline_lifecycle.py --service dsv4_flash_pp8 relaunch --execute", script)
        self.assertIn("exit 64", script)

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
        self.assertIn("c6e55a80d213ba2652ab9a7d5d0aacf01cbccd34", doc)
        self.assertIn("SimpleCPUOffloadConnector", doc)
        self.assertIn("LMCacheConnectorV1Dynamic", doc)
        self.assertIn("turns off vLLM's hybrid KV cache manager", doc)
        self.assertIn("Do not replace this with a Ray vLLM service", doc)
        self.assertIn("max_model_len=262144", doc)
        self.assertIn("MTP speculative decoding enabled", doc)
        self.assertIn("KV cache metrics and iteration details enabled", doc)


if __name__ == "__main__":
    unittest.main()
