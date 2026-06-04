from __future__ import annotations

import json
from pathlib import Path
import tempfile
import unittest

from ds4_infer.baked_profiles import create_engine_lock, lock_sha256, validate_lock, write_rank_files


class BakedVllmProfileTests(unittest.TestCase):
    def test_create_lock_resolves_pp7_cache_root_and_semantic_gates(self) -> None:
        with tempfile.TemporaryDirectory() as raw_tmp:
            tmp = Path(raw_tmp)
            contract, topology = _write_profile_inputs(tmp)
            lock = create_engine_lock(
                profile_name="dsv4_flash_pp7_semantic_cpu_staged",
                runtime_contract_path=contract,
                topology_path=topology,
                service_id="dsv4_flash_pp8",
                ds4_repo=tmp,
                vllm_repo=None,
                node_ids=["spark0", "spark1", "spark2", "spark3", "spark4", "spark5", "spark6"],
                layer_partition=[7, 6, 6, 6, 6, 6, 6],
                pipeline_parallel_size=7,
                arg_sets={"--max-num-seqs": "1", "--max-num-batched-tokens": "8192"},
                arg_drops=["--speculative-config"],
                env_sets={"DS4_PP_TRANSPORT": "tcp-staged"},
                expected_banner={"moe_backend": "FLASHINFER_CUTLASS_MXFP4_MXFP8"},
                semantic_preset="dsv4-basic",
                allow_dirty=True,
                ds4_commit="ds4-test",
                vllm_commit="vllm-test",
            )
        self.assertEqual(validate_lock(lock), [])
        self.assertEqual(lock["parallelism"]["pipeline_parallel_size"], 7)
        self.assertEqual(lock["parallelism"]["stage_start_layers"], [0, 7, 13, 19, 25, 31, 37])
        self.assertIn("--max-num-seqs", lock["vllm_args"])
        self.assertNotIn("--speculative-config", lock["vllm_args"])
        self.assertEqual(lock["env"]["DS4_PP_TRANSPORT"], "tcp-staged")
        self.assertIn(lock["profile_hash"][:12], lock["env"]["VLLM_CACHE_ROOT"])
        self.assertEqual(len(lock["semantic_gates"]), 2)

    def test_validate_lock_rejects_tamper_and_env_drift(self) -> None:
        lock = _minimal_lock()
        self.assertEqual(validate_lock(lock), [])
        tampered = json.loads(json.dumps(lock))
        tampered["vllm_args"].append("--unexpected")
        self.assertIn("lock_sha256 does not match lock contents", validate_lock(tampered))
        errors = validate_lock(lock, current_env={"VLLM_CACHE_ROOT": "/wrong"})
        self.assertEqual(errors, ["current env VLLM_CACHE_ROOT='/wrong' differs from lock value '/cache/root'"])

    def test_write_rank_files_exports_exact_env_and_commands(self) -> None:
        lock = _minimal_lock()
        with tempfile.TemporaryDirectory() as raw_tmp:
            out = Path(raw_tmp)
            write_rank_files(lock, out)
            self.assertIn("VLLM_CACHE_ROOT=/cache/root", (out / "rank_0.env").read_text(encoding="utf-8"))
            self.assertIn("NODE_RANK=1", (out / "rank_1.sh").read_text(encoding="utf-8"))


def _write_profile_inputs(tmp: Path) -> tuple[Path, Path]:
    contract = {
        "launch": {
            "args": [
                "--pipeline-parallel-size",
                "8",
                "--tensor-parallel-size",
                "1",
                "--max-model-len",
                "262144",
                "--max-num-seqs",
                "64",
                "--max-num-batched-tokens",
                "32768",
                "--speculative-config",
                "{\"method\":\"deepseek_mtp\"}",
            ],
            "port": 8102,
        },
        "model": {"model_id": "deepseek-ai/DeepSeek-V4-Flash", "served_model_name": "deepseek-v4-flash"},
        "pipeline": {"layer_partition": [5, 6, 6, 6, 6, 5, 5, 4]},
        "required_nodes": ["spark0", "spark1", "spark2", "spark3", "spark4", "spark5", "spark6", "spark7"],
    }
    topology = {
        "routing_policy": {
            "pipeline_services": {
                "dsv4_flash_pp8": {
                    "model_id": "deepseek-ai/DeepSeek-V4-Flash",
                    "pipeline_parallel_size": 8,
                    "tensor_parallel_size": 1,
                    "layer_partition": [5, 6, 6, 6, 6, 5, 5, 4],
                    "node_ids": ["spark0", "spark1", "spark2", "spark3", "spark4", "spark5", "spark6", "spark7"],
                }
            }
        }
    }
    contract_path = tmp / "contract.json"
    topology_path = tmp / "topology.json"
    contract_path.write_text(json.dumps(contract), encoding="utf-8")
    topology_path.write_text(json.dumps(topology), encoding="utf-8")
    return contract_path, topology_path


def _minimal_lock() -> dict[str, object]:
    lock = {
        "format": "ds4-vllm-engine-lock-v1",
        "profile_name": "test",
        "profile_hash": "abc",
        "repos": {"ds4_commit": "ds4", "vllm_commit": "vllm"},
        "model": {"model_path": "m", "served_model_name": "m"},
        "parallelism": {
            "pipeline_parallel_size": 2,
            "tensor_parallel_size": 1,
            "layer_partition": [1, 1],
            "node_ids": ["spark0", "spark1"],
        },
        "vllm_args": ["--pipeline-parallel-size", "2", "--tensor-parallel-size", "1", "--max-model-len", "128"],
        "env": {"VLLM_CACHE_ROOT": "/cache/root"},
        "launch": {"rank_commands": ["NODE_RANK=0 vllm serve m", "NODE_RANK=1 vllm serve m"]},
    }
    lock["lock_sha256"] = lock_sha256(lock)
    return lock


if __name__ == "__main__":
    unittest.main()
