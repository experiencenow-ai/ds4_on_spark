import os
from pathlib import Path
import subprocess
import sys
import tempfile
import textwrap
import unittest


class Ds4VllmRuntimePatchTests(unittest.TestCase):
    def test_sitecustomize_applies_sm12_flashmla_sparse_patch(self):
        v2_root = Path(__file__).resolve().parents[1]
        src_root = v2_root / "src"
        hook_root = src_root / "ds4_vllm_runtime"
        with tempfile.TemporaryDirectory() as tmp:
            vllm_root = Path(tmp)
            module_dir = vllm_root / "vllm/v1/attention/backends/mla"
            module_dir.mkdir(parents=True)
            for init_dir in [
                "vllm",
                "vllm/v1",
                "vllm/v1/attention",
                "vllm/v1/attention/backends",
                "vllm/v1/attention/backends/mla",
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


if __name__ == "__main__":
    unittest.main()
