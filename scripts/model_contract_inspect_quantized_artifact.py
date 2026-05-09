#!/usr/bin/env python3

from collections import Counter
import json
import struct
import sys
from argparse import ArgumentParser
from dataclasses import dataclass
from pathlib import Path
from typing import Any, BinaryIO


@dataclass(frozen=True)
class InspectResult:
	path: str
	artifact_type: str
	tensor_count: int
	tensor_type_counts: dict[str, int]
	mtp_present: bool
	mtp_tensor_count: int
	mtp_tensor_type_counts: dict[str, int]
	mtp_layer_ids: list[int]
	first_mtp_keys: list[str]


def load_json(path: Path) -> Any:
	with path.open("r", encoding="utf-8") as f:
		return json.load(f)


def read_u32_le(f: BinaryIO) -> int:
	b = f.read(4)
	if len(b) != 4:
		raise EOFError("unexpected EOF reading u32")
	return int(struct.unpack("<I", b)[0])


def read_u64_le(f: BinaryIO) -> int:
	b = f.read(8)
	if len(b) != 8:
		raise EOFError("unexpected EOF reading u64")
	return int(struct.unpack("<Q", b)[0])


def read_bytes(f: BinaryIO, n: int) -> bytes:
	b = f.read(n)
	if len(b) != n:
		raise EOFError(f"unexpected EOF reading {n} bytes")
	return b


def read_gguf_string(f: BinaryIO) -> str:
	n = read_u32_le(f)
	b = read_bytes(f, n)
	try:
		return b.decode("utf-8")
	except UnicodeDecodeError:
		return b.decode("utf-8", errors="replace")


def skip_gguf_value(f: BinaryIO, value_type: int) -> None:
	# Types follow gguf spec: https://github.com/ggerganov/ggml/blob/master/docs/gguf.md
	if value_type in (0, 1, 7):  # u8, i8, bool
		read_bytes(f, 1)
		return
	if value_type in (2, 3):  # u16, i16
		read_bytes(f, 2)
		return
	if value_type in (4, 5, 6):  # u32, i32, f32
		read_bytes(f, 4)
		return
	if value_type in (10, 11, 12):  # u64, i64, f64
		read_bytes(f, 8)
		return
	if value_type == 8:  # string
		_ = read_gguf_string(f)
		return
	if value_type == 9:  # array
		elem_type = read_u32_le(f)
		n = read_u64_le(f)
		for _ in range(int(n)):
			skip_gguf_value(f, int(elem_type))
		return
	raise ValueError(f"unsupported gguf value_type={value_type}")


def inspect_weight_keys(weight_keys: list[str], path: str, artifact_type: str) -> InspectResult:
	mtp_keys = [k for k in weight_keys if k.startswith("mtp.")]
	mtp_layer_ids = set()
	for k in mtp_keys:
		parts = k.split(".", 2)
		if len(parts) < 2:
			continue
		try:
			mtp_layer_ids.add(int(parts[1]))
		except ValueError:
			continue
	return InspectResult(
		path=path,
		artifact_type=artifact_type,
		tensor_count=len(weight_keys),
		tensor_type_counts={},
		mtp_present=bool(mtp_keys),
		mtp_tensor_count=len(mtp_keys),
		mtp_tensor_type_counts={},
		mtp_layer_ids=sorted(mtp_layer_ids),
		first_mtp_keys=mtp_keys[:10],
	)


def inspect_safetensors_index(path: Path) -> InspectResult:
	data = load_json(path)
	weight_map = data.get("weight_map", None)
	if not isinstance(weight_map, dict):
		raise ValueError(f"{path} does not look like a safetensors index JSON (missing weight_map object)")
	return inspect_weight_keys(sorted(weight_map.keys()), str(path), "safetensors.index.json")


def inspect_gguf(path: Path) -> InspectResult:
	# Types follow gguf spec (ggml_type):
	# https://github.com/ggml-org/ggml/blob/master/docs/gguf.md
	#
	# This mapping is intentionally partial/stable: unknown types are emitted as "TYPE_<code>".
	ggml_type_names: dict[int, str] = {
		0: "F32",
		1: "F16",
		2: "Q4_0",
		3: "Q4_1",
		6: "Q5_0",
		7: "Q5_1",
		8: "Q8_0",
		9: "Q8_1",
		10: "Q2_K",
		11: "Q3_K",
		12: "Q4_K",
		13: "Q5_K",
		14: "Q6_K",
		15: "Q8_K",
		16: "IQ2_XXS",
		17: "IQ2_XS",
		18: "IQ3_XXS",
		19: "IQ1_S",
		20: "IQ4_NL",
		21: "IQ3_S",
		22: "IQ2_S",
		23: "IQ4_XS",
		24: "I8",
		25: "I16",
		26: "I32",
		27: "I64",
		28: "F64",
		29: "IQ1_M",
		30: "BF16",
		34: "TQ1_0",
		35: "TQ2_0",
		39: "MXFP4",
	}

	def ggml_type_name(code: int) -> str:
		return ggml_type_names.get(code, f"TYPE_{code}")

	with path.open("rb") as f:
		magic = read_bytes(f, 4)
		if magic != b"GGUF":
			raise ValueError(f"{path} does not look like a GGUF file (bad magic {magic!r})")
		_vers = read_u32_le(f)
		n_tensors = read_u64_le(f)
		n_kv = read_u64_le(f)

		for _ in range(int(n_kv)):
			_ = read_gguf_string(f)
			vtype = read_u32_le(f)
			skip_gguf_value(f, int(vtype))

		weight_keys: list[str] = []
		weight_types: list[int] = []
		for _ in range(int(n_tensors)):
			name = read_gguf_string(f)
			nd = read_u32_le(f)
			for _ in range(int(nd)):
				_ = read_u64_le(f)
			tensor_type = read_u32_le(f)  # ggml_type
			_ = read_u64_le(f)  # offset
			weight_keys.append(name)
			weight_types.append(int(tensor_type))

	type_counts = Counter(ggml_type_name(t) for t in weight_types)
	mtp_type_counts = Counter(ggml_type_name(t) for k, t in zip(weight_keys, weight_types) if k.startswith("mtp."))
	res = inspect_weight_keys(weight_keys, str(path), "gguf")
	return InspectResult(
		path=res.path,
		artifact_type=res.artifact_type,
		tensor_count=res.tensor_count,
		tensor_type_counts=dict(sorted(type_counts.items())),
		mtp_present=res.mtp_present,
		mtp_tensor_count=res.mtp_tensor_count,
		mtp_tensor_type_counts=dict(sorted(mtp_type_counts.items())),
		mtp_layer_ids=res.mtp_layer_ids,
		first_mtp_keys=res.first_mtp_keys,
	)


def detect_and_inspect(path: Path) -> InspectResult:
	if path.is_dir():
		idx = path / "model.safetensors.index.json"
		if idx.exists():
			return inspect_safetensors_index(idx)
		raise ValueError(f"{path} is a directory but does not contain model.safetensors.index.json")
	if path.suffix.lower() == ".gguf":
		return inspect_gguf(path)
	if path.name.endswith(".safetensors.index.json") or path.name == "model.safetensors.index.json" or path.suffix.lower() == ".json":
		return inspect_safetensors_index(path)
	raise ValueError(f"unrecognized artifact type for {path} (expected .gguf or model.safetensors.index.json)")


def main() -> int:
	parser = ArgumentParser()
	parser.add_argument("--path", type=str, required=True, help="Quantized artifact path: .gguf, model.safetensors.index.json, or a directory containing it.")
	parser.add_argument("--json", action="store_true", help="Emit machine-readable JSON output.")
	parser.add_argument("--require-mtp", action="store_true", help="Exit non-zero if no mtp.* tensors are present.")
	args = parser.parse_args()

	try:
		res = detect_and_inspect(Path(args.path))
	except Exception as e:
		print(f"ERROR: {e}")
		return 2

	if args.json:
		print(
			json.dumps(
				{
					"path": res.path,
					"artifact_type": res.artifact_type,
					"tensor_count": res.tensor_count,
					"tensor_type_counts": res.tensor_type_counts,
					"mtp_present": res.mtp_present,
					"mtp_tensor_count": res.mtp_tensor_count,
					"mtp_tensor_type_counts": res.mtp_tensor_type_counts,
					"mtp_layer_ids": res.mtp_layer_ids,
					"first_mtp_keys": res.first_mtp_keys,
				},
				indent=2,
				sort_keys=True,
			)
		)
	else:
		print(f"path: {res.path}")
		print(f"artifact_type: {res.artifact_type}")
		print(f"tensor_count: {res.tensor_count}")
		if res.tensor_type_counts:
			for k in sorted(res.tensor_type_counts.keys()):
				print(f"tensor_type_count: {k}={res.tensor_type_counts[k]}")
		print(f"mtp_present: {str(res.mtp_present).lower()}")
		print(f"mtp_tensor_count: {res.mtp_tensor_count}")
		if res.mtp_tensor_type_counts:
			for k in sorted(res.mtp_tensor_type_counts.keys()):
				print(f"mtp_tensor_type_count: {k}={res.mtp_tensor_type_counts[k]}")
		print(f"mtp_layer_ids: {res.mtp_layer_ids}")
		for k in res.first_mtp_keys:
			print(f"mtp_key: {k}")

	if args.require_mtp and not res.mtp_present:
		return 1
	return 0


if __name__ == "__main__":
	raise SystemExit(main())
