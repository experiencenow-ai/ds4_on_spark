import json
import tempfile
import unittest
from pathlib import Path

from scripts import discover_preloaded_models as discover
from scripts import qualify_small_model as qualify


class SmallModelQualificationTest(unittest.TestCase):
    def test_inventory_record_shape_from_listing(self) -> None:
        listing = {
            "gguf_files": ["/models/smoke/stories15M-q4_0.gguf", "/models/Qwen3.5-2B/Qwen3.5-2B-Q4_K_M.gguf"],
            "hf_configs": {"/models/hf/Qwen/Qwen3.5-2B/config.json": {"torch_dtype": "bfloat16", "num_parameters": 2_000_000_000}},
            "llama_cli_path": "/opt/llama-cli",
        }
        inventory = discover.discover_from_remote_listing(listing, "spark2", "/models")
        self.assertEqual(inventory["format"], "small-model-inventory-v1")
        self.assertEqual(inventory["model_count"], 3)
        gguf = [item for item in inventory["models"] if item["artifact_type"] == "gguf"]
        self.assertTrue(all(item["serve_backend"] == "llama.cpp" for item in gguf))
        self.assertTrue(all(item["can_serve_request"] for item in gguf))
        by_params = {item["model_size_params"]: item for item in gguf}
        self.assertIn(15_000_000, by_params)
        self.assertIn(2_000_000_000, by_params)

    def test_eval_set_validation_is_deterministic(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "eval.json"
            path.write_text(
                json.dumps(
                    {
                        "format": "small-model-eval-set-v1",
                        "eval_set_id": "unit",
                        "prompts": [
                            {"task_id": "a", "task_kind": "simple_math", "prompt": "Return 4", "expected_answer": "4"},
                            {"task_id": "a", "task_kind": "simple_code", "prompt": "Return OK", "expected_answer": "OK"},
                        ],
                    }
                ),
                encoding="utf-8",
            )
            with self.assertRaises(ValueError):
                qualify.load_eval_set(path)

    def test_missing_model_fails_loudly(self) -> None:
        inventory = {"models": [{"model_id": "present", "model_path": "/models/present.gguf"}]}
        with self.assertRaises(ValueError):
            qualify.find_model(inventory, "missing")

    def test_mock_backend_execution_builds_valid_record(self) -> None:
        model = {
            "model_id": "unit-2b-q4",
            "model_path": "/models/unit.gguf",
            "model_size_params": 2_000_000_000,
            "model_dtype": "Q4_K_M",
            "serve_backend": "llama.cpp",
            "can_serve_request": True,
        }
        eval_set = {
            "format": "small-model-eval-set-v1",
            "eval_set_id": "unit",
            "prompts": [
                {"task_id": "math", "task_kind": "simple_math", "prompt": "Return 4", "expected_answer": "4", "max_tokens": 8},
                {"task_id": "code", "task_kind": "simple_code", "prompt": "Return PASS", "expected_answer": "PASS", "max_tokens": 8},
            ],
        }

        def runner(command, timeout_seconds):
            text = "PASS" if "PASS" in command[-1] else "4"
            return {"returncode": 0, "stdout": text, "stderr": "", "elapsed_seconds": 0.5}

        record = qualify.qualify_model(model, eval_set, "spark2", "/opt/llama-cli", runner=runner)
        self.assertEqual(record["format"], "small-model-qualification-v1")
        self.assertEqual(record["model_id"], "unit-2b-q4")
        self.assertEqual(record["aggregate_metrics"]["pass_rate"], 1.0)
        self.assertEqual(record["aggregate_metrics"]["prompt_count"], 2)
        self.assertEqual(record["cost_proxy_estimate"]["score"], 2.0)

    def test_scoring_ignores_echoed_prompt(self) -> None:
        stdout = "banner\n> Return exactly 4 for 2+2.\n\nwrong answer\n\n[ Prompt: 1 t/s | Generation: 2 t/s ]\nExiting..."
        generated = qualify.extract_generated_text(stdout, "Return exactly 4 for 2+2.")
        self.assertEqual(generated, "wrong answer")
        self.assertFalse(qualify.score_answer("4", generated))

    def test_llama_command_uses_kill_after_timeout(self) -> None:
        command = qualify.build_llama_command("spark2", "/opt/llama-cli", "/models/a.gguf", "Return 4", 8, 60.0)
        self.assertIn("timeout -k 5s 60", command[-1])


if __name__ == "__main__":
    unittest.main()
