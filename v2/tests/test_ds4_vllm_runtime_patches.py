import os
from pathlib import Path
import subprocess
import sys
import tempfile
import textwrap
import unittest


class Ds4VllmRuntimePatchTests(unittest.TestCase):
    def _write_fake_vllm(self, vllm_root: Path) -> None:
        module_dir = vllm_root / "vllm/v1/attention/backends/mla"
        engine_dir = vllm_root / "vllm/v1/engine"
        module_dir.mkdir(parents=True)
        engine_dir.mkdir(parents=True)
        for init_dir in [
            "vllm",
            "vllm/v1",
            "vllm/v1/attention",
            "vllm/v1/attention/backends",
            "vllm/v1/attention/backends/mla",
            "vllm/v1/engine",
        ]:
            (vllm_root / init_dir / "__init__.py").write_text("")
        (module_dir / "flashmla_sparse.py").write_text(
            textwrap.dedent(
                """
                class FlashMLASparseBackend:
                    @classmethod
                    def supports_compute_capability(cls, capability):
                        return capability.major in (9, 10)
                """
            )
        )
        (engine_dir / "core_client.py").write_text(
            textwrap.dedent(
                """
                import json
                from types import SimpleNamespace

                class ValidationError(Exception):
                    pass

                class EngineCoreReadyResponse:
                    pass

                class Msgpack:
                    @staticmethod
                    def decode(payload, type=None):
                        data = json.loads(payload.decode("utf-8"))
                        if type is EngineCoreReadyResponse:
                            if "block_size" not in data:
                                raise ValidationError(
                                    "Object missing required field `block_size`"
                                )
                            return SimpleNamespace(**data)
                        return data

                    @staticmethod
                    def encode(data):
                        return json.dumps(data).encode("utf-8")

                class Msgspec:
                    ValidationError = ValidationError
                    msgpack = Msgpack

                msgspec = Msgspec

                class MPClient:
                    def __init__(self):
                        self.vllm_config = SimpleNamespace(
                            cache_config=SimpleNamespace(
                                block_size=64, num_gpu_blocks=0
                            ),
                            model_config=SimpleNamespace(max_model_len=8192),
                        )
                        self.stats_update_address = None

                    def _apply_ready_response(self, payload):
                        response = msgspec.msgpack.decode(
                            payload, type=EngineCoreReadyResponse
                        )
                        self.vllm_config.model_config.max_model_len = min(
                            self.vllm_config.model_config.max_model_len,
                            response.max_model_len,
                        )
                        self.vllm_config.cache_config.num_gpu_blocks += (
                            response.num_gpu_blocks
                        )
                        self.vllm_config.cache_config.block_size = response.block_size
                """
            )
        )

    def test_sitecustomize_applies_sm12_flashmla_sparse_patch(self):
        v2_root = Path(__file__).resolve().parents[1]
        src_root = v2_root / "src"
        hook_root = src_root / "ds4_vllm_runtime"
        with tempfile.TemporaryDirectory() as tmp:
            vllm_root = Path(tmp)
            self._write_fake_vllm(vllm_root)
            code = textwrap.dedent(
                """
                from types import SimpleNamespace
                from vllm.v1.attention.backends.mla.flashmla_sparse import FlashMLASparseBackend
                print(FlashMLASparseBackend.supports_compute_capability(SimpleNamespace(major=12)))
                """
            )
            env = os.environ.copy()
            env["DS4_VLLM_SM12_FLASHMLA_SPARSE"] = "1"
            env["DS4_VLLM_RUNTIME_PATCHES_STRICT"] = "1"
            env["PYTHONPATH"] = os.pathsep.join(
                [str(vllm_root), str(hook_root), str(src_root)]
            )
            result = subprocess.run(
                [sys.executable, "-c", code],
                env=env,
                check=True,
                text=True,
                capture_output=True,
            )
        self.assertEqual(result.stdout.strip(), "True")

    def test_runner_check_only_applies_sm12_patch(self):
        v2_root = Path(__file__).resolve().parents[1]
        src_root = v2_root / "src"
        runner = v2_root / "scripts/ds4_run_vllm_from_source.py"
        with tempfile.TemporaryDirectory() as tmp:
            vllm_root = Path(tmp)
            self._write_fake_vllm(vllm_root)
            env = os.environ.copy()
            env["DS4_VLLM_SM12_FLASHMLA_SPARSE"] = "1"
            env["PYTHONPATH"] = str(src_root)
            result = subprocess.run(
                [
                    sys.executable,
                    str(runner),
                    "--source-root",
                    str(vllm_root),
                    "--check-only",
                ],
                env=env,
                check=True,
                text=True,
                capture_output=True,
            )
        self.assertIn("flashmla_sparse_sm12_compute_capability", result.stdout)
        self.assertIn("ready_response_block_size_compat", result.stdout)

    def test_runtime_patch_repairs_old_ready_response_payload(self):
        v2_root = Path(__file__).resolve().parents[1]
        src_root = v2_root / "src"
        with tempfile.TemporaryDirectory() as tmp:
            vllm_root = Path(tmp)
            self._write_fake_vllm(vllm_root)
            code = textwrap.dedent(
                """
                from ds4_vllm_runtime.patches import apply_runtime_patches
                from vllm.v1.engine.core_client import MPClient
                apply_runtime_patches()
                client = MPClient()
                payload = (
                    b'{"max_model_len":4096,"num_gpu_blocks":7,'
                    b'"dp_stats_address":null,"dtype":"bfloat16",'
                    b'"vllm_version":"old"}'
                )
                client._apply_ready_response(payload)
                print(client.vllm_config.model_config.max_model_len)
                print(client.vllm_config.cache_config.num_gpu_blocks)
                print(client.vllm_config.cache_config.block_size)
                """
            )
            env = os.environ.copy()
            env["DS4_VLLM_SM12_FLASHMLA_SPARSE"] = "1"
            env["PYTHONPATH"] = os.pathsep.join([str(vllm_root), str(src_root)])
            result = subprocess.run(
                [sys.executable, "-c", code],
                env=env,
                check=True,
                text=True,
                capture_output=True,
            )
        self.assertEqual(result.stdout.strip().splitlines(), ["4096", "7", "64"])


if __name__ == "__main__":
    unittest.main()
