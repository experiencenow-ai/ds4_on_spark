import os
from pathlib import Path
import json
import subprocess
import sys
import tempfile
import textwrap
import unittest


class Ds4VllmRuntimePatchTests(unittest.TestCase):
    def _write_fake_vllm(self, vllm_root: Path) -> None:
        module_dir = vllm_root / "vllm/v1/attention/backends/mla"
        ops_dir = vllm_root / "vllm/v1/attention/ops"
        dist_dir = vllm_root / "vllm/distributed"
        engine_dir = vllm_root / "vllm/v1/engine"
        layers_dir = vllm_root / "vllm/model_executor/layers"
        models_dir = vllm_root / "vllm/model_executor/models"
        utils_dir = vllm_root / "vllm/utils"
        module_dir.mkdir(parents=True)
        ops_dir.mkdir(parents=True)
        dist_dir.mkdir(parents=True)
        engine_dir.mkdir(parents=True)
        layers_dir.mkdir(parents=True)
        models_dir.mkdir(parents=True)
        utils_dir.mkdir(parents=True)
        for init_dir in [
            "vllm",
            "vllm/distributed",
            "vllm/model_executor",
            "vllm/model_executor/layers",
            "vllm/model_executor/models",
            "vllm/utils",
            "vllm/v1",
            "vllm/v1/attention",
            "vllm/v1/attention/backends",
            "vllm/v1/attention/backends/mla",
            "vllm/v1/attention/ops",
            "vllm/v1/engine",
        ]:
            (vllm_root / init_dir / "__init__.py").write_text("")
        (vllm_root / "vllm/__init__.py").write_text('__version__ = "fake-vllm-new"\n')
        (vllm_root / "torch.py").write_text(
            textwrap.dedent(
                """
                class _Device:
                    def __init__(self, kind):
                        self.type = kind
                    def __str__(self):
                        return self.type

                class Tensor:
                    def __init__(self, device="cuda", shape=(4,), dtype="fake"):
                        self.device = _Device(device)
                        self.shape = tuple(shape)
                        self.dtype = dtype
                    @property
                    def is_cuda(self):
                        return self.device.type == "cuda"
                    @property
                    def is_cpu(self):
                        return self.device.type == "cpu"
                    def numel(self):
                        out = 1
                        for dim in self.shape:
                            out *= dim
                        return out
                    def element_size(self):
                        return 2
                    def size(self):
                        return self.shape
                    def detach(self):
                        return self
                    def to(self, device):
                        return Tensor(str(device), self.shape, self.dtype)
                    def contiguous(self):
                        return self
                    def reshape(self, *shape):
                        if len(shape) == 1 and isinstance(shape[0], tuple):
                            shape = shape[0]
                        return Tensor(self.device.type, shape, self.dtype)
                    def record_stream(self, stream):
                        pass

                def empty(size, dtype=None, device="cpu"):
                    return Tensor(str(device), tuple(size), dtype or "fake")

                def zeros(size, dtype=None, device="cpu"):
                    return Tensor(str(device), tuple(size), dtype or "fake")

                int32 = "int32"

                class _Work:
                    def wait(self):
                        pass
                    def is_completed(self):
                        return True

                class _Distributed:
                    def __init__(self):
                        self.initialized = True
                    def is_initialized(self):
                        return self.initialized
                    def isend(self, *args, **kwargs):
                        return _Work()
                    def irecv(self, *args, **kwargs):
                        return _Work()

                class _Cuda:
                    def current_stream(self, device=None):
                        return None

                distributed = _Distributed()
                cuda = _Cuda()
                """
            )
        )
        (vllm_root / "vllm/envs.py").write_text(
            textwrap.dedent(
                """
                import os

                environment_variables = {
                    "VLLM_HOST_IP": lambda: os.getenv("VLLM_HOST_IP", ""),
                }

                def __getattr__(name):
                    if name in environment_variables:
                        return environment_variables[name]()
                    raise AttributeError(name)

                def validate_environ(hard_fail):
                    for key in os.environ:
                        if key.startswith("VLLM_") and key not in environment_variables:
                            if hard_fail:
                                raise ValueError(key)
                """
            )
        )
        (dist_dir / "parallel_state.py").write_text(
            textwrap.dedent(
                """
                from collections import namedtuple
                import torch

                TensorMetadata = namedtuple("TensorMetadata", ["device", "dtype", "size"])

                def _split_tensor_dict(tensor_dict):
                    metadata = []
                    tensors = []
                    for key, value in tensor_dict.items():
                        if isinstance(value, torch.Tensor):
                            metadata.append((key, TensorMetadata("cuda", "fake", (1,))))
                            tensors.append(value)
                        else:
                            metadata.append((key, value))
                    return metadata, tensors

                class GroupCoordinator:
                    def __init__(
                        self,
                        group_ranks,
                        local_rank,
                        torch_distributed_backend,
                        use_device_communicator=True,
                        use_message_queue_broadcaster=False,
                        group_name=None,
                    ):
                        self.group_name = group_name
                        self.unique_name = f"{group_name}:0"
                        self.world_size = 2
                        self.rank = 0
                        self.rank_in_group = 0
                        self.ranks = [0, 1]
                        self.cpu_group = "cpu"
                        self.device_group = "device"
                        self.use_cpu_custom_send_recv = False
                        self.use_device_communicator = use_device_communicator
                        self.device_communicator = (
                            object() if use_device_communicator else None
                        )
                        self.sent_objects = []

                    def send_object(self, obj, dst):
                        self.sent_objects.append((dst, obj))

                    def recv_object(self, src):
                        return []

                    def _should_use_all_gather(
                        self, key, numel, all_gather_group, all_gather_tensors
                    ):
                        return False

                    def isend_tensor_dict(
                        self,
                        tensor_dict,
                        dst=None,
                        all_gather_group=None,
                        all_gather_tensors=None,
                    ):
                        return ["original-send"]

                    def irecv_tensor_dict(
                        self,
                        src=None,
                        all_gather_group=None,
                        all_gather_tensors=None,
                    ):
                        return {"original": True}, [], []
                """
            )
        )
        (module_dir / "flashmla_sparse.py").write_text(
            textwrap.dedent(
                """
                class FlashMLASparseBackend:
                    @classmethod
                    def supports_compute_capability(cls, capability):
                        return capability.major in (9, 10)

                class FlashMLASparseImpl:
                    def _bf16_flash_mla_kernel(self, q, kv_c_and_k_pe_cache, topk_indices):
                        return "original"
                """
            )
        )
        (module_dir / "triton_mla.py").write_text(
            textwrap.dedent(
                """
                class TritonMLABackend:
                    @classmethod
                    def validate_configuration(cls, **kwargs):
                        if kwargs.get("use_sparse"):
                            return ["sparse not supported", "other reason"]
                        return []
                """
            )
        )
        (ops_dir / "triton_decode_attention.py").write_text(
            textwrap.dedent(
                """
                calls = []
                is_hip_ = False

                class _Triton:
                    @staticmethod
                    def next_power_of_2(value):
                        out = 1
                        while out < value:
                            out *= 2
                        return out
                    @staticmethod
                    def cdiv(left, right):
                        return -(-left // right)

                triton = _Triton()

                class _Kernel:
                    def __getitem__(self, grid):
                        def _run(*args, **kwargs):
                            calls.append({"grid": grid, "kwargs": kwargs})
                        return _run

                _fwd_grouped_kernel_stage1 = _Kernel()

                def _decode_grouped_att_m_fwd(*args, **kwargs):
                    return "original"
                """
            )
        )
        (vllm_root / "vllm/_custom_ops.py").write_text(
            "def indexer_k_quant_and_cache(*args, **kwargs):\n    return None\n"
        )
        (utils_dir / "deep_gemm.py").write_text(
            textwrap.dedent(
                """
                def get_paged_mqa_logits_metadata(context_lens, block_size, num_sms):
                    raise RuntimeError("Assertion error (/workspace/.deps/deepgemm-src/csrc/apis/attention.hpp:219): Unsupported architecture")
                """
            )
        )
        (layers_dir / "sparse_attn_indexer.py").write_text(
            textwrap.dedent(
                """
                class SparseAttnIndexer:
                    def forward_cuda(self, hidden_states, q_quant, k, weights):
                        return "original"
                """
            )
        )
        (models_dir / "deepseek_v2.py").write_text(
            textwrap.dedent(
                """
                class DeepseekV2Model:
                    def __init__(self, *, vllm_config, prefix=""):
                        self.index_topk = vllm_config.model_config.hf_config.index_topk
                """
            )
        )
        (models_dir / "glm4_moe_lite.py").write_text(
            textwrap.dedent(
                """
                class Glm4MoeLiteModel:
                    def __init__(self, *, vllm_config, prefix=""):
                        self.index_topk = vllm_config.model_config.hf_config.index_topk
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

                def trtllm_batch_decode_with_kv_cache_mla(**kwargs):
                    block_tables = kwargs["block_tables"]
                    if "backend" in kwargs:
                        return f"{kwargs['backend']}:{block_tables.ndim}"
                    return block_tables.ndim
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

    def test_runtime_patch_allows_sm12_deepgemm_moe_support(self):
        v2_root = Path(__file__).resolve().parents[1]
        src_root = v2_root / "src"
        with tempfile.TemporaryDirectory() as tmp:
            vllm_root = Path(tmp)
            platforms_dir = vllm_root / "vllm/platforms"
            platforms_dir.mkdir(parents=True)
            (vllm_root / "vllm/__init__.py").write_text("")
            (platforms_dir / "__init__.py").write_text("")
            (platforms_dir / "cuda.py").write_text(
                textwrap.dedent(
                    """
                    from collections import namedtuple

                    DeviceCapability = namedtuple("DeviceCapability", ["major", "minor"])

                    class CudaPlatformBase:
                        device_name = "cuda"

                        @classmethod
                        def get_device_capability(cls, device_id=0):
                            return DeviceCapability(12, 1)

                        @classmethod
                        def is_device_capability(cls, capability, device_id=0):
                            current = cls.get_device_capability(device_id)
                            if isinstance(capability, tuple):
                                return current == capability
                            return ((current.major * 10) + current.minor) == capability

                        @classmethod
                        def is_device_capability_family(cls, capability, device_id=0):
                            current = cls.get_device_capability(device_id)
                            return (((current.major * 10) + current.minor) // 10) == (capability // 10)

                        @classmethod
                        def support_deep_gemm(cls):
                            return cls.is_device_capability(90) or cls.is_device_capability_family(100)

                    class NvmlCudaPlatform(CudaPlatformBase):
                        pass

                    class NonNvmlCudaPlatform(CudaPlatformBase):
                        pass

                    CudaPlatform = NvmlCudaPlatform
                    """
                )
            )
            code = textwrap.dedent(
                """
                from ds4_vllm_runtime.patches import apply_runtime_patches
                from vllm.platforms.cuda import CudaPlatformBase

                print(CudaPlatformBase.support_deep_gemm())
                print(apply_runtime_patches())
                print(CudaPlatformBase.support_deep_gemm())
                print(CudaPlatformBase.is_device_capability_blackwell())
                """
            )
            env = os.environ.copy()
            env["DS4_VLLM_SM12_DEEPGEMM_MOE"] = "1"
            env["PYTHONPATH"] = os.pathsep.join([str(vllm_root), str(src_root)])
            result = subprocess.run(
                [sys.executable, "-c", code],
                env=env,
                check=True,
                text=True,
                capture_output=True,
            )
        lines = result.stdout.strip().splitlines()
        self.assertEqual(lines[0], "False")
        self.assertIn("deepgemm_moe_sm12_support:", lines[1])
        self.assertEqual(lines[2:], ["True", "True"])

    def test_runtime_patch_applies_flashmla_torch_fallback(self):
        v2_root = Path(__file__).resolve().parents[1]
        src_root = v2_root / "src"
        with tempfile.TemporaryDirectory() as tmp:
            vllm_root = Path(tmp)
            self._write_fake_vllm(vllm_root)
            code = textwrap.dedent(
                """
                from ds4_vllm_runtime.patches import apply_runtime_patches
                from vllm.v1.attention.backends.mla.flashmla_sparse import FlashMLASparseImpl
                print(apply_runtime_patches())
                print(getattr(FlashMLASparseImpl._bf16_flash_mla_kernel, "_ds4_sm12_torch_sparse_fallback", False))
                """
            )
            env = os.environ.copy()
            env["DS4_VLLM_FLASHMLA_SPARSE_TORCH_FALLBACK"] = "1"
            env["PYTHONPATH"] = os.pathsep.join([str(vllm_root), str(src_root)])
            result = subprocess.run(
                [sys.executable, "-c", code],
                env=env,
                check=True,
                text=True,
                capture_output=True,
            )
        self.assertIn("flashmla_sparse_torch_fallback", result.stdout)
        self.assertEqual(result.stdout.strip().splitlines()[-1], "True")

    def test_runtime_patch_applies_flashmla_triton_bf16_fallback(self):
        v2_root = Path(__file__).resolve().parents[1]
        src_root = v2_root / "src"
        with tempfile.TemporaryDirectory() as tmp:
            vllm_root = Path(tmp)
            self._write_fake_vllm(vllm_root)
            code = textwrap.dedent(
                """
                from ds4_vllm_runtime.patches import apply_runtime_patches
                from vllm.v1.attention.backends.mla.flashmla_sparse import FlashMLASparseImpl
                print(apply_runtime_patches())
                print(getattr(FlashMLASparseImpl._bf16_flash_mla_kernel, "_ds4_sm12_triton_sparse_bf16_fallback", False))
                """
            )
            env = os.environ.copy()
            env["DS4_VLLM_FLASHMLA_SPARSE_TRITON_BF16_FALLBACK"] = "1"
            env["PYTHONPATH"] = os.pathsep.join([str(vllm_root), str(src_root)])
            result = subprocess.run(
                [sys.executable, "-c", code],
                env=env,
                check=True,
                text=True,
                capture_output=True,
            )
        self.assertIn("flashmla_sparse_triton_bf16_fallback", result.stdout)
        self.assertEqual(result.stdout.strip().splitlines()[-1], "True")

    def test_runtime_patch_allows_triton_mla_sparse_validation(self):
        v2_root = Path(__file__).resolve().parents[1]
        src_root = v2_root / "src"
        with tempfile.TemporaryDirectory() as tmp:
            vllm_root = Path(tmp)
            self._write_fake_vllm(vllm_root)
            code = textwrap.dedent(
                """
                import vllm.envs as envs
                from ds4_vllm_runtime.patches import apply_runtime_patches
                from vllm.v1.attention.backends.mla.triton_mla import TritonMLABackend
                print(TritonMLABackend.validate_configuration(use_sparse=True))
                print(apply_runtime_patches())
                envs.validate_environ(True)
                print(envs.VLLM_TRITON_MLA_SPARSE)
                print(TritonMLABackend.validate_configuration(use_sparse=True))
                print(TritonMLABackend.validate_configuration(use_sparse=False))
                print(apply_runtime_patches().count("triton_mla_sparse_validation"))
                """
            )
            env = os.environ.copy()
            env["VLLM_TRITON_MLA_SPARSE"] = "1"
            env["PYTHONPATH"] = os.pathsep.join([str(vllm_root), str(src_root)])
            result = subprocess.run(
                [sys.executable, "-c", code],
                env=env,
                check=True,
                text=True,
                capture_output=True,
            )
        lines = result.stdout.strip().splitlines()
        self.assertEqual(lines[0], "['sparse not supported', 'other reason']")
        self.assertIn("vllm_ds4_envs_registered_", lines[1])
        self.assertIn("triton_mla_sparse_validation", lines[1])
        self.assertEqual(lines[2], "True")
        self.assertEqual(lines[3], "['other reason']")
        self.assertEqual(lines[4], "[]")
        self.assertEqual(lines[5], "1")

    def test_runtime_patch_tunes_triton_mla_decode_block_h(self):
        v2_root = Path(__file__).resolve().parents[1]
        src_root = v2_root / "src"
        with tempfile.TemporaryDirectory() as tmp:
            vllm_root = Path(tmp)
            self._write_fake_vllm(vllm_root)
            code = textwrap.dedent(
                """
                from ds4_vllm_runtime.patches import apply_runtime_patches
                import vllm.v1.attention.ops.triton_decode_attention as decode

                class T:
                    def __init__(self, shape):
                        self.shape = tuple(shape)
                    def stride(self, axis):
                        return 100 + axis

                print(apply_runtime_patches())
                decode._decode_grouped_att_m_fwd(
                    T((1, 32, 576)),
                    T((1, 1, 1, 576)),
                    T((1, 1, 1, 512)),
                    T((1, 32, 512)),
                    T((1, 1)),
                    T((1,)),
                    2,
                    1.0,
                    1,
                    0.0,
                    object(),
                    object(),
                    is_mla=True,
                )
                call = decode.calls[-1]
                print(call["grid"])
                print(call["kwargs"]["BLOCK_H"])
                print(call["kwargs"]["num_stages"])
                print(call["kwargs"]["BLOCK_DMODEL"])
                print(call["kwargs"]["BLOCK_DPE"])
                """
            )
            env = os.environ.copy()
            env["VLLM_DS4_TRITON_MLA_BLOCK_H"] = "8"
            env["VLLM_DS4_TRITON_MLA_NUM_STAGES"] = "1"
            env["PYTHONPATH"] = os.pathsep.join([str(vllm_root), str(src_root)])
            result = subprocess.run(
                [sys.executable, "-c", code],
                env=env,
                check=True,
                text=True,
                capture_output=True,
            )
        lines = result.stdout.strip().splitlines()
        self.assertIn("triton_mla_decode_tuning", lines[0])
        self.assertEqual(lines[1], "(1, 4, 2)")
        self.assertEqual(lines[2], "8")
        self.assertEqual(lines[3], "1")
        self.assertEqual(lines[4], "512")
        self.assertEqual(lines[5], "64")

    def test_sitecustomize_applies_pp_tcp_transport_patch(self):
        v2_root = Path(__file__).resolve().parents[1]
        src_root = v2_root / "src"
        hook_root = src_root / "ds4_vllm_runtime"
        with tempfile.TemporaryDirectory() as tmp:
            vllm_root = Path(tmp)
            self._write_fake_vllm(vllm_root)
            code = textwrap.dedent(
                """
                import vllm.envs as envs
                from vllm.distributed.parallel_state import GroupCoordinator
                envs.validate_environ(True)
                group = GroupCoordinator(
                    group_ranks=[[0, 1]],
                    local_rank=0,
                    torch_distributed_backend="gloo",
                    use_device_communicator=True,
                    group_name="pp",
                )
                print(envs.VLLM_DS4_PP_TCP_TENSOR_DICT)
                print(group.use_device_communicator)
                print(group.device_communicator is None)
                print(type(group.ds4_pp_tcp_tensor_channel).__name__)
                print(group.isend_tensor_dict({"marker": "ok"}))
                print(group.sent_objects)
                """
            )
            env = os.environ.copy()
            env["VLLM_DS4_PP_DISABLE_DEVICE_COMMUNICATOR"] = "1"
            env["VLLM_DS4_PP_TCP_TENSOR_DICT"] = "1"
            env["VLLM_DS4_PP_TCP_BIND_HOST"] = "127.0.0.1"
            env["VLLM_DS4_PP_TCP_ADVERTISE_HOST"] = "127.0.0.1"
            env["VLLM_DS4_PP_TCP_STRIPES"] = "2"
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
        lines = result.stdout.strip().splitlines()
        self.assertEqual(lines[:5], ["True", "False", "True", "Ds4TcpTensorChannel", "[]"])
        self.assertIn("'marker', 'ok'", lines[5])

    def test_pp_tcp_patch_handles_positional_group_name(self):
        v2_root = Path(__file__).resolve().parents[1]
        src_root = v2_root / "src"
        hook_root = src_root / "ds4_vllm_runtime"
        with tempfile.TemporaryDirectory() as tmp:
            vllm_root = Path(tmp)
            self._write_fake_vllm(vllm_root)
            code = textwrap.dedent(
                """
                from vllm.distributed.parallel_state import GroupCoordinator
                group = GroupCoordinator([[0, 1]], 0, "gloo", True, False, "pp")
                print(group.use_device_communicator)
                print(group.device_communicator is None)
                print(type(group.ds4_pp_tcp_tensor_channel).__name__)
                """
            )
            env = os.environ.copy()
            env["VLLM_DS4_PP_DISABLE_DEVICE_COMMUNICATOR"] = "1"
            env["VLLM_DS4_PP_TCP_TENSOR_DICT"] = "1"
            env["VLLM_DS4_PP_TCP_BIND_HOST"] = "127.0.0.1"
            env["VLLM_DS4_PP_TCP_ADVERTISE_HOST"] = "127.0.0.1"
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
        self.assertEqual(
            result.stdout.strip().splitlines(),
            ["False", "True", "Ds4TcpTensorChannel"],
        )

    def test_pp_patch_cpu_stages_cuda_tensor_dict_without_upstream_helper(self):
        v2_root = Path(__file__).resolve().parents[1]
        src_root = v2_root / "src"
        hook_root = src_root / "ds4_vllm_runtime"
        with tempfile.TemporaryDirectory() as tmp:
            vllm_root = Path(tmp)
            self._write_fake_vllm(vllm_root)
            code = textwrap.dedent(
                """
                import torch
                from vllm.distributed.parallel_state import GroupCoordinator
                group = GroupCoordinator(
                    [[0, 1]], 0, "gloo", True, False, group_name="pp"
                )
                handles = group.isend_tensor_dict(
                    {"hidden_states": torch.Tensor(device="cuda", shape=(8,))}
                )
                metadata = group.sent_objects[0][1][0][1]
                print(type(metadata).__name__)
                print(metadata.target_device)
                print(len(handles))
                """
            )
            env = os.environ.copy()
            env["VLLM_DS4_PP_CPU_STAGED_TENSOR_DICT"] = "1"
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
        self.assertEqual(
            result.stdout.strip().splitlines(),
            ["TensorMetadataCpuStaged", "cuda", "1"],
        )

    def test_pp_tcp_channel_caps_stripes_by_minimum_bytes(self):
        v2_root = Path(__file__).resolve().parents[1]
        src_root = v2_root / "src"
        with tempfile.TemporaryDirectory() as tmp:
            vllm_root = Path(tmp)
            self._write_fake_vllm(vllm_root)
            code = textwrap.dedent(
                """
                from types import SimpleNamespace
                from ds4_vllm_runtime.pp_tcp_tensor_channel import Ds4TcpTensorChannel
                env = SimpleNamespace(
                    VLLM_DS4_PP_TCP_STRIPES=16,
                    VLLM_DS4_PP_TCP_STRIPE_MIN_BYTES=262144,
                )
                channel = Ds4TcpTensorChannel(
                    rank=0,
                    rank_in_group=0,
                    envs=env,
                    send_control=lambda obj, dst: None,
                    recv_control=lambda src: None,
                )
                for byte_count in (32768, 262144, 262145, 1048576, 8388608):
                    print(channel._stripe_count(byte_count))
                """
            )
            env = os.environ.copy()
            env["PYTHONPATH"] = os.pathsep.join([str(vllm_root), str(src_root)])
            result = subprocess.run(
                [sys.executable, "-c", code],
                env=env,
                check=True,
                text=True,
                capture_output=True,
            )
        self.assertEqual(result.stdout.strip().splitlines(), ["1", "1", "2", "4", "16"])

    def test_runtime_patch_overrides_index_topk(self):
        v2_root = Path(__file__).resolve().parents[1]
        src_root = v2_root / "src"
        with tempfile.TemporaryDirectory() as tmp:
            vllm_root = Path(tmp)
            self._write_fake_vllm(vllm_root)
            code = textwrap.dedent(
                """
                from types import SimpleNamespace
                from ds4_vllm_runtime.patches import apply_runtime_patches
                from vllm.model_executor.models.deepseek_v2 import DeepseekV2Model
                config = SimpleNamespace(index_topk=2048)
                vllm_config = SimpleNamespace(model_config=SimpleNamespace(hf_config=config))
                print(apply_runtime_patches())
                model = DeepseekV2Model(vllm_config=vllm_config)
                print(model.index_topk)
                print(config._ds4_original_index_topk)
                """
            )
            env = os.environ.copy()
            env["DS4_VLLM_INDEX_TOPK_OVERRIDE"] = "512"
            env["PYTHONPATH"] = os.pathsep.join([str(vllm_root), str(src_root)])
            result = subprocess.run(
                [sys.executable, "-c", code],
                env=env,
                check=True,
                text=True,
                capture_output=True,
            )
        self.assertIn("index_topk_override_512", result.stdout)
        self.assertEqual(result.stdout.strip().splitlines()[-2:], ["512", "2048"])

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
            env["DS4_VLLM_FLASHMLA_SPARSE_TORCH_FALLBACK"] = "1"
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
        self.assertIn("flashmla_sparse_torch_fallback", result.stdout)
        self.assertIn("ready_response_block_size_compat", result.stdout)

    def test_runtime_patch_applies_sparse_indexer_dense_fallback(self):
        v2_root = Path(__file__).resolve().parents[1]
        src_root = v2_root / "src"
        with tempfile.TemporaryDirectory() as tmp:
            vllm_root = Path(tmp)
            self._write_fake_vllm(vllm_root)
            code = textwrap.dedent(
                """
                from ds4_vllm_runtime.patches import apply_runtime_patches
                import torch
                import vllm.utils.deep_gemm as deep_gemm
                from vllm.model_executor.layers.sparse_attn_indexer import SparseAttnIndexer
                print(apply_runtime_patches())
                print(getattr(SparseAttnIndexer.forward_cuda, "_ds4_sm12_dense_fallback", False))
                metadata = deep_gemm.get_paged_mqa_logits_metadata(torch.Tensor(), 64, 14)
                print(getattr(deep_gemm.get_paged_mqa_logits_metadata, "_ds4_sm12_dense_metadata_fallback", False))
                print(metadata.shape)
                """
            )
            env = os.environ.copy()
            env["DS4_VLLM_SM12_SPARSE_INDEXER_DENSE_FALLBACK"] = "1"
            env["PYTHONPATH"] = os.pathsep.join([str(vllm_root), str(src_root)])
            result = subprocess.run(
                [sys.executable, "-c", code],
                env=env,
                check=True,
                text=True,
                capture_output=True,
            )
        self.assertIn("sparse_indexer_dense_topk_fallback", result.stdout)
        lines = result.stdout.strip().splitlines()
        self.assertEqual(lines[-3], "True")
        self.assertEqual(lines[-2], "True")
        self.assertEqual(lines[-1], "(15, 2)")

    def test_runtime_patch_squeezes_flashinfer_shared_block_tables(self):
        v2_root = Path(__file__).resolve().parents[1]
        src_root = v2_root / "src"
        with tempfile.TemporaryDirectory() as tmp:
            vllm_root = Path(tmp)
            self._write_fake_vllm(vllm_root)
            code = textwrap.dedent(
                """
                from types import SimpleNamespace
                from ds4_vllm_runtime.patches import apply_runtime_patches
                import vllm.v1.attention.backends.mla.flashinfer_mla_sparse as sparse
                apply_runtime_patches()
                block_tables = SimpleNamespace(ndim=3, shape=(2, 1, 4), squeeze=lambda dim: SimpleNamespace(ndim=2, shape=(2, 4)))
                print(sparse.trtllm_batch_decode_with_kv_cache_mla(block_tables=block_tables))
                """
            )
            env = os.environ.copy()
            env["DS4_VLLM_FLASHINFER_MLA_SHARED_BLOCK_TABLES_2D"] = "1"
            env["PYTHONPATH"] = os.pathsep.join([str(vllm_root), str(src_root)])
            result = subprocess.run(
                [sys.executable, "-c", code],
                env=env,
                check=True,
                text=True,
                capture_output=True,
            )
        self.assertEqual(result.stdout.strip(), "2")

    def test_runtime_patch_forces_flashinfer_mla_trtllm_gen_backend(self):
        v2_root = Path(__file__).resolve().parents[1]
        src_root = v2_root / "src"
        with tempfile.TemporaryDirectory() as tmp:
            vllm_root = Path(tmp)
            self._write_fake_vllm(vllm_root)
            code = textwrap.dedent(
                """
                from types import SimpleNamespace
                from ds4_vllm_runtime.patches import apply_runtime_patches
                import vllm.v1.attention.backends.mla.flashinfer_mla_sparse as sparse
                apply_runtime_patches()
                block_tables = SimpleNamespace(ndim=2, shape=(2, 4))
                print(sparse.trtllm_batch_decode_with_kv_cache_mla(block_tables=block_tables))
                """
            )
            env = os.environ.copy()
            env["DS4_VLLM_FLASHINFER_MLA_FORCE_TRTLLM_GEN"] = "1"
            env["PYTHONPATH"] = os.pathsep.join([str(vllm_root), str(src_root)])
            result = subprocess.run(
                [sys.executable, "-c", code],
                env=env,
                check=True,
                text=True,
                capture_output=True,
            )
        self.assertEqual(result.stdout.strip(), "trtllm-gen:2")

    def test_runtime_patch_keeps_trtllm_gen_sparse_block_tables_3d(self):
        v2_root = Path(__file__).resolve().parents[1]
        src_root = v2_root / "src"
        with tempfile.TemporaryDirectory() as tmp:
            vllm_root = Path(tmp)
            self._write_fake_vllm(vllm_root)
            code = textwrap.dedent(
                """
                from types import SimpleNamespace
                from ds4_vllm_runtime.patches import apply_runtime_patches
                import vllm.v1.attention.backends.mla.flashinfer_mla_sparse as sparse
                apply_runtime_patches()
                block_tables = SimpleNamespace(ndim=3, shape=(2, 1, 4), squeeze=lambda dim: SimpleNamespace(ndim=2, shape=(2, 4)))
                print(sparse.trtllm_batch_decode_with_kv_cache_mla(block_tables=block_tables))
                """
            )
            env = os.environ.copy()
            env["DS4_VLLM_FLASHINFER_MLA_SHARED_BLOCK_TABLES_2D"] = "1"
            env["DS4_VLLM_FLASHINFER_MLA_FORCE_TRTLLM_GEN"] = "1"
            env["PYTHONPATH"] = os.pathsep.join([str(vllm_root), str(src_root)])
            result = subprocess.run(
                [sys.executable, "-c", code],
                env=env,
                check=True,
                text=True,
                capture_output=True,
            )
        self.assertEqual(result.stdout.strip(), "trtllm-gen:3")

    def test_runtime_patch_forces_cute_dsl_and_squeezes_sparse_block_tables(self):
        v2_root = Path(__file__).resolve().parents[1]
        src_root = v2_root / "src"
        with tempfile.TemporaryDirectory() as tmp:
            vllm_root = Path(tmp)
            self._write_fake_vllm(vllm_root)
            code = textwrap.dedent(
                """
                from types import SimpleNamespace
                from ds4_vllm_runtime.patches import apply_runtime_patches
                import vllm.v1.attention.backends.mla.flashinfer_mla_sparse as sparse
                apply_runtime_patches()
                block_tables = SimpleNamespace(ndim=3, shape=(2, 1, 4), squeeze=lambda dim: SimpleNamespace(ndim=2, shape=(2, 4)))
                print(sparse.trtllm_batch_decode_with_kv_cache_mla(block_tables=block_tables))
                """
            )
            env = os.environ.copy()
            env["DS4_VLLM_FLASHINFER_MLA_SHARED_BLOCK_TABLES_2D"] = "1"
            env["DS4_VLLM_FLASHINFER_MLA_FORCE_CUTE_DSL"] = "1"
            env["PYTHONPATH"] = os.pathsep.join([str(vllm_root), str(src_root)])
            result = subprocess.run(
                [sys.executable, "-c", code],
                env=env,
                check=True,
                text=True,
                capture_output=True,
            )
        self.assertEqual(result.stdout.strip(), "cute-dsl:2")

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

    def test_runtime_patch_adds_trim_memory_api_to_old_serve_overlay(self):
        v2_root = Path(__file__).resolve().parents[1]
        src_root = v2_root / "src"
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            vllm_root = tmp_path / "vllm_root"
            fastapi_dir = vllm_root / "fastapi"
            serve_dir = vllm_root / "vllm/entrypoints/serve"
            worker_dir = vllm_root / "vllm/v1/worker"
            fastapi_dir.mkdir(parents=True)
            serve_dir.mkdir(parents=True)
            worker_dir.mkdir(parents=True)
            (fastapi_dir / "__init__.py").write_text(
                textwrap.dedent(
                    """
                    from types import SimpleNamespace

                    class Route:
                        def __init__(self, path, endpoint):
                            self.path = path
                            self.endpoint = endpoint
                            self.methods = {"POST"}

                    class APIRouter:
                        def __init__(self):
                            self.routes = []
                        def post(self, path):
                            def decorator(fn):
                                self.routes.append(Route(path, fn))
                                return fn
                            return decorator

                    class FastAPI:
                        def __init__(self):
                            self.routes = []
                            self.state = SimpleNamespace()
                        def include_router(self, router):
                            self.routes.extend(router.routes)

                    class HTTPException(Exception):
                        def __init__(self, status_code, detail):
                            super().__init__(detail)
                            self.status_code = status_code
                            self.detail = detail

                    class Request:
                        def __init__(self, app):
                            self.app = app

                    def Query(default=None):
                        return default
                    """
                )
            )
            (fastapi_dir / "responses.py").write_text(
                textwrap.dedent(
                    """
                    class JSONResponse:
                        def __init__(self, content, status_code=200):
                            self.content = content
                            self.status_code = status_code
                    """
                )
            )
            for init_dir in [
                "vllm",
                "vllm/entrypoints",
                "vllm/entrypoints/serve",
                "vllm/v1",
                "vllm/v1/worker",
            ]:
                (vllm_root / init_dir / "__init__.py").write_text("")
            (serve_dir / "__init__.py").write_text(
                textwrap.dedent(
                    """
                    def register_vllm_serve_api_routers(app):
                        app.state.original_router_called = True
                    """
                )
            )
            (worker_dir / "worker_base.py").write_text(
                "class WorkerBase:\n    pass\n"
            )
            code = textwrap.dedent(
                """
                import asyncio
                import json
                from fastapi import FastAPI, Request
                from typing import get_type_hints
                from ds4_vllm_runtime.patches import apply_runtime_patches

                class Engine:
                    def __init__(self):
                        self.calls = []
                    async def pause_generation(self, **kwargs):
                        self.calls.append(["pause", kwargs])
                    async def collective_rpc(self, method, timeout=None, args=(), kwargs=None):
                        self.calls.append(["collective", method, kwargs])
                        return [{"rank": 0, "process": {"malloc_trim": False}}]
                    async def reset_prefix_cache(self, reset_running_requests=False, reset_connector=False):
                        self.calls.append(["prefix", reset_running_requests, reset_connector])
                        return True
                    async def reset_mm_cache(self):
                        self.calls.append(["mm"])
                    async def reset_encoder_cache(self):
                        self.calls.append(["encoder"])
                    async def resume_generation(self):
                        self.calls.append(["resume"])

                print(json.dumps(apply_runtime_patches()))
                from vllm.entrypoints.serve import register_vllm_serve_api_routers
                from vllm.v1.worker.worker_base import WorkerBase
                app = FastAPI()
                engine = Engine()
                app.state.engine_client = engine
                register_vllm_serve_api_routers(app)
                route = [r for r in app.routes if r.path == "/v1/trim_memory"][0]
                request_hint_ok = get_type_hints(route.endpoint)["raw_request"] is Request
                response = asyncio.run(
                    route.endpoint(
                        Request(app),
                        mode="wait",
                        malloc_trim=False,
                    )
                )
                worker_result = WorkerBase().trim_memory(malloc_trim=False)
                print(json.dumps({
                    "status_code": response.status_code,
                    "body": response.content,
                    "calls": engine.calls,
                    "original": getattr(app.state, "original_router_called", False),
                    "request_hint_ok": request_hint_ok,
                    "worker_keys": sorted(worker_result.keys()),
                }, sort_keys=True))
                """
            )
            env = os.environ.copy()
            env["DS4_VLLM_ENABLE_TRIM_MEMORY"] = "1"
            env["PYTHONPATH"] = os.pathsep.join([str(vllm_root), str(src_root)])
            result = subprocess.run(
                [sys.executable, "-c", code],
                env=env,
                check=True,
                text=True,
                capture_output=True,
            )
        lines = result.stdout.strip().splitlines()
        patches = json.loads(lines[0])
        payload = json.loads(lines[1])
        self.assertIn("trim_memory_api:trim_memory_worker", patches)
        self.assertEqual(payload["status_code"], 200)
        self.assertEqual(payload["body"]["status"], "ok")
        self.assertTrue(payload["original"])
        self.assertTrue(payload["request_hint_ok"])
        self.assertEqual(payload["worker_keys"], ["connector", "process"])
        self.assertEqual(payload["calls"][0][0], "pause")
        self.assertEqual(payload["calls"][1][0], "collective")
        self.assertEqual(payload["calls"][-1][0], "resume")


if __name__ == "__main__":
    unittest.main()
