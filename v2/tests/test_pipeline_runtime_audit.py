from __future__ import annotations

import importlib.util
import json
from pathlib import Path
import sys
import unittest


ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "scripts" / "ds4_pipeline_runtime_audit.py"
DSV4_PRODUCTION_PROFILE = ROOT / "profiles" / "production" / "dsv4_flash_pp8_resident128.json"
FIRST3_MEMORY_BUDGET = ROOT / "profiles" / "production" / "first3_resident_memory_budget.json"


def load_script_module(name: str, path: Path):
    spec = importlib.util.spec_from_file_location(name, path)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"cannot load {path.name}")
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


audit = load_script_module("ds4_pipeline_runtime_audit", SCRIPT)


class PipelineRuntimeAuditTests(unittest.TestCase):
    def test_dsv4_production_profile_is_source_of_truth(self) -> None:
        profile = json.loads(DSV4_PRODUCTION_PROFILE.read_text(encoding="utf-8"))

        self.assertEqual(profile["format"], "ds4-production-profile-v1")
        self.assertEqual(sum(profile["layer_partition"]), 43)
        self.assertEqual(len(profile["layer_partition"]), profile["pipeline_parallel_size"])
        self.assertLessEqual(profile["layer_partition"][0], max(profile["layer_partition"][1:]))
        self.assertEqual(profile["max_num_seqs"], profile["coordinator"]["dispatch_window"])
        self.assertEqual(profile["max_num_seqs"], profile["coordinator"]["completion_cohort_max"])
        self.assertEqual(profile["kv_cache_memory_bytes"], profile["coordinator"]["dispatch_kv_capacity_bytes"])
        self.assertFalse(profile["speculative_decode"])
        self.assertTrue((ROOT / profile["runtime_contract"]).exists())
        self.assertTrue((ROOT / profile["kv_deployment"]).exists())
        self.assertTrue((ROOT / profile["topology"]).exists())
        self.assertTrue((ROOT / profile["memory_budget"]).exists())
        self.assertTrue(profile["warmup"]["required_before_first3_residency"])
        self.assertEqual(profile["warmup"]["script"], "scripts/ds4_warm_dsv4_flashinfer_cache.py")
        self.assertEqual(
            profile["warmup"]["compile_env"]["VLLM_DS4_DSV4_SPARSE_MLA_PREFILL_BACKEND"],
            "indexed",
        )
        self.assertEqual(profile["warmup"]["compile_env"]["VLLM_DS4_DSV4_PP_FLUSH_HC_BOUNDARY"], "1")
        self.assertEqual(profile["warmup"]["compile_env"]["VLLM_DEEP_GEMM_WARMUP"], "skip")
        self.assertEqual(profile["warmup"]["compile_env"]["NCCL_IB_DISABLE"], "1")
        self.assertEqual(profile["warmup"]["compile_env"]["NCCL_SOCKET_IFNAME"], "ds4ring0")
        self.assertEqual(profile["warmup"]["compile_env"]["NCCL_SOCKET_FAMILY"], "AF_INET")

    def test_first3_memory_budget_tracks_profile_partitions_and_gpu_caps(self) -> None:
        budget = json.loads(FIRST3_MEMORY_BUDGET.read_text(encoding="utf-8"))
        profile = json.loads(DSV4_PRODUCTION_PROFILE.read_text(encoding="utf-8"))

        self.assertEqual(budget["layer_partitions"]["dsv4_flash_pp8"], profile["layer_partition"])
        self.assertEqual(budget["layer_partitions"]["qwen27_bf16_pp8"], [7, 8, 7, 9, 9, 9, 8, 7])
        self.assertEqual(budget["layer_partitions"]["gemma4_26b_a4b_pp8"], [3, 4, 4, 4, 3, 4, 4, 4])
        self.assertEqual(budget["gpu_memory_utilization"]["active_sum"], 0.63)
        self.assertEqual(budget["coordinator"]["dispatch_window"], 128)
        self.assertEqual(budget["coordinator"]["dispatch_refill_batch"], 128)
        self.assertGreaterEqual(budget["projection"]["floor_gib"], budget["target"]["min_available_gib"])

    def test_pipeline_runtime_audit_passes_checked_in_profiles(self) -> None:
        self.assertEqual(audit.main(), 0)


if __name__ == "__main__":
    unittest.main()
