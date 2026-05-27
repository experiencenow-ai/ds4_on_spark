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
VLLM_COMMIT = "d523ead071132cd291e66e3dfd68f55446c27357"


class _Done:
    returncode = 0
    stderr = ""

    def __init__(self, payload: dict) -> None:
        self.stdout = json.dumps(payload)


class SparkControlTests(unittest.TestCase):
    def test_registry_has_one_qwen27_profile(self) -> None:
        registry = ProfileRegistry.load(PROFILES)
        profiles = [profile for profile in registry.all_profiles() if profile.model_id == "Qwen/Qwen3.6-27B-FP8"]
        self.assertEqual([profile.profile_id for profile in profiles], ["qwen3_6_27b_fp8_efficient_v1"])

    def test_qwen27_contract_caps_max_num_seqs_at_12(self) -> None:
        contract = json.loads((CONTRACTS / "qwen27_vllm_trim_v1.json").read_text(encoding="utf-8"))
        args = contract["launch"]["args"]
        self.assertEqual(contract["vllm"]["required_source_commit"], VLLM_COMMIT)
        self.assertEqual(contract["optional_kv_cache"]["connector"], "LMCacheMPConnector")
        self.assertEqual(args[args.index("--max-num-seqs") + 1], "12")
        self.assertEqual(args[args.index("--gpu-memory-utilization") + 1], "0.50")

    def test_qwen_trim_plan_uses_runtime_contract_endpoint(self) -> None:
        plan = trim_spark_memory(node_id="spark0", topology_path=TOPOLOGY, profiles_dir=PROFILES, contracts_dir=CONTRACTS)
        self.assertFalse(plan["execute"])
        self.assertEqual(plan["profile_id"], "qwen3_6_27b_fp8_efficient_v1")
        self.assertEqual(plan["runtime_contract_id"], "qwen27_vllm_trim_v1")
        self.assertEqual(plan["ingress_node_id"], "spark0")
        self.assertEqual(plan["endpoint"]["base_url"], "http://127.0.0.1:18100")
        self.assertEqual(plan["endpoint"]["path"], "/v1/trim_memory")
        self.assertIn("release_offload_memory=true", plan["endpoint"]["query"])

    def test_grouped_dsv4_trim_plan_uses_group_ingress(self) -> None:
        plan = trim_spark_memory(node_id="spark5", topology_path=TOPOLOGY, profiles_dir=PROFILES, contracts_dir=CONTRACTS)
        self.assertEqual(plan["profile_id"], "dsv4_vllm_mtp_smartest_v1")
        self.assertEqual(plan["runtime_contract_id"], "dsv4_spark45_vllm_mtp_v1")
        self.assertEqual(plan["ingress_node_id"], "spark4")
        self.assertEqual(plan["endpoint"]["base_url"], "http://127.0.0.1:8000")

    def test_experimental_spark_can_be_trimmed_with_profile_or_base_url(self) -> None:
        plan = trim_spark_memory(node_id="spark7", profile_id="qwen3_6_27b_fp8_efficient_v1", topology_path=TOPOLOGY, profiles_dir=PROFILES, contracts_dir=CONTRACTS)
        self.assertEqual(plan["ingress_node_id"], "spark7")
        self.assertEqual(plan["endpoint"]["base_url"], "http://127.0.0.1:18110")
        self.assertIn("mode=abort", plan["endpoint"]["query"])
        graceful = trim_spark_memory(node_id="spark7", profile_id="qwen3_6_27b_fp8_efficient_v1", topology_path=TOPOLOGY, profiles_dir=PROFILES, contracts_dir=CONTRACTS, mode="wait")
        self.assertIn("mode=wait", graceful["endpoint"]["query"])
        custom = trim_spark_memory(node_id="spark7", base_url="http://127.0.0.1:19999", topology_path=TOPOLOGY, profiles_dir=PROFILES, contracts_dir=CONTRACTS)
        self.assertIsNone(custom["profile_id"])
        self.assertEqual(custom["endpoint"]["base_url"], "http://127.0.0.1:19999")

    def test_experimental_spark_requires_profile_or_base_url(self) -> None:
        with self.assertRaisesRegex(ValueError, "spark7 has no resident profile"):
            trim_spark_memory(node_id="spark7", topology_path=TOPOLOGY, profiles_dir=PROFILES, contracts_dir=CONTRACTS)

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
        self.assertEqual(result["result"]["endpoint"]["base_url"], "http://127.0.0.1:18100")

    def test_cli_uses_same_trim_contract(self) -> None:
        stdout = StringIO()
        with redirect_stdout(stdout):
            rc = infer_cli_main(
                [
                    "trim-spark-memory",
                    "--node-id",
                    "spark5",
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
        self.assertEqual(payload["ingress_node_id"], "spark4")


if __name__ == "__main__":
    unittest.main()
