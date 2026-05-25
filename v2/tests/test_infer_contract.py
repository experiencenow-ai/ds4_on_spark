from __future__ import annotations

import json
from pathlib import Path
import tempfile
import unittest

from ds4_infer.profiles import ProfileRegistry
from ds4_infer.runners import FakeRunner
from ds4_infer.schemas import InferenceRequest
from ds4_infer.service import run_requests

ROOT = Path(__file__).resolve().parents[1]
PROFILES = ROOT / "profiles" / "models"


class InferenceContractTests(unittest.TestCase):
    def test_efficient_routes_to_qwen_27b(self) -> None:
        profile = ProfileRegistry.load(PROFILES).resolve(capability="efficient", chat=False, job_class="atom_edit")
        self.assertEqual(profile.profile_id, "qwen3_6_27b_fp8_efficient_v1")
        self.assertEqual(profile.quality["ds4_eval_correct"], 76)
        self.assertLess(profile.performance["single_stream_decode_tok_s"], profile.performance["aggregate_decode_tok_s_at_16"])
        self.assertLess(profile.performance["aggregate_decode_tok_s_at_16"], profile.performance["aggregate_decode_tok_s_at_32"])

    def test_fastest_routes_to_qwen_a3b_for_triage(self) -> None:
        profile = ProfileRegistry.load(PROFILES).resolve(capability="fastest", chat=False, job_class="triage")
        self.assertEqual(profile.profile_id, "qwen3_6_35b_a3b_fp8_fastest_v1")

    def test_smart_completion_routes_to_antirez(self) -> None:
        profile = ProfileRegistry.load(PROFILES).resolve(capability="smart", chat=False, job_class="atom_edit")
        self.assertEqual(profile.profile_id, "dsv4_antirez_smart_v1")

    def test_smartest_chat_routes_to_vllm_mtp(self) -> None:
        profile = ProfileRegistry.load(PROFILES).resolve(capability="smartest", chat=True, job_class="tool_chat")
        self.assertEqual(profile.profile_id, "dsv4_vllm_mtp_smartest_v1")

    def test_pin_overrides_capability(self) -> None:
        profile = ProfileRegistry.load(PROFILES).resolve(
            capability="efficient",
            chat=True,
            job_class="atom_edit",
            model_pin={"profile_id": "dsv4_vllm_mtp_smartest_v1"},
        )
        self.assertEqual(profile.profile_id, "dsv4_vllm_mtp_smartest_v1")

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
            self.assertEqual(response["selected_profile"]["profile_id"], "qwen3_6_27b_fp8_efficient_v1")
            self.assertIn("centaur-atom-edit-v1", response["output"]["text"])


if __name__ == "__main__":
    unittest.main()
