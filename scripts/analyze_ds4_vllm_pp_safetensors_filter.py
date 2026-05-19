#!/usr/bin/env python3
"""Analyze DeepSeek-V4 safetensors bytes that PP ranks can skip before tensor load."""

from __future__ import annotations

import argparse
import copy
import hashlib
import json
import re
import struct
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable


FORMAT = "ds4-vllm-pp-safetensors-filter-v1"
HASH_FIELDS = {"artifact_sha256", "artifact_hash"}
LAYER_RE = re.compile(r"(?:^|\.)model\.layers\.(\d+)\.")
DTYPE_BYTES = {
    "BOOL": 1,
    "BF16": 2,
    "F16": 2,
    "F32": 4,
    "F64": 8,
    "F8_E4M3": 1,
    "F8_E5M2": 1,
    "F8_E8M0": 1,
    "I8": 1,
    "I16": 2,
    "I32": 4,
    "I64": 8,
    "U8": 1,
    "U16": 2,
    "U32": 4,
    "U64": 8,
}


@dataclass(frozen=True)
class TensorInfo:
    file_name: str
    name: str
    mapped_name: str
    nbytes: int


def canonical_hash(obj: dict[str, Any]) -> str:
    payload = copy.deepcopy(obj)
    for field in HASH_FIELDS:
        payload.pop(field, None)
    data = json.dumps(payload, sort_keys=True, separators=(",", ":"), ensure_ascii=True).encode("utf-8")
    return hashlib.sha256(data).hexdigest()


def add_artifact_hash(obj: dict[str, Any]) -> dict[str, Any]:
    digest = canonical_hash(obj)
    obj["artifact_sha256"] = digest
    obj["artifact_hash"] = digest
    return obj


def parse_pp_partition(raw: str) -> list[int]:
    parts: list[int] = []
    for item in raw.split(","):
        token = item.strip()
        if token == "":
            continue
        try:
            count = int(token)
        except ValueError as exc:
            raise ValueError(f"invalid PP partition component: {token}") from exc
        if count <= 0:
            raise ValueError("PP partition components must be positive")
        parts.append(count)
    if len(parts) == 0:
        raise ValueError("PP partition must not be empty")
    return parts


def partition_ranges(partition: list[int]) -> list[tuple[int, int]]:
    ranges: list[tuple[int, int]] = []
    start = 0
    for count in partition:
        end = start + count
        ranges.append((start, end))
        start = end
    return ranges


def map_deepseek_v4_weight_name(name: str) -> str:
    mapped = name
    if mapped.startswith(("layers.", "embed.", "norm.", "hc_head", "mtp.")):
        mapped = "model." + mapped
    mapped = mapped.replace(".attn.compressor.", ".attn.mla_attn.compressor.")
    mapped = mapped.replace(".shared_experts.w2", ".shared_experts.down_proj")
    mapped = re.sub(r"(\.experts\.\d+\.w[123])\.scale$", r"\1.weight_scale", mapped)
    mapped = re.sub(r"\.scale$", ".weight_scale_inv", mapped)
    if mapped.endswith("head.weight"):
        mapped = mapped[: -len("head.weight")] + "lm_head.weight"
    if mapped.endswith("embed.weight"):
        mapped = mapped[: -len("embed.weight")] + "embed_tokens.weight"
    mapped = mapped.replace(".ffn.gate.bias", ".ffn.gate.e_score_correction_bias")
    return mapped


def tensor_nbytes(name: str, meta: dict[str, Any]) -> int:
    offsets = meta.get("data_offsets")
    if (
        isinstance(offsets, list)
        and len(offsets) == 2
        and isinstance(offsets[0], int)
        and isinstance(offsets[1], int)
        and offsets[1] >= offsets[0]
    ):
        return offsets[1] - offsets[0]
    dtype = str(meta.get("dtype", ""))
    elem_bytes = DTYPE_BYTES.get(dtype)
    if elem_bytes is None:
        raise ValueError(f"{name}: unknown dtype {dtype}")
    shape = meta.get("shape")
    if not isinstance(shape, list):
        raise ValueError(f"{name}: missing tensor shape")
    count = 1
    for dim in shape:
        if not isinstance(dim, int) or dim < 0:
            raise ValueError(f"{name}: invalid shape dimension {dim!r}")
        count *= dim
    return count * elem_bytes


def read_safetensors_header(path: Path) -> dict[str, Any]:
    with path.open("rb") as f:
        raw_len = f.read(8)
        if len(raw_len) != 8:
            raise ValueError(f"{path}: missing safetensors header length")
        header_len = struct.unpack("<Q", raw_len)[0]
        if header_len <= 0:
            raise ValueError(f"{path}: invalid safetensors header length {header_len}")
        header = f.read(header_len)
        if len(header) != header_len:
            raise ValueError(f"{path}: truncated safetensors header")
    obj = json.loads(header.decode("utf-8"))
    if not isinstance(obj, dict):
        raise ValueError(f"{path}: safetensors header must be an object")
    return obj


def iter_tensors(model_dir: Path, pattern: str) -> Iterable[TensorInfo]:
    for path in sorted(model_dir.glob(pattern)):
        header = read_safetensors_header(path)
        for name, meta in header.items():
            if name == "__metadata__":
                continue
            if not isinstance(meta, dict):
                raise ValueError(f"{path}:{name}: tensor metadata must be an object")
            yield TensorInfo(
                file_name=path.name,
                name=name,
                mapped_name=map_deepseek_v4_weight_name(name),
                nbytes=tensor_nbytes(name, meta),
            )


def _empty_rank_stat(rank: int, layer_range: tuple[int, int], total: int) -> dict[str, Any]:
    start, end = layer_range
    return {
        "rank": rank,
        "layer_start": start,
        "layer_end_exclusive": end,
        "total_seen_bytes": total,
        "total_seen_gib": total / (1024**3),
        "local_layer_bytes": 0,
        "local_layer_tensors": 0,
        "skipped_layer_bytes": 0,
        "skipped_layer_tensors": 0,
        "mtp_skipped_bytes": 0,
        "mtp_skipped_tensors": 0,
        "global_or_rank_specific_bytes": 0,
        "global_or_rank_specific_tensors": 0,
    }


def _add_category(stat: dict[str, Any], prefix: str, nbytes: int) -> None:
    stat[f"{prefix}_bytes"] += nbytes
    stat[f"{prefix}_tensors"] += 1


def analyze_tensors(
    tensors: list[TensorInfo],
    pp_partition: list[int],
    *,
    run_id: str,
    checked_at: str,
    model_dir: str,
    model_id: str,
    source_command: str,
) -> dict[str, Any]:
    total = sum(item.nbytes for item in tensors)
    ranges = partition_ranges(pp_partition)
    stats = [_empty_rank_stat(rank, layer_range, total) for rank, layer_range in enumerate(ranges)]
    for item in tensors:
        is_mtp = item.name.startswith("mtp.") or item.mapped_name.startswith("model.mtp.")
        layer_match = LAYER_RE.search(item.mapped_name)
        for stat in stats:
            if is_mtp:
                _add_category(stat, "mtp_skipped", item.nbytes)
            elif layer_match is not None:
                layer = int(layer_match.group(1))
                if stat["layer_start"] <= layer < stat["layer_end_exclusive"]:
                    _add_category(stat, "local_layer", item.nbytes)
                else:
                    _add_category(stat, "skipped_layer", item.nbytes)
            else:
                _add_category(stat, "global_or_rank_specific", item.nbytes)
    for stat in stats:
        without_filter = stat["total_seen_bytes"]
        with_filter = stat["local_layer_bytes"] + stat["global_or_rank_specific_bytes"]
        avoidable = stat["skipped_layer_bytes"] + stat["mtp_skipped_bytes"]
        stat["candidate_materialized_bytes_without_filter"] = without_filter
        stat["candidate_materialized_gib_without_filter"] = without_filter / (1024**3)
        stat["candidate_materialized_bytes_with_early_filter_floor"] = with_filter
        stat["candidate_materialized_gib_with_early_filter_floor"] = with_filter / (1024**3)
        stat["avoidable_tensor_load_bytes_floor"] = avoidable
        stat["avoidable_tensor_load_gib_floor"] = avoidable / (1024**3)
        stat["avoidable_fraction_floor"] = avoidable / without_filter if without_filter > 0 else 0.0
    artifact = {
        "format": FORMAT,
        "artifact_sha256": "",
        "artifact_hash": "",
        "run_id": run_id,
        "checked_at": checked_at,
        "model_id": model_id,
        "model_dir": model_dir,
        "source_command": source_command,
        "checkpoint_bytes": total,
        "checkpoint_gib": total / (1024**3),
        "files": len({item.file_name for item in tensors}),
        "tensor_count": len(tensors),
        "pp_partition": pp_partition,
        "layer_ranges": [{"rank": i, "start": start, "end_exclusive": end} for i, (start, end) in enumerate(ranges)],
        "current_iterator_materializes_before_pp_skip": True,
        "early_filter_can_skip_before_tensor_load": True,
        "skip_is_conservative_floor": True,
        "rank_stats": stats,
        "recommended_patch": {
            "vllm_files": [
                "vllm/model_executor/model_loader/weight_utils.py",
                "vllm/model_executor/model_loader/default_loader.py",
                "vllm/model_executor/models/deepseek_v4.py",
            ],
            "summary": "Pass a raw weight-name predicate into safetensors_weights_iterator and let DeepseekV4ForCausalLM reject PP-missing layers and MTP tensors before f.get_tensor(name).",
        },
    }
    return add_artifact_hash(artifact)


def build_artifact(args: argparse.Namespace) -> dict[str, Any]:
    model_dir = Path(args.model_dir)
    tensors = list(iter_tensors(model_dir, args.pattern))
    if len(tensors) == 0:
        raise ValueError(f"no safetensors matched {model_dir / args.pattern}")
    return analyze_tensors(
        tensors,
        parse_pp_partition(args.pp_partition),
        run_id=args.run_id,
        checked_at=args.checked_at,
        model_dir=str(model_dir),
        model_id=args.model_id,
        source_command=args.source_command,
    )


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--model-dir", required=True)
    parser.add_argument("--pp-partition", required=True, help="Comma-separated layer counts, e.g. 14,15,14")
    parser.add_argument("--model-id", default="deepseek-ai/DeepSeek-V4-Flash")
    parser.add_argument("--pattern", default="*.safetensors")
    parser.add_argument("--run-id", default="ds4-vllm-pp-safetensors-filter")
    parser.add_argument("--checked-at", default=datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"))
    parser.add_argument("--source-command", default="")
    parser.add_argument("--output")
    args = parser.parse_args()
    artifact = build_artifact(args)
    data = json.dumps(artifact, indent=2, sort_keys=True) + "\n"
    if args.output:
        Path(args.output).write_text(data, encoding="utf-8")
    else:
        print(data, end="")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
