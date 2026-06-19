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
        (vllm_root / "vllm/__init__.py").write_text('__version__ = "fake-vllm-new"\n')
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
        (module_dir / "flashinfer_mla_sparse.py").write_text(
            textwrap.dedent(
                """
                class FlashInferMLASparseBackend:
                    @classmethod
                    def supports_compute_capability(cls, capability):
                        return capability.major == 10
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

                VLLM_VERSION = "fake-vllm-new"

                class Msgpack:
                    @staticmethod
                    def decode(payload, type=None):
                        data = json.loads(payload.decode("utf-8"))
                        if type is EngineCoreReadyResponse:
                            for field in [
                                "max_model_len",
                                "num_gpu_blocks",
                                "block_size",
                                "dp_stats_address",
                                "dtype",
                                "vllm_version",
                            ]:
                                if field not in data:
                                    raise ValidationError(
                                        f"Object missing required field `{field}`"
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
                            model_config=SimpleNamespace(
                                dtype="torch.bfloat16", max_model_len=8192
                            ),
                        )
                        self.stats_update_address = None
                        self.ready_dtype = None
                        self.ready_vllm_version = None

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
                        self.ready_dtype = response.dtype
                        self.ready_vllm_version = response.vllm_version
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

    def test_sitecustomize_applies_sm12_flashinfer_sparse_patch(self):
        v2_root = Path(__file__).resolve().parents[1]
        src_root = v2_root / "src"
        hook_root = src_root / "ds4_vllm_runtime"
        with tempfile.TemporaryDirectory() as tmp:
            vllm_root = Path(tmp)
            self._write_fake_vllm(vllm_root)
            code = textwrap.dedent(
                """
                from types import SimpleNamespace
                from vllm.v1.attention.backends.mla.flashinfer_mla_sparse import FlashInferMLASparseBackend
                print(FlashInferMLASparseBackend.supports_compute_capability(SimpleNamespace(major=12)))
                """
            )
            env = os.environ.copy()
            env["DS4_VLLM_SM12_FLASHINFER_MLA_SPARSE"] = "1"
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

    def test_runner_check_only_applies_sm12_patches(self):
        v2_root = Path(__file__).resolve().parents[1]
        src_root = v2_root / "src"
        runner = v2_root / "scripts/ds4_run_vllm_from_source.py"
        with tempfile.TemporaryDirectory() as tmp:
            vllm_root = Path(tmp)
            self._write_fake_vllm(vllm_root)
            env = os.environ.copy()
            env["DS4_VLLM_SM12_FLASHMLA_SPARSE"] = "1"
            env["DS4_VLLM_SM12_FLASHINFER_MLA_SPARSE"] = "1"
            env["DS4_VLLM_READY_RESPONSE_COMPAT"] = "1"
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
        self.assertIn("flashinfer_mla_sparse_sm12_compute_capability", result.stdout)
        self.assertIn("ready_response_block_size_compat", result.stdout)

    def test_runner_child_pythonpath_enables_sitecustomize_for_flashinfer_patch(self):
        v2_root = Path(__file__).resolve().parents[1]
        src_root = v2_root / "src"
        runner = v2_root / "scripts/ds4_run_vllm_from_source.py"
        with tempfile.TemporaryDirectory() as tmp:
            vllm_root = Path(tmp)
            self._write_fake_vllm(vllm_root)
            child_code = (
                "from types import SimpleNamespace; "
                "from vllm.v1.attention.backends.mla.flashinfer_mla_sparse "
                "import FlashInferMLASparseBackend; "
                "print(FlashInferMLASparseBackend.supports_compute_capability("
                "SimpleNamespace(major=12)))"
            )
            (vllm_root / "child_probe.py").write_text(
                textwrap.dedent(
                    f"""
                    import os
                    import subprocess
                    import sys

                    result = subprocess.run(
                        [sys.executable, "-c", {child_code!r}],
                        env=os.environ.copy(),
                        check=True,
                        text=True,
                        capture_output=True,
                    )
                    print(result.stdout.strip())
                    """
                )
            )
            env = os.environ.copy()
            env["DS4_VLLM_SM12_FLASHINFER_MLA_SPARSE"] = "1"
            env["PYTHONPATH"] = str(src_root)
            result = subprocess.run(
                [
                    sys.executable,
                    str(runner),
                    "--source-root",
                    str(vllm_root),
                    "--module",
                    "child_probe",
                ],
                env=env,
                check=True,
                text=True,
                capture_output=True,
            )
        self.assertIn("flashinfer_mla_sparse_sm12_compute_capability", result.stdout)
        self.assertEqual(result.stdout.strip().splitlines()[-1], "True")

    def test_sitecustomize_writes_child_import_proof(self):
        v2_root = Path(__file__).resolve().parents[1]
        src_root = v2_root / "src"
        runner = v2_root / "scripts/ds4_run_vllm_from_source.py"
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            vllm_root = tmp_path / "fake_vllm"
            proof_path = tmp_path / "proof.json"
            self._write_fake_vllm(vllm_root)
            (vllm_root / "child_probe.py").write_text(
                textwrap.dedent(
                    """
                    import os
                    import subprocess
                    import sys

                    subprocess.run(
                        [sys.executable, "-c", "import vllm; print(vllm.__file__)"],
                        env=os.environ.copy(),
                        check=True,
                        text=True,
                        capture_output=True,
                    )
                    """
                )
            )
            env = os.environ.copy()
            env["DS4_VLLM_READY_RESPONSE_COMPAT"] = "1"
            env["DS4_VLLM_IMPORT_PROOF_JSON"] = str(proof_path)
            env["PYTHONPATH"] = str(src_root)
            subprocess.run(
                [
                    sys.executable,
                    str(runner),
                    "--source-root",
                    str(vllm_root),
                    "--module",
                    "child_probe",
                ],
                env=env,
                check=True,
                text=True,
                capture_output=True,
            )
            parent = proof_path.read_text()
            child_proofs = list(tmp_path.glob("proof.sitecustomize.pid*.json"))
            self.assertIn(str(vllm_root / "vllm/__init__.py"), parent)
            self.assertTrue(child_proofs)
            self.assertIn(
                str(vllm_root / "vllm/__init__.py"), child_proofs[0].read_text()
            )

    def test_sitecustomize_forces_source_root_ahead_of_old_editable_vllm(self):
        v2_root = Path(__file__).resolve().parents[1]
        src_root = v2_root / "src"
        hook_root = src_root / "ds4_vllm_runtime"
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            old_root = tmp_path / "old_vllm"
            new_root = tmp_path / "new_vllm"
            proof_path = tmp_path / "proof.json"
            self._write_fake_vllm(old_root)
            self._write_fake_vllm(new_root)
            (old_root / "vllm/__init__.py").write_text('__version__ = "old-vllm"\n')
            code = "import vllm; print(vllm.__version__); print(vllm.__file__)"
            env = os.environ.copy()
            env["DS4_VLLM_READY_RESPONSE_COMPAT"] = "1"
            env["DS4_VLLM_IMPORT_PROOF_JSON"] = str(proof_path)
            env["DS4_VLLM_SOURCE_ROOT"] = str(new_root)
            env["PYTHONPATH"] = os.pathsep.join(
                [str(old_root), str(new_root), str(hook_root), str(src_root)]
            )
            result = subprocess.run(
                [sys.executable, "-c", code],
                env=env,
                check=True,
                text=True,
                capture_output=True,
            )
            proof_files = list(tmp_path.glob("proof.sitecustomize.pid*.json"))
            self.assertTrue(proof_files)
            proof = proof_files[0].read_text()
        self.assertEqual(result.stdout.strip().splitlines()[0], "fake-vllm-new")
        self.assertIn(str(new_root / "vllm/__init__.py"), result.stdout)
        self.assertIn(str(new_root / "vllm/__init__.py"), proof)
        self.assertNotIn(str(old_root / "vllm/__init__.py"), proof)

    def test_runtime_patch_repairs_old_ready_response_payload_without_flashmla(self):
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
                    b'{"max_model_len":4096,"num_gpu_blocks":7}'
                )
                client._apply_ready_response(payload)
                print(client.vllm_config.model_config.max_model_len)
                print(client.vllm_config.cache_config.num_gpu_blocks)
                print(client.vllm_config.cache_config.block_size)
                print(client.ready_dtype)
                print(client.ready_vllm_version)
                """
            )
            env = os.environ.copy()
            env["DS4_VLLM_READY_RESPONSE_COMPAT"] = "1"
            env["PYTHONPATH"] = os.pathsep.join([str(vllm_root), str(src_root)])
            result = subprocess.run(
                [sys.executable, "-c", code],
                env=env,
                check=True,
                text=True,
                capture_output=True,
            )
        self.assertEqual(
            result.stdout.strip().splitlines(),
            ["4096", "7", "64", "bfloat16", "fake-vllm-new"],
        )


if __name__ == "__main__":
    unittest.main()
