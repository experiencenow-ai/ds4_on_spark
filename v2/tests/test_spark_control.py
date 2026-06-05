from __future__ import annotations

from contextlib import redirect_stdout
from io import StringIO
import json
from pathlib import Path
import unittest

from ds4_infer.cli import main as infer_cli_main
from ds4_infer.control import trim_spark_memory
from ds4_infer.profiles import ProfileRegistry
from ds4_tools.registry import ToolRegistry

ROOT = Path(__file__).resolve().parents[1]
PROFILES = ROOT / "profiles" / "models"
TOPOLOGY = ROOT / "profiles" / "topology" / "static_sparks.json"
CONTRACTS = ROOT / "profiles" / "runtime_contracts"
TOOLS = ROOT / "tools" / "registry.jsonl"
VLLM_COMMIT = "c6e55a80d213ba2652ab9a7d5d0aacf01cbccd34"
QWEN_PP = "qwen3_6_27b_bf16_pp8_efficient_v1"
DSV4_PP = "dsv4_vllm_mtp_pp8_smartest_v1"
GEMMA31_PP = "gemma4_31b_it_pp8_peer_v1"


class _Done:
    returncode = 0
    stderr = ""

    def __init__(self, payload: dict) -> None:
        self.stdout = json.dumps(payload)


class SparkControlTests(unittest.TestCase):
    def test_registry_keeps_legacy_qwen27_but_defaults_to_bf16_pipeline(self) -> None:
        registry = ProfileRegistry.load(PROFILES)
        qwen_profiles = {profile.profile_id: profile for profile in registry.all_profiles() if profile.model_id.startswith("Qwen/Qwen3.6-27B")}
        self.assertIn("qwen3_6_27b_fp8_efficient_v1", qwen_profiles)
        self.assertIn(QWEN_PP, qwen_profiles)
        self.assertEqual(registry.resolve(capability="efficient", chat=False, job_class="atom_edit").profile_id, QWEN_PP)

    def test_qwen27_bf16_pipeline_contract_uses_spark0_entry_and_pp8(self) -> None:
        contract = json.loads((CONTRACTS / "qwen27_bf16_pp8_v1.json").read_text(encoding="utf-8"))
        args = contract["launch"]["args"]
        self.assertEqual(contract["vllm"]["required_source_commit"], VLLM_COMMIT)
        self.assertEqual(contract["launch"]["api_base_url"], "http://127.0.0.1:8101")
        self.assertEqual(contract["pipeline"]["total_layers"], 64)
        self.assertEqual(contract["pipeline"]["layer_partition"], [9, 9, 9, 8, 8, 8, 8, 5])
        self.assertEqual(args[args.index("--pipeline-parallel-size") + 1], "8")
        self.assertEqual(args[args.index("--dtype") + 1], "bfloat16")
        self.assertIn("--language-model-only", args)

    def test_qwen_trim_plan_uses_pipeline_entry_endpoint(self) -> None:
        plan = trim_spark_memory(node_id="spark0", topology_path=TOPOLOGY, profiles_dir=PROFILES, contracts_dir=CONTRACTS)
        self.assertFalse(plan["execute"])
        self.assertEqual(plan["profile_id"], QWEN_PP)
        self.assertEqual(plan["runtime_contract_id"], "qwen27_bf16_pp8_v1")
        self.assertEqual(plan["ingress_node_id"], "spark0")
        self.assertEqual(plan["endpoint"]["base_url"], "http://127.0.0.1:8101")
        self.assertEqual(plan["endpoint"]["path"], "/v1/trim_memory")
        self.assertIn("release_offload_memory=true", plan["endpoint"]["query"])

    def test_dsv4_trim_plan_requires_profile_and_uses_pipeline_entry(self) -> None:
        default = trim_spark_memory(node_id="spark5", topology_path=TOPOLOGY, profiles_dir=PROFILES, contracts_dir=CONTRACTS)
        self.assertEqual(default["profile_id"], QWEN_PP)
        self.assertEqual(default["ingress_node_id"], "spark0")
        explicit = trim_spark_memory(node_id="spark5", profile_id=DSV4_PP, topology_path=TOPOLOGY, profiles_dir=PROFILES, contracts_dir=CONTRACTS)
        self.assertEqual(explicit["profile_id"], DSV4_PP)
        self.assertEqual(explicit["runtime_contract_id"], "dsv4_flash_pp8_mtp_v1")
        self.assertEqual(explicit["ingress_node_id"], "spark0")
        self.assertEqual(explicit["endpoint"]["base_url"], "http://127.0.0.1:8102")

    def test_gemma_trim_plan_uses_profile_pinned_pipeline_entry(self) -> None:
        explicit = trim_spark_memory(node_id="spark7", profile_id=GEMMA31_PP, topology_path=TOPOLOGY, profiles_dir=PROFILES, contracts_dir=CONTRACTS)
        self.assertEqual(explicit["profile_id"], GEMMA31_PP)
        self.assertEqual(explicit["runtime_contract_id"], "gemma4_31b_it_pp8_v1")
        self.assertEqual(explicit["ingress_node_id"], "spark0")
        self.assertEqual(explicit["endpoint"]["base_url"], "http://127.0.0.1:8120")

    def test_every_spark_trims_through_single_entry_with_override_preserved(self) -> None:
        plan = trim_spark_memory(node_id="spark7", topology_path=TOPOLOGY, profiles_dir=PROFILES, contracts_dir=CONTRACTS)
        self.assertEqual(plan["profile_id"], QWEN_PP)
        self.assertEqual(plan["ingress_node_id"], "spark0")
        self.assertEqual(plan["endpoint"]["base_url"], "http://127.0.0.1:8101")
        self.assertIn("mode=abort", plan["endpoint"]["query"])
        graceful = trim_spark_memory(node_id="spark7", topology_path=TOPOLOGY, profiles_dir=PROFILES, contracts_dir=CONTRACTS, mode="wait")
        self.assertIn("mode=wait", graceful["endpoint"]["query"])
        custom = trim_spark_memory(node_id="spark7", base_url="http://127.0.0.1:19999", topology_path=TOPOLOGY, profiles_dir=PROFILES, contracts_dir=CONTRACTS)
        self.assertEqual(custom["profile_id"], QWEN_PP)
        self.assertEqual(custom["endpoint"]["base_url"], "http://127.0.0.1:19999")

    def test_profile_without_runtime_contract_fails_before_transport(self) -> None:
        with self.assertRaisesRegex(ValueError, "has no runtime_contract_id"):
            trim_spark_memory(node_id="spark0", profile_id="qwen3_6_35b_a3b_fp8_fastest_v1", topology_path=TOPOLOGY, profiles_dir=PROFILES, contracts_dir=CONTRACTS)

    def test_execute_wraps_remote_trim_response(self) -> None:
        calls = []

        def runner(command, **kwargs):
            calls.append((command, kwargs))
            return _Done({"ok": True, "status": 200, "json": {"status": "ok", "result": {"worker_results": [{"connector": {"released_cpu_bytes": 4096}}]}}})

        result = trim_spark_memory(node_id="spark0", topology_path=TOPOLOGY, profiles_dir=PROFILES, contracts_dir=CONTRACTS, execute=True, command_runner=runner)
        self.assertTrue(result["ok"])
        self.assertTrue(result["execute"])
        self.assertEqual(result["response"]["json"]["result"]["worker_results"][0]["connector"]["released_cpu_bytes"], 4096)
        self.assertEqual(calls[0][0][5], "spark0")

    def test_tool_lattice_exposes_same_high_level_api(self) -> None:
        result = ToolRegistry.load(TOOLS).invoke("tool:spark.trim_memory", {"node": "spark0"})
        self.assertTrue(result["ok"], result)
        self.assertEqual(result["result"]["format"], "ds4-spark-trim-memory-plan-v1")
        self.assertEqual(result["result"]["endpoint"]["base_url"], "http://127.0.0.1:8101")

    def test_cli_uses_same_trim_contract(self) -> None:
        stdout = StringIO()
        with redirect_stdout(stdout):
            rc = infer_cli_main(
                [
                    "trim-spark-memory",
                    "--node-id",
                    "spark5",
                    "--profile-id",
                    DSV4_PP,
                    "--topology",
                    str(TOPOLOGY),
                    "--profiles-dir",
                    str(PROFILES),
                    "--contracts-dir",
                    str(CONTRACTS),
                ]
            )
        payload = json.loads(stdout.getvalue())
        self.assertEqual(rc, 0)
        self.assertEqual(payload["format"], "ds4-spark-trim-memory-plan-v1")
        self.assertEqual(payload["profile_id"], DSV4_PP)
        self.assertEqual(payload["ingress_node_id"], "spark0")
        self.assertEqual(payload["endpoint"]["base_url"], "http://127.0.0.1:8102")


if __name__ == "__main__":
    unittest.main()
