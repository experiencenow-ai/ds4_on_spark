import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


class Dsv4RecipeLaunchTests(unittest.TestCase):
    def test_dsv4_recipe_preserves_known_good_no_ray_mtp_shape(self) -> None:
        recipe = (ROOT / "recipes" / "deepseek-v4-flash-spark45.yaml").read_text()
        self.assertIn("--distributed-executor-backend mp", recipe)
        self.assertIn("deepseek_mtp", recipe)
        self.assertIn("num_speculative_tokens", recipe)
        self.assertIn("max_model_len: 45056", recipe)
        self.assertIn("max_num_seqs: 2", recipe)
        self.assertIn("dda4668b59567416f86956cfe7bbc1eab371a61e", recipe)
        self.assertIn("vllm-node-dsv4-lmcache-rankfix", recipe)
        self.assertIn("LMCACHE_USE_EXPERIMENTAL", recipe)
        self.assertIn("LMCacheConnectorV1Dynamic", recipe)
        self.assertIn('NCCL_IB_DISABLE: "1"', recipe)

    def test_service_wrapper_uses_pinned_recipe_runner(self) -> None:
        script = (ROOT / "scripts" / "ds4_dsv4_recipe_spark45.sh").read_text()
        self.assertIn("refs/remotes/origin/pr/219", script)
        self.assertIn("+refs/pull/219/head:refs/remotes/origin/pr/219", script)
        self.assertIn("vllm-node-dsv4-lmcache-rankfix", script)
        self.assertIn("CONTAINER_LMCACHE_CONFIG_FILE", script)
        self.assertIn("CONTAINER_NCCL_IB_DISABLE=1", script)
        self.assertIn("ds4_spark_launch_ed25519", script)
        self.assertIn("--no-ray --no-cache-dirs -d", script)

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
        self.assertIn("Do not replace this with a Ray vLLM service", doc)
        self.assertIn('Do not "simplify" the DSV4 lane by disabling MTP', doc)


if __name__ == "__main__":
    unittest.main()
