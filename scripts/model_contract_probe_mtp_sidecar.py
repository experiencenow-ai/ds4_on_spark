#!/usr/bin/env python3

import json
import struct
import sys
from argparse import ArgumentParser
from dataclasses import dataclass
from pathlib import Path
from typing import Any, BinaryIO, Optional


@dataclass(frozen=True)
class TensorDesc:
	name: str
	ndim: int
	dims: list[int]
	ggml_type: int
	rel_offset: int


def read_bytes(f: BinaryIO, n: int) -> bytes:
	b = f.read(n)
	if len(b) != n:
		raise EOFError(f"unexpected EOF reading {n} bytes")
	return b


def read_u32_le(f: BinaryIO) -> int:
	return int(struct.unpack("<I", read_bytes(f, 4))[0])


def read_u64_le(f: BinaryIO) -> int:
	return int(struct.unpack("<Q", read_bytes(f, 8))[0])


def read_i8(f: BinaryIO) -> int:
	return int(struct.unpack("<b", read_bytes(f, 1))[0])


def read_u8(f: BinaryIO) -> int:
	return int(struct.unpack("<B", read_bytes(f, 1))[0])


def read_i16_le(f: BinaryIO) -> int:
	return int(struct.unpack("<h", read_bytes(f, 2))[0])


def read_u16_le(f: BinaryIO) -> int:
	return int(struct.unpack("<H", read_bytes(f, 2))[0])


def read_i32_le(f: BinaryIO) -> int:
	return int(struct.unpack("<i", read_bytes(f, 4))[0])


def read_i64_le(f: BinaryIO) -> int:
	return int(struct.unpack("<q", read_bytes(f, 8))[0])


def read_f32_le(f: BinaryIO) -> float:
	return float(struct.unpack("<f", read_bytes(f, 4))[0])


def read_f64_le(f: BinaryIO) -> float:
	return float(struct.unpack("<d", read_bytes(f, 8))[0])


def read_gguf_string(f: BinaryIO) -> str:
	n = read_u32_le(f)
	b = read_bytes(f, n)
	try:
		return b.decode("utf-8")
	except UnicodeDecodeError:
		return b.decode("utf-8", errors="replace")


def skip_gguf_value(f: BinaryIO, value_type: int) -> None:
	# Types follow gguf spec: https://github.com/ggml-org/ggml/blob/master/docs/gguf.md
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


def read_gguf_value(f: BinaryIO, value_type: int) -> Any:
	# Values follow gguf spec: https://github.com/ggml-org/ggml/blob/master/docs/gguf.md
	if value_type == 0:
		return read_u8(f)
	if value_type == 1:
		return read_i8(f)
	if value_type == 2:
		return read_u16_le(f)
	if value_type == 3:
		return read_i16_le(f)
	if value_type == 4:
		return read_u32_le(f)
	if value_type == 5:
		return read_i32_le(f)
	if value_type == 6:
		return read_f32_le(f)
	if value_type == 7:
		return (read_u8(f) != 0)
	if value_type == 8:
		return read_gguf_string(f)
	if value_type == 10:
		return read_u64_le(f)
	if value_type == 11:
		return read_i64_le(f)
	if value_type == 12:
		return read_f64_le(f)
	if value_type == 9:
		skip_gguf_value(f, value_type)
		return "<array omitted>"
	raise ValueError(f"unsupported gguf value_type={value_type}")


def parse_gguf(path: Path) -> tuple[int, dict[str, Any], list[TensorDesc]]:
	with path.open("rb") as f:
		magic = read_bytes(f, 4)
		if magic != b"GGUF":
			raise ValueError(f"{path} does not look like a GGUF file (bad magic {magic!r})")
		version = read_u32_le(f)
		n_tensors = read_u64_le(f)
		n_kv = read_u64_le(f)

		metadata: dict[str, Any] = {"_n_tensors": int(n_tensors), "_n_kv": int(n_kv)}
		for _ in range(int(n_kv)):
			key = read_gguf_string(f)
			vtype = read_u32_le(f)
			if vtype == 9:
				skip_gguf_value(f, int(vtype))
				continue
			if key == "general.architecture" or key.startswith("deepseek4."):
				metadata[key] = read_gguf_value(f, int(vtype))
			else:
				skip_gguf_value(f, int(vtype))

		tensors: list[TensorDesc] = []
		for _ in range(int(n_tensors)):
			name = read_gguf_string(f)
			ndim = int(read_u32_le(f))
			dims = [int(read_u64_le(f)) for _ in range(ndim)]
			ggml_type = int(read_u32_le(f))
			rel_offset = int(read_u64_le(f))
			tensors.append(TensorDesc(name=name, ndim=ndim, dims=dims, ggml_type=ggml_type, rel_offset=rel_offset))
	return (int(version), metadata, tensors)


GGML_TYPE_NAMES: dict[int, str] = {
	0: "F32",
	1: "F16",
	8: "Q8_0",
	10: "Q2_K",
	12: "Q4_K",
	16: "IQ2_XXS",
	26: "I32",
}


def ggml_type_name(code: int) -> str:
	return GGML_TYPE_NAMES.get(code, f"TYPE_{code}")


def must_u32(meta: dict[str, Any], key: str) -> int:
	v = meta.get(key, None)
	if v is None:
		raise KeyError(key)
	try:
		return int(v)
	except Exception as e:
		raise ValueError(f"metadata {key} is not an int: {v!r}") from e


def expect_tensor(
	errors: list[str],
	name: str,
	t: Optional[TensorDesc],
	want_types: set[int],
	want_ndim: int,
	want_dims: list[int],
) -> None:
	if t is None:
		errors.append(f"missing tensor: {name}")
		return
	if t.ggml_type not in want_types:
		errors.append(
			f"tensor {name} has type {ggml_type_name(t.ggml_type)} ({t.ggml_type}), expected one of {[ggml_type_name(x) for x in sorted(want_types)]}"
		)
	if t.ndim != want_ndim:
		errors.append(f"tensor {name} has ndim={t.ndim}, expected {want_ndim}")
		return
	if t.dims != want_dims:
		errors.append(f"tensor {name} has dims={t.dims}, expected {want_dims}")


def main() -> int:
	parser = ArgumentParser()
	parser.add_argument("--path", type=str, required=True, help="Path to MTP sidecar GGUF (DeepSeek4 MTP support).")
	parser.add_argument("--json", action="store_true", help="Emit machine-readable JSON output.")
	args = parser.parse_args()

	path = Path(args.path)
	version, meta, tensors = parse_gguf(path)

	out: dict[str, Any] = {
		"path": str(path),
		"gguf_version": int(version),
		"metadata": {k: meta[k] for k in sorted(meta.keys()) if not k.startswith("_")},
		"tensor_count": len(tensors),
		"architecture": meta.get("general.architecture", None),
	}

	errors: list[str] = []
	if version != 3:
		errors.append(f"gguf version is {version}, expected 3")
	if meta.get("general.architecture", None) != "deepseek4_mtp_support":
		errors.append(f"general.architecture is {meta.get('general.architecture', None)!r}, expected 'deepseek4_mtp_support'")

	expected_names = [
		"mtp.0.hc_head_base.weight",
		"mtp.0.hc_head_fn.weight",
		"mtp.0.hc_head_scale.weight",
		"mtp.0.e_proj.weight",
		"mtp.0.h_proj.weight",
		"mtp.0.enorm.weight",
		"mtp.0.hnorm.weight",
		"mtp.0.norm.weight",
		"mtp.0.hc_attn_fn.weight",
		"mtp.0.hc_attn_scale.weight",
		"mtp.0.hc_attn_base.weight",
		"mtp.0.attn_norm.weight",
		"mtp.0.attn_q_a.weight",
		"mtp.0.attn_q_a_norm.weight",
		"mtp.0.attn_q_b.weight",
		"mtp.0.attn_kv.weight",
		"mtp.0.attn_kv_a_norm.weight",
		"mtp.0.attn_sinks.weight",
		"mtp.0.attn_output_a.weight",
		"mtp.0.attn_output_b.weight",
		"mtp.0.hc_ffn_fn.weight",
		"mtp.0.hc_ffn_scale.weight",
		"mtp.0.hc_ffn_base.weight",
		"mtp.0.ffn_norm.weight",
		"mtp.0.ffn_gate_inp.weight",
		"mtp.0.exp_probs_b.bias",
		"mtp.0.ffn_gate_exps.weight",
		"mtp.0.ffn_up_exps.weight",
		"mtp.0.ffn_down_exps.weight",
		"mtp.0.ffn_gate_shexp.weight",
		"mtp.0.ffn_up_shexp.weight",
		"mtp.0.ffn_down_shexp.weight",
	]
	expected_set = set(expected_names)
	got_names = [t.name for t in tensors]
	got_set = set(got_names)
	missing = sorted(expected_set - got_set)
	extra = sorted(got_set - expected_set)
	out["missing_tensors"] = missing
	out["extra_tensors"] = extra
	if len(tensors) != len(expected_names):
		errors.append(f"tensor_count is {len(tensors)}, expected {len(expected_names)}")
	if missing:
		errors.append(f"missing {len(missing)} expected tensor(s)")
	if extra:
		errors.append(f"found {len(extra)} unexpected tensor(s)")
	if any(not n.startswith("mtp.0.") for n in got_names):
		errors.append("found tensor names outside mtp.0.* namespace")

	tmap = {t.name: t for t in tensors}
	try:
		n_embd = must_u32(meta, "deepseek4.embedding_length")
		n_head = must_u32(meta, "deepseek4.attention.head_count")
		n_head_dim = must_u32(meta, "deepseek4.attention.key_length")
		n_lora_q = must_u32(meta, "deepseek4.attention.q_lora_rank")
		n_lora_o = must_u32(meta, "deepseek4.attention.output_lora_rank")
		n_out_group = must_u32(meta, "deepseek4.attention.output_group_count")
		n_expert = must_u32(meta, "deepseek4.expert_count")
		n_ff_exp = must_u32(meta, "deepseek4.expert_feed_forward_length")
		n_hc = must_u32(meta, "deepseek4.hyper_connection.count")
	except KeyError as e:
		errors.append(f"missing required metadata key: {e.args[0]}")
		n_embd = n_head = n_head_dim = n_lora_q = n_lora_o = n_out_group = n_expert = n_ff_exp = n_hc = 0

	if n_embd and n_head and n_head_dim and n_lora_q and n_lora_o and n_out_group and n_expert and n_ff_exp and n_hc:
		hc_dim = n_embd * n_hc
		hc_mix_dim = (2 * n_hc) + (n_hc * n_hc)
		q_dim = n_head * n_head_dim
		out_low_dim = n_out_group * n_lora_o
		out_a_dim0 = n_head_dim * (n_head // n_out_group if n_out_group else 0)

		PLAIN = {0, 1}
		F32 = {0}
		Q8_0 = {8}
		ROUTED = {10, 12, 16}

		expect_tensor(errors, "mtp.0.hc_head_base.weight", tmap.get("mtp.0.hc_head_base.weight"), F32, 1, [n_hc])
		expect_tensor(errors, "mtp.0.hc_head_fn.weight", tmap.get("mtp.0.hc_head_fn.weight"), PLAIN, 2, [hc_dim, n_hc])
		expect_tensor(errors, "mtp.0.hc_head_scale.weight", tmap.get("mtp.0.hc_head_scale.weight"), F32, 1, [1])
		expect_tensor(errors, "mtp.0.e_proj.weight", tmap.get("mtp.0.e_proj.weight"), Q8_0, 2, [n_embd, n_embd])
		expect_tensor(errors, "mtp.0.h_proj.weight", tmap.get("mtp.0.h_proj.weight"), Q8_0, 2, [n_embd, n_embd])
		expect_tensor(errors, "mtp.0.enorm.weight", tmap.get("mtp.0.enorm.weight"), F32, 1, [n_embd])
		expect_tensor(errors, "mtp.0.hnorm.weight", tmap.get("mtp.0.hnorm.weight"), F32, 1, [n_embd])
		expect_tensor(errors, "mtp.0.norm.weight", tmap.get("mtp.0.norm.weight"), F32, 1, [n_embd])

		expect_tensor(errors, "mtp.0.hc_attn_fn.weight", tmap.get("mtp.0.hc_attn_fn.weight"), PLAIN, 2, [hc_dim, hc_mix_dim])
		expect_tensor(errors, "mtp.0.hc_attn_scale.weight", tmap.get("mtp.0.hc_attn_scale.weight"), F32, 1, [3])
		expect_tensor(errors, "mtp.0.hc_attn_base.weight", tmap.get("mtp.0.hc_attn_base.weight"), F32, 1, [hc_mix_dim])
		expect_tensor(errors, "mtp.0.attn_norm.weight", tmap.get("mtp.0.attn_norm.weight"), F32, 1, [n_embd])
		expect_tensor(errors, "mtp.0.attn_q_a.weight", tmap.get("mtp.0.attn_q_a.weight"), Q8_0, 2, [n_embd, n_lora_q])
		expect_tensor(errors, "mtp.0.attn_q_a_norm.weight", tmap.get("mtp.0.attn_q_a_norm.weight"), F32, 1, [n_lora_q])
		expect_tensor(errors, "mtp.0.attn_q_b.weight", tmap.get("mtp.0.attn_q_b.weight"), Q8_0, 2, [n_lora_q, q_dim])
		expect_tensor(errors, "mtp.0.attn_kv.weight", tmap.get("mtp.0.attn_kv.weight"), Q8_0, 2, [n_embd, n_head_dim])
		expect_tensor(errors, "mtp.0.attn_kv_a_norm.weight", tmap.get("mtp.0.attn_kv_a_norm.weight"), F32, 1, [n_head_dim])
		expect_tensor(errors, "mtp.0.attn_sinks.weight", tmap.get("mtp.0.attn_sinks.weight"), F32, 1, [n_head])
		expect_tensor(errors, "mtp.0.attn_output_a.weight", tmap.get("mtp.0.attn_output_a.weight"), Q8_0, 2, [out_a_dim0, out_low_dim])
		expect_tensor(errors, "mtp.0.attn_output_b.weight", tmap.get("mtp.0.attn_output_b.weight"), Q8_0, 2, [out_low_dim, n_embd])

		expect_tensor(errors, "mtp.0.hc_ffn_fn.weight", tmap.get("mtp.0.hc_ffn_fn.weight"), PLAIN, 2, [hc_dim, hc_mix_dim])
		expect_tensor(errors, "mtp.0.hc_ffn_scale.weight", tmap.get("mtp.0.hc_ffn_scale.weight"), F32, 1, [3])
		expect_tensor(errors, "mtp.0.hc_ffn_base.weight", tmap.get("mtp.0.hc_ffn_base.weight"), F32, 1, [hc_mix_dim])
		expect_tensor(errors, "mtp.0.ffn_norm.weight", tmap.get("mtp.0.ffn_norm.weight"), F32, 1, [n_embd])
		expect_tensor(errors, "mtp.0.ffn_gate_inp.weight", tmap.get("mtp.0.ffn_gate_inp.weight"), PLAIN, 2, [n_embd, n_expert])
		expect_tensor(errors, "mtp.0.exp_probs_b.bias", tmap.get("mtp.0.exp_probs_b.bias"), F32, 1, [n_expert])
		expect_tensor(errors, "mtp.0.ffn_gate_exps.weight", tmap.get("mtp.0.ffn_gate_exps.weight"), ROUTED, 3, [n_embd, n_ff_exp, n_expert])
		expect_tensor(errors, "mtp.0.ffn_up_exps.weight", tmap.get("mtp.0.ffn_up_exps.weight"), ROUTED, 3, [n_embd, n_ff_exp, n_expert])
		expect_tensor(errors, "mtp.0.ffn_down_exps.weight", tmap.get("mtp.0.ffn_down_exps.weight"), ROUTED, 3, [n_ff_exp, n_embd, n_expert])
		expect_tensor(errors, "mtp.0.ffn_gate_shexp.weight", tmap.get("mtp.0.ffn_gate_shexp.weight"), Q8_0, 2, [n_embd, n_ff_exp])
		expect_tensor(errors, "mtp.0.ffn_up_shexp.weight", tmap.get("mtp.0.ffn_up_shexp.weight"), Q8_0, 2, [n_embd, n_ff_exp])
		expect_tensor(errors, "mtp.0.ffn_down_shexp.weight", tmap.get("mtp.0.ffn_down_shexp.weight"), Q8_0, 2, [n_ff_exp, n_embd])

	out["ok"] = (len(errors) == 0)
	out["errors"] = errors

	if args.json:
		print(json.dumps(out, indent=2, sort_keys=True))
	else:
		print(f"path: {out['path']}")
		print(f"gguf_version: {out['gguf_version']}")
		print(f"general.architecture: {out['architecture']}")
		print(f"tensor_count: {out['tensor_count']}")
		for k in sorted(out["metadata"].keys()):
			print(f"metadata: {k}={out['metadata'][k]}")
		if missing:
			for n in missing[:32]:
				print(f"missing_tensor: {n}")
		if extra:
			for n in extra[:32]:
				print(f"extra_tensor: {n}")
		for e in errors[:64]:
			print(f"error: {e}")
		print(f"ok: {str(bool(out['ok'])).lower()}")

	return 0 if out["ok"] else 1


if __name__ == "__main__":
	sys.exit(main())
