"""Runtime patch for DS4 PP tensor-dict TCP transport on vLLM overlays."""

from __future__ import annotations

import importlib
from collections import namedtuple
from collections.abc import Callable
from typing import Any

from ds4_vllm_runtime.vllm_env_registry import register_ds4_vllm_envs

_FallbackTensorMetadata = namedtuple("TensorMetadata", ["device", "dtype", "size"])
_FallbackTensorMetadataCpuStaged = namedtuple(
    "TensorMetadataCpuStaged", ["target_device", "dtype", "size"]
)
_ORIGINAL_INIT: Callable[..., None] | None = None
_ORIGINAL_ISEND: Callable[..., list[Any]] | None = None
_ORIGINAL_IRECV: Callable[..., tuple[dict[str, Any] | None, list[Any], list[Any]]] | None = None


def patch_ds4_pp_tcp_tensor_transport() -> str:
    register_ds4_vllm_envs()
    parallel_state = importlib.import_module("vllm.distributed.parallel_state")
    group_cls = getattr(parallel_state, "GroupCoordinator")
    if getattr(group_cls, "_ds4_pp_tcp_runtime_patch", False):
        return "pp_tcp_tensor_transport"
    _capture_originals(group_cls)
    group_cls.__init__ = _init_with_ds4_tcp
    group_cls.isend_tensor_dict = _isend_tensor_dict
    group_cls.irecv_tensor_dict = _irecv_tensor_dict
    group_cls._ds4_pp_tcp_runtime_patch = True
    return "pp_tcp_tensor_transport"


def _capture_originals(group_cls: Any) -> None:
    global _ORIGINAL_INIT, _ORIGINAL_ISEND, _ORIGINAL_IRECV
    _ORIGINAL_INIT = group_cls.__init__
    _ORIGINAL_ISEND = group_cls.isend_tensor_dict
    _ORIGINAL_IRECV = group_cls.irecv_tensor_dict


def _modules() -> tuple[Any, Any, Any]:
    parallel_state = importlib.import_module("vllm.distributed.parallel_state")
    envs = importlib.import_module("vllm.envs")
    torch = importlib.import_module("torch")
    return parallel_state, envs, torch


def _is_pp_group(group: Any) -> bool:
    return "pp" in str(getattr(group, "unique_name", ""))


def _can_use_tcp(group: Any) -> bool:
    _, envs, _ = _modules()
    if not envs.VLLM_DS4_PP_TCP_TENSOR_DICT:
        return False
    if not _is_pp_group(group) or int(getattr(group, "world_size", 1)) <= 1:
        return False
    _reject_conflicting_transports(envs)
    if getattr(group, "ds4_pp_tcp_tensor_channel", None) is None:
        raise RuntimeError(
            "VLLM_DS4_PP_TCP_TENSOR_DICT is enabled, but the PP group has "
            "no DS4 TCP tensor channel."
        )
    return True


def _reject_conflicting_transports(envs: Any) -> None:
    if envs.VLLM_DS4_PP_CPU_STAGED_TENSOR_DICT:
        raise RuntimeError(
            "VLLM_DS4_PP_TCP_TENSOR_DICT and "
            "VLLM_DS4_PP_CPU_STAGED_TENSOR_DICT cannot both be enabled."
        )
    if envs.VLLM_DS4_PP_PYNCCL_TENSOR_DICT:
        raise RuntimeError(
            "VLLM_DS4_PP_TCP_TENSOR_DICT and "
            "VLLM_DS4_PP_PYNCCL_TENSOR_DICT cannot both be enabled."
        )
    if envs.VLLM_DS4_PP_TORCH_PG_TENSOR_DICT:
        raise RuntimeError(
            "VLLM_DS4_PP_TCP_TENSOR_DICT and "
            "VLLM_DS4_PP_TORCH_PG_TENSOR_DICT cannot both be enabled."
        )


def _can_use_bridge(group: Any) -> bool:
    return _can_use_tcp(group) or _should_cpu_stage(group)


def _init_with_ds4_tcp(self: Any, *args: Any, **kwargs: Any) -> None:
    _, envs, _ = _modules()
    group_name = _group_name_from_init(args, kwargs)
    if group_name == "pp" and envs.VLLM_DS4_PP_DISABLE_DEVICE_COMMUNICATOR:
        args, kwargs = _disable_device_communicator(args, kwargs)
    assert _ORIGINAL_INIT is not None
    _ORIGINAL_INIT(self, *args, **kwargs)
    self.ds4_pp_tcp_tensor_channel = None
    if group_name == "pp" and envs.VLLM_DS4_PP_TCP_TENSOR_DICT:
        _attach_tcp_channel(self, envs)


def _group_name_from_init(args: tuple[Any, ...], kwargs: dict[str, Any]) -> str | None:
    group_name = kwargs.get("group_name")
    if group_name is not None:
        return str(group_name)
    if len(args) >= 6 and args[5] is not None:
        return str(args[5])
    return None


def _disable_device_communicator(
    args: tuple[Any, ...], kwargs: dict[str, Any]
) -> tuple[tuple[Any, ...], dict[str, Any]]:
    if len(args) >= 4:
        rewritten = list(args)
        rewritten[3] = False
        return tuple(rewritten), kwargs
    rewritten_kwargs = dict(kwargs)
    rewritten_kwargs["use_device_communicator"] = False
    return args, rewritten_kwargs


def _attach_tcp_channel(group: Any, envs: Any) -> None:
    if int(getattr(group, "world_size", 1)) <= 1:
        return
    from ds4_vllm_runtime.pp_tcp_tensor_channel import Ds4TcpTensorChannel

    group.ds4_pp_tcp_tensor_channel = Ds4TcpTensorChannel(
        rank=group.rank,
        rank_in_group=group.rank_in_group,
        envs=envs,
        send_control=group.send_object,
        recv_control=group.recv_object,
    )


def _isend_tensor_dict(
    self: Any,
    tensor_dict: dict[str, Any],
    dst: int | None = None,
    all_gather_group: Any | None = None,
    all_gather_tensors: dict[str, bool] | None = None,
) -> list[Any]:
    if not _can_use_bridge(self):
        assert _ORIGINAL_ISEND is not None
        return _ORIGINAL_ISEND(
            self,
            tensor_dict,
            dst=dst,
            all_gather_group=all_gather_group,
            all_gather_tensors=all_gather_tensors,
        )
    dst = _resolve_dst(self, dst)
    if self.use_cpu_custom_send_recv:
        return _send_via_cpu_custom(self, tensor_dict, dst)
    parallel_state, _, torch = _modules()
    metadata_list, tensor_list = _split_tensor_dict(
        parallel_state, tensor_dict, torch, cpu_stage_cuda=_should_cpu_stage(self)
    )
    self.send_object(metadata_list, dst=dst)
    return _send_tensor_payloads(
        self, tensor_dict, tensor_list, dst, all_gather_group, all_gather_tensors, torch
    )


def _resolve_dst(group: Any, dst: int | None) -> int:
    if group.world_size <= 1:
        return 0
    if dst is None:
        dst = (group.rank_in_group + 1) % group.world_size
    assert dst < group.world_size, f"Invalid dst rank ({dst})"
    return dst


def _send_via_cpu_custom(group: Any, tensor_dict: dict[str, Any], dst: int) -> list[Any]:
    if group.device_communicator is None:
        raise ValueError("No device communicator found")
    group.device_communicator.send_tensor_dict(tensor_dict, dst)
    return []


def _should_cpu_stage(group: Any) -> bool:
    _, envs, _ = _modules()
    if not envs.VLLM_DS4_PP_CPU_STAGED_TENSOR_DICT:
        return False
    if not _is_pp_group(group) or int(getattr(group, "world_size", 1)) <= 1:
        return False
    if envs.VLLM_DS4_PP_TCP_TENSOR_DICT:
        raise RuntimeError(
            "VLLM_DS4_PP_CPU_STAGED_TENSOR_DICT and "
            "VLLM_DS4_PP_TCP_TENSOR_DICT cannot both be enabled."
        )
    if envs.VLLM_DS4_PP_PYNCCL_TENSOR_DICT:
        raise RuntimeError(
            "VLLM_DS4_PP_CPU_STAGED_TENSOR_DICT and "
            "VLLM_DS4_PP_PYNCCL_TENSOR_DICT cannot both be enabled."
        )
    return True


def _split_tensor_dict(
    parallel_state: Any,
    tensor_dict: dict[str, Any],
    torch: Any,
    *,
    cpu_stage_cuda: bool,
) -> tuple[list[tuple[str, Any]], list[Any]]:
    splitter = getattr(parallel_state, "_split_tensor_dict", None)
    if callable(splitter) and not cpu_stage_cuda:
        return splitter(tensor_dict)
    if callable(splitter) and cpu_stage_cuda:
        try:
            return splitter(tensor_dict, cpu_stage_cuda=True)
        except TypeError:
            pass
    return _split_tensor_dict_compat(parallel_state, tensor_dict, torch, cpu_stage_cuda)


def _split_tensor_dict_compat(
    parallel_state: Any,
    tensor_dict: dict[str, Any],
    torch: Any,
    cpu_stage_cuda: bool,
) -> tuple[list[tuple[str, Any]], list[Any]]:
    metadata_cls = getattr(parallel_state, "TensorMetadata", _FallbackTensorMetadata)
    staged_cls = getattr(
        parallel_state, "TensorMetadataCpuStaged", _FallbackTensorMetadataCpuStaged
    )
    metadata_list: list[tuple[str, Any]] = []
    tensor_list: list[Any] = []
    for key, value in tensor_dict.items():
        if not isinstance(value, torch.Tensor):
            metadata_list.append((key, value))
            continue
        device = value.device.type
        if cpu_stage_cuda and value.is_cuda:
            metadata_list.append((key, staged_cls(device, value.dtype, value.size())))
            tensor_list.append(value.detach().to("cpu").contiguous())
        else:
            metadata_list.append((key, metadata_cls(device, value.dtype, value.size())))
            tensor_list.append(value)
    return metadata_list, tensor_list


def _send_tensor_payloads(
    group: Any,
    tensor_dict: dict[str, Any],
    tensor_list: list[Any],
    dst: int,
    all_gather_group: Any | None,
    all_gather_tensors: dict[str, bool] | None,
    torch: Any,
) -> list[Any]:
    tensor_keys = [k for k, v in tensor_dict.items() if isinstance(v, torch.Tensor)]
    assert len(tensor_keys) == len(tensor_list)
    handles: list[Any] = []
    for key, tensor in zip(tensor_keys, tensor_list):
        handle = _send_one_tensor(
            group, key, tensor, dst, all_gather_group, all_gather_tensors, torch
        )
        if handle is not None:
            handles.append(handle)
    return handles


def _send_one_tensor(
    group: Any,
    key: str,
    tensor: Any,
    dst: int,
    all_gather_group: Any | None,
    all_gather_tensors: dict[str, bool] | None,
    torch: Any,
) -> Any | None:
    if tensor.numel() == 0:
        return None
    if _should_use_all_gather(group, key, tensor, all_gather_group, all_gather_tensors):
        size = all_gather_group.world_size
        rank = all_gather_group.rank_in_group
        tensor = tensor.reshape(size, -1)[rank]
    if tensor.is_cuda and group.ds4_pp_tcp_tensor_channel.can_handle(tensor):
        return group.ds4_pp_tcp_tensor_channel.send(tensor, dst)
    comm_group = group.cpu_group if tensor.is_cpu else group.device_group
    handle = torch.distributed.isend(tensor, dst=group.ranks[dst], group=comm_group)
    if tensor.is_cuda:
        tensor.record_stream(torch.cuda.current_stream(tensor.device))
    return handle


def _should_use_all_gather(
    group: Any,
    key: str,
    tensor: Any,
    all_gather_group: Any | None,
    all_gather_tensors: dict[str, bool] | None,
) -> bool:
    return group._should_use_all_gather(
        key, tensor.numel(), all_gather_group, all_gather_tensors
    )


def _irecv_tensor_dict(
    self: Any,
    src: int | None = None,
    all_gather_group: Any | None = None,
    all_gather_tensors: dict[str, bool] | None = None,
) -> tuple[dict[str, Any] | None, list[Any], list[Callable[[], None]]]:
    parallel_state, _, torch = _modules()
    if not _can_use_bridge(self):
        assert _ORIGINAL_IRECV is not None
        return _ORIGINAL_IRECV(
            self,
            src=src,
            all_gather_group=all_gather_group,
            all_gather_tensors=all_gather_tensors,
        )
    if not torch.distributed.is_initialized() or self.world_size == 1:
        return None, [], []
    src = _resolve_src(self, src)
    if self.use_cpu_custom_send_recv:
        return _recv_via_cpu_custom(self, src)
    return _recv_tensor_payloads(
        self, src, all_gather_group, all_gather_tensors, parallel_state, torch
    )


def _resolve_src(group: Any, src: int | None) -> int:
    if src is None:
        src = (group.rank_in_group - 1) % group.world_size
    assert src < group.world_size, f"Invalid src rank ({src})"
    return src


def _recv_via_cpu_custom(
    group: Any, src: int
) -> tuple[dict[str, Any] | None, list[Any], list[Callable[[], None]]]:
    if group.device_communicator is None:
        raise ValueError("No device communicator found")
    return group.device_communicator.recv_tensor_dict(src), [], []


def _recv_tensor_payloads(
    group: Any,
    src: int,
    all_gather_group: Any | None,
    all_gather_tensors: dict[str, bool] | None,
    parallel_state: Any,
    torch: Any,
) -> tuple[dict[str, Any], list[Any], list[Callable[[], None]]]:
    tensor_dict: dict[str, Any] = {}
    handles: list[Any] = []
    postprocess: list[Callable[[], None]] = []
    for key, value in group.recv_object(src=src):
        _recv_metadata_entry(
            group, key, value, src, all_gather_group, all_gather_tensors,
            parallel_state, torch, tensor_dict, handles, postprocess
        )
    return tensor_dict, handles, postprocess


def _recv_metadata_entry(
    group: Any,
    key: str,
    value: Any,
    src: int,
    all_gather_group: Any | None,
    all_gather_tensors: dict[str, bool] | None,
    parallel_state: Any,
    torch: Any,
    tensor_dict: dict[str, Any],
    handles: list[Any],
    postprocess: list[Callable[[], None]],
) -> None:
    metadata_kind = _tensor_metadata_kind(parallel_state, value)
    if metadata_kind is None:
        tensor_dict[key] = value
        return
    cpu_staged = metadata_kind == "cpu_staged"
    tcp_staged = metadata_kind == "tensor" and value.device == "cuda" and _can_use_tcp(group)
    stage_to_cpu = cpu_staged or tcp_staged
    target_device = _target_device(value, cpu_staged, tcp_staged)
    full_tensor = _alloc_recv_tensor(value, stage_to_cpu, torch)
    if full_tensor.numel() == 0:
        tensor_dict[key] = _maybe_to_target(full_tensor, stage_to_cpu, target_device)
        return
    if _should_use_all_gather(group, key, full_tensor, all_gather_group, all_gather_tensors):
        _recv_all_gather(group, key, full_tensor, src, all_gather_group,
                         tcp_staged, stage_to_cpu, target_device,
                         tensor_dict, handles, postprocess, torch)
    else:
        _recv_full_tensor(group, key, full_tensor, src, tcp_staged,
                          stage_to_cpu, target_device,
                          tensor_dict, handles, postprocess, torch)


def _tensor_metadata_kind(parallel_state: Any, value: Any) -> str | None:
    tensor_cls = getattr(parallel_state, "TensorMetadata", _FallbackTensorMetadata)
    staged_cls = getattr(
        parallel_state, "TensorMetadataCpuStaged", _FallbackTensorMetadataCpuStaged
    )
    if isinstance(value, staged_cls):
        return "cpu_staged"
    if isinstance(value, tensor_cls):
        return "tensor"
    return None


def _target_device(value: Any, cpu_staged: bool, tcp_staged: bool) -> Any:
    if cpu_staged:
        return value.target_device
    if tcp_staged:
        return value.device
    return "cpu"


def _alloc_recv_tensor(value: Any, stage_to_cpu: bool, torch: Any) -> Any:
    recv_device = "cpu" if stage_to_cpu else value.device
    return torch.empty(value.size, dtype=value.dtype, device=recv_device)


def _maybe_to_target(tensor: Any, stage_to_cpu: bool, target_device: Any) -> Any:
    if stage_to_cpu and str(target_device) != "cpu":
        return tensor.to(target_device)
    return tensor


def _recv_all_gather(
    group: Any,
    key: str,
    full_tensor: Any,
    src: int,
    all_gather_group: Any,
    tcp_staged: bool,
    stage_to_cpu: bool,
    target_device: Any,
    tensor_dict: dict[str, Any],
    handles: list[Any],
    postprocess: list[Callable[[], None]],
    torch: Any,
) -> None:
    orig_shape = full_tensor.shape
    slice_tensor = full_tensor.reshape(all_gather_group.world_size, -1)[
        all_gather_group.rank_in_group
    ]
    handles.append(_recv_slice(group, slice_tensor, src, tcp_staged, torch))
    postprocess.append(
        _make_all_gather_postprocess(
            key, slice_tensor, tuple(orig_shape), all_gather_group, stage_to_cpu,
            target_device, tensor_dict
        )
    )
    tensor_dict[key] = slice_tensor


def _recv_slice(group: Any, tensor: Any, src: int, tcp_staged: bool, torch: Any) -> Any:
    if tcp_staged:
        return group.ds4_pp_tcp_tensor_channel.recv(tensor, src)
    comm_group = group.cpu_group if tensor.is_cpu else group.device_group
    return torch.distributed.irecv(tensor, src=group.ranks[src], group=comm_group)


def _make_all_gather_postprocess(
    key: str,
    slice_tensor: Any,
    orig_shape: tuple[int, ...],
    all_gather_group: Any,
    stage_to_cpu: bool,
    target_device: Any,
    tensor_dict: dict[str, Any],
) -> Callable[[], None]:
    def _postprocess() -> None:
        tensor = _maybe_to_target(slice_tensor, stage_to_cpu, target_device)
        tensor_dict[key] = all_gather_group.all_gather(tensor, dim=0).reshape(orig_shape)

    return _postprocess


def _recv_full_tensor(
    group: Any,
    key: str,
    full_tensor: Any,
    src: int,
    tcp_staged: bool,
    stage_to_cpu: bool,
    target_device: Any,
    tensor_dict: dict[str, Any],
    handles: list[Any],
    postprocess: list[Callable[[], None]],
    torch: Any,
) -> None:
    handles.append(_recv_slice(group, full_tensor, src, tcp_staged, torch))
    if stage_to_cpu and str(target_device) != "cpu":
        postprocess.append(_make_target_postprocess(key, full_tensor, target_device, tensor_dict))
    tensor_dict[key] = full_tensor


def _make_target_postprocess(
    key: str,
    full_tensor: Any,
    target_device: Any,
    tensor_dict: dict[str, Any],
) -> Callable[[], None]:
    def _postprocess() -> None:
        tensor_dict[key] = full_tensor.to(target_device)

    return _postprocess
