import copy
import json
import struct
import tempfile
import unittest
from pathlib import Path

from scripts import analyze_ds4_vllm_pp_safetensors_filter as analyzer
from scripts import validate_ds4_vllm_pp_safetensors_filter as validator


FIXTURE = Path(
    "fixtures/vllm_pp_safetensors_filter/ds4_vllm_pp3_safetensors_filter_spark1_20260519.example.json"
)
PATCH = Path("docs/vllm-patches/ds4-deepseek-v4-pp-safetensors-early-filter.patch")


def write_header(path: Path, tensors: dict[str, int]) -> None:
    offset = 0
    header: dict[str, object] = {}
    for name, nbytes in tensors.items():
        header[name] = {
            "dtype": "U8",
            "shape": [nbytes],
            "data_offsets": [offset, offset + nbytes],
        }
        offset += nbytes
    payload = json.dumps(header, separators=(",", ":"), sort_keys=True).encode("utf-8")
    path.write_bytes(struct.pack("<Q", len(payload)) + payload)


class VllmPpSafetensorsFilterTest(unittest.TestCase):
    def test_fixture_validates(self) -> None:
        result = validator.validate_paths([FIXTURE])
        self.assertTrue(result["ok"], result["errors"])

    def test_analyzer_classifies_pp_skips_before_tensor_load(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            model_dir = Path(tmp)
            write_header(
                model_dir / "model-00001-of-00001.safetensors",
                {
                    "layers.0.ffn.shared_experts.w2.weight": 20,
                    "layers.1.ffn.shared_experts.w2.weight": 30,
                    "layers.2.ffn.shared_experts.w2.weight": 40,
                    "mtp.0.embed.weight": 5,
                    "embed.weight": 7,
                },
            )
            tensors = list(analyzer.iter_tensors(model_dir, "*.safetensors"))
            artifact = analyzer.analyze_tensors(
                tensors,
                [1, 2],
                run_id="unit",
                checked_at="2026-05-19T00:00:00Z",
                model_dir=str(model_dir),
                model_id="unit",
                source_command="unit",
            )
        self.assertEqual(artifact["checkpoint_bytes"], 102)
        rank0 = artifact["rank_stats"][0]
        rank1 = artifact["rank_stats"][1]
        self.assertEqual(rank0["local_layer_bytes"], 20)
        self.assertEqual(rank0["skipped_layer_bytes"], 70)
        self.assertEqual(rank0["mtp_skipped_bytes"], 5)
        self.assertEqual(rank0["global_or_rank_specific_bytes"], 7)
        self.assertEqual(rank0["avoidable_tensor_load_bytes_floor"], 75)
        self.assertEqual(rank1["local_layer_bytes"], 70)
        self.assertEqual(rank1["skipped_layer_bytes"], 20)
        self.assertEqual(rank1["avoidable_tensor_load_bytes_floor"], 25)
        result = validator.validate_artifact(artifact, Path("unit.json"))
        self.assertEqual(result, [])

    def test_validator_rejects_inconsistent_avoidable_bytes(self) -> None:
        obj = validator.load_json(FIXTURE)
        bad = copy.deepcopy(obj)
        bad["rank_stats"][1]["avoidable_tensor_load_bytes_floor"] += 1
        bad["artifact_sha256"] = validator.canonical_hash(bad)
        bad["artifact_hash"] = bad["artifact_sha256"]
        errors = validator.validate_artifact(bad, Path("bad.json"))
        self.assertTrue(any("avoidable_tensor_load_bytes_floor" in item for item in errors))

    def test_validator_rejects_missing_runtime_bug_marker(self) -> None:
        obj = validator.load_json(FIXTURE)
        bad = copy.deepcopy(obj)
        bad["current_iterator_materializes_before_pp_skip"] = False
        bad["artifact_sha256"] = validator.canonical_hash(bad)
        bad["artifact_hash"] = bad["artifact_sha256"]
        errors = validator.validate_artifact(bad, Path("bad.json"))
        self.assertTrue(any("current_iterator_materializes_before_pp_skip" in item for item in errors))

    def test_patch_adds_pre_get_tensor_filter_hook(self) -> None:
        text = PATCH.read_text(encoding="utf-8")
        self.assertIn("weight_name_filter: Callable[[str], bool] | None = None", text)
        self.assertIn("not weight_name_filter(name)", text)
        self.assertIn("f.get_tensor(name)", text)
        self.assertIn("should_load_checkpoint_weight", text)
        self.assertIn("is_pp_missing_parameter(mapped_name, self)", text)


if __name__ == "__main__":
    unittest.main()
