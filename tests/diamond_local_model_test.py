import unittest

from scripts import qualify_small_model as qualify
from scripts._lib.diamond_local_model import DiamondLocalModelClient
from scripts._lib.diamond_local_model import DiamondLocalModelError
from scripts._lib.diamond_local_model import DiamondSshTransformersClient
from scripts._lib import diamond_local_model as local_model


class DiamondLocalModelTest(unittest.TestCase):
    def test_endpoint_is_required_without_fallback(self) -> None:
        client = DiamondLocalModelClient("")
        with self.assertRaisesRegex(DiamondLocalModelError, "no fallback provider"):
            client.propose_refactor("def f():\n    return 1\n", "inline_path")

    def test_frontier_endpoint_is_rejected(self) -> None:
        client = DiamondLocalModelClient("https://api.openai.com/v1/chat/completions")
        with self.assertRaisesRegex(DiamondLocalModelError, "frontier endpoints are forbidden"):
            client.propose_refactor("def f():\n    return 1\n", "inline_path")

    def test_candidate_source_is_extracted_from_code_fence(self) -> None:
        text = "```python\ndef answer(value):\n    return value + 1\n```"
        self.assertEqual(local_model._extract_candidate_source(text), "def answer(value):\n    return value + 1\n")

    def test_spark_ssh_transformers_client_uses_remote_local_files(self) -> None:
        def runner(command, timeout_seconds):
            self.assertEqual(command[:4], ["ssh", "-o", "BatchMode=yes", "-o"])
            self.assertEqual(command[4], "ConnectTimeout=8")
            self.assertEqual(command[5], "spark2")
            self.assertIn("local_files_only=True", command[-1])
            self.assertIn("--model-path /models/hf/qwen", command[-1])
            payload = '{"generated_text": "def answer(value):\\n    return value + 1", "generated_token_count": 8}'
            return {"returncode": 0, "stdout": qualify.TRANSFORMERS_RESULT_PREFIX + payload, "stderr": "", "elapsed_seconds": 1.5}

        client = DiamondSshTransformersClient("spark2", "/models/hf/qwen", runner=runner)
        record = client.propose_refactor("def answer(value):\n    return value\n", "inline")
        self.assertEqual(record["api_style"], "spark-ssh-transformers")
        self.assertEqual(record["generated_token_count"], 8)
        self.assertEqual(record["candidate_source"], "def answer(value):\n    return value + 1\n")


if __name__ == "__main__":
    unittest.main()
