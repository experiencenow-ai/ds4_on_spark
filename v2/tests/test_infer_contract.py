from __future__ import annotations

import json
from pathlib import Path
import tempfile
import unittest

from ds4_infer.builders import resolve_model_alias
from ds4_infer.profiles import ProfileRegistry
from ds4_infer.runners import FakeRunner
from ds4_infer.schemas import InferenceRequest
from ds4_infer.service import run_requests

ROOT = Path(__file__).resolve().parents[1]
PROFILES = ROOT / "profiles" / "models"


class InferenceContractTests(unittest.TestCase):
    def test_efficient_routes_to_qwen_27b_bf16_pipeline(self) -> None:
        profile = ProfileRegistry.load(PROFILES).resolve(capability="efficient", chat=False, job_class="atom_edit")
        self.assertEqual(profile.profile_id, "qwen3_6_27b_bf16_pp8_efficient_v1")
        self.assertEqual(profile.model_id, "Qwen/Qwen3.6-27B")
        self.assertEqual(profile.backend, "vllm_pipeline")
        self.assertIn("76/92 ds4_eval", profile.quality["baseline"])
        self.assertIn("3-5B per-stage", profile.performance["target"])

    def test_fastest_routes_to_qwen_a3b_for_triage(self) -> None:
        profile = ProfileRegistry.load(PROFILES).resolve(capability="fastest", chat=False, job_class="triage")
        self.assertEqual(profile.profile_id, "qwen3_6_35b_a3b_fp8_fastest_v1")

    def test_smart_completion_routes_to_gemma26_fast_slot(self) -> None:
        profile = ProfileRegistry.load(PROFILES).resolve(capability="smart", chat=False, job_class="atom_edit")
        self.assertEqual(profile.profile_id, "gemma4_26b_a4b_it_pp8_peer_v1")
        self.assertEqual(profile.model_id, "google/gemma-4-26B-A4B-it")
        self.assertTrue(profile.production_eligible)
        self.assertFalse(profile.routing["requires_profile_pin"])
        self.assertFalse(profile.routing["startup_autoload"])
        self.assertEqual(profile.routing["optional_kv_cache_deployments"], ["profiles/kv_cache/gemma4_26b_a4b_it_pp8_lmcache_hma.json"])

    def test_first3_model_aliases_resolve_to_resident_services(self) -> None:
        self.assertEqual(resolve_model_alias("qwen27"), "qwen3_6_27b_bf16_pp8_efficient_v1")
        self.assertEqual(resolve_model_alias("qwen-bf16"), "qwen3_6_27b_bf16_pp8_efficient_v1")
        self.assertEqual(resolve_model_alias("gemma"), "gemma4_26b_a4b_it_pp8_peer_v1")
        self.assertEqual(resolve_model_alias("gemma4"), "gemma4_26b_a4b_it_pp8_peer_v1")

    def test_smartest_chat_has_no_implicit_dsv4_route_while_unqualified(self) -> None:
        with self.assertRaisesRegex(ValueError, "no production profile"):
            ProfileRegistry.load(PROFILES).resolve(capability="smartest", chat=True, job_class="tool_chat")

    def test_pin_overrides_capability(self) -> None:
        profile = ProfileRegistry.load(PROFILES).resolve(
            capability="efficient",
            chat=True,
            job_class="atom_edit",
            model_pin={"profile_id": "dsv4_vllm_mtp_pp8_smartest_v1"},
        )
        self.assertEqual(profile.profile_id, "dsv4_vllm_mtp_pp8_smartest_v1")

    def test_fake_runner_writes_durable_manifest(self) -> None:
        request = InferenceRequest.from_json(
            {
                "format": "ds4-inference-request-v1",
                "request_id": "r1",
                "capability": "efficient",
                "chat": False,
                "immediate": False,
                "job_class": "atom_edit",
                "max_output_tokens": 128,
                "thinking_budget_tokens": 0,
                "temperature": 0,
                "input": {"target_atom_id": "atom:x", "source_atom_hash": "h"},
                "output_contract": {"format": "centaur-atom-edit-v1", "strict_json": True},
            }
        )
        with tempfile.TemporaryDirectory() as tmp:
            manifest = run_requests(
                requests=[request],
                registry=ProfileRegistry.load(PROFILES),
                runner=FakeRunner(),
                out_dir=tmp,
            )
            self.assertEqual(manifest["request_count"], 1)
            self.assertEqual(manifest["completed_count"], 1)
            response = json.loads((Path(tmp) / "responses.jsonl").read_text().strip())
            self.assertEqual(response["selected_profile"]["profile_id"], "qwen3_6_27b_bf16_pp8_efficient_v1")
            self.assertIn("centaur-atom-edit-v1", response["output"]["text"])


if __name__ == "__main__":
    unittest.main()
