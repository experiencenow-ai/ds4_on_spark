#!/usr/bin/env python3

import io
import json
import struct
import sys
from argparse import ArgumentParser
from dataclasses import dataclass
from pathlib import Path
from typing import Any, BinaryIO, Optional
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

if __package__ in (None, ""):
	sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from scripts._lib.model_contract import read_bytes


@dataclass(frozen=True)
class TensorDesc:
	name: str
	ndim: int
	dims: list[int]
	ggml_type: int
	rel_offset: int
	file_index: int


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
	n = read_u64_le(f)
	if n > (256 * 1024 * 1024):
		raise ValueError(f"unreasonable gguf string length: {n}")
	b = read_bytes(f, int(n))
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


def align_up(n: int, alignment: int) -> int:
	return int(n + ((alignment - (n % alignment)) % alignment))


def parse_gguf_stream(f: BinaryIO, label: str) -> tuple[int, dict[str, Any], list[TensorDesc], int, int]:
	magic = read_bytes(f, 4)
	if magic != b"GGUF":
		raise ValueError(f"{label} does not look like a GGUF file (bad magic {magic!r})")
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
		if key in ("general.architecture", "general.alignment") or key.startswith("deepseek4."):
			metadata[key] = read_gguf_value(f, int(vtype))
		else:
			skip_gguf_value(f, int(vtype))

	tensors: list[TensorDesc] = []
	for i in range(int(n_tensors)):
		name = read_gguf_string(f)
		ndim = int(read_u32_le(f))
		dims = [int(read_u64_le(f)) for _ in range(ndim)]
		ggml_type = int(read_u32_le(f))
		rel_offset = int(read_u64_le(f))
		tensors.append(TensorDesc(name=name, ndim=ndim, dims=dims, ggml_type=ggml_type, rel_offset=rel_offset, file_index=i))

	alignment = int(metadata.get("general.alignment", 32))
	if alignment <= 0 or (alignment & (alignment - 1)) != 0:
		raise ValueError(f"{label} has invalid general.alignment={alignment}")
	data_off = align_up(int(f.tell()), alignment)
	return (int(version), metadata, tensors, int(data_off), int(alignment))


def parse_gguf(path: Path) -> tuple[int, dict[str, Any], list[TensorDesc], int, int]:
	with path.open("rb") as f:
		return parse_gguf_stream(f, str(path))


def parse_content_range_total_bytes(content_range: str) -> Optional[int]:
	# Expected: "bytes <start>-<end>/<size>" or "bytes */<size>" or ".../*".
	try:
		tail = content_range.strip().split("/")[-1].strip()
		if tail == "*" or tail == "":
			return None
		return int(tail)
	except Exception:
		return None


def fetch_url_prefix(url: str, want_bytes: int, timeout_s: int = 20) -> tuple[bytes, Optional[int]]:
	req = Request(url, headers={"Range": f"bytes=0-{want_bytes - 1}"})
	with urlopen(req, timeout=timeout_s) as resp:
		status = getattr(resp, "status", None)
		content_range = resp.headers.get("Content-Range", None)
		if status is not None and int(status) != 206:
			raise RuntimeError(
				f"server did not honor Range request for {url} (status={status}); refusing to risk a full download"
			)
		if content_range is None:
			raise RuntimeError(f"server did not return Content-Range for {url}; refusing to risk a full download")
		total_bytes = parse_content_range_total_bytes(str(content_range))
		return (resp.read(want_bytes), total_bytes)


def parse_gguf_url_prefix(
	url: str, max_bytes: int, timeout_s: int = 20
) -> tuple[int, dict[str, Any], list[TensorDesc], int, int, int, Optional[int]]:
	want = 256 * 1024
	while want <= max_bytes:
		try:
			prefix, total_bytes = fetch_url_prefix(url, want, timeout_s=timeout_s)
			f = io.BytesIO(prefix)
			version, meta, tensors, data_off, alignment = parse_gguf_stream(f, url)
			return (version, meta, tensors, len(prefix), data_off, alignment, total_bytes)
		except EOFError:
			want *= 2
			continue
		except HTTPError as e:
			raise RuntimeError(f"HTTP error fetching {url}: {e}") from e
		except URLError as e:
			raise RuntimeError(f"URL error fetching {url}: {e}") from e
	raise RuntimeError(f"unable to parse gguf header/tensor table from {url} within max_bytes={max_bytes}")


def fetch_url_range(url: str, offset: int, n: int, timeout_s: int) -> bytes:
	req = Request(url, headers={"Range": f"bytes={offset}-{offset + n - 1}"})
	with urlopen(req, timeout=timeout_s) as resp:
		status = getattr(resp, "status", None)
		if status is not None and int(status) != 206:
			raise RuntimeError(f"server did not honor Range request for {url} (status={status})")
		return resp.read(n)


def sample_hash_fnv1a64(b: bytes) -> str:
	h = 1469598103934665603
	for x in b:
		h ^= int(x)
		h = ((h * 1099511628211) & 0xFFFFFFFFFFFFFFFF)
	return f"{h:016x}"


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


def prod_i64(xs: list[int]) -> int:
	out = 1
	for x in xs:
		out *= int(x)
	return int(out)


def ggml_row_size_bytes(type_code: int, n_per_row: int) -> int:
	# Minimal ggml row-size calculator for the sidecar’s expected tensor types.
	#
	# Mirrors ggml’s row_size logic for the supported types:
	# - F32: 4 bytes / element
	# - I32: 4 bytes / element
	# - Q8_0: blocks of 32 elems; sizeof(block_q8_0)=sizeof(ggml_half)+32=34 bytes
	# - Q4_K: super-blocks of 256 elems; sizeof(block_q4_K)=2*sizeof(ggml_half)+K_SCALE_SIZE+256/2 = 4+12+128=144 bytes
	n = int(n_per_row)
	if n < 0:
		raise ValueError(f"invalid n_per_row={n}")
	if type_code in (0, 26):  # F32, I32
		return int(n * 4)
	if type_code == 1:  # F16
		return int(n * 2)
	if type_code == 8:  # Q8_0
		qk = 32
		block = 34
		if (n % qk) != 0:
			raise ValueError(f"Q8_0 row length {n} is not a multiple of {qk}")
		return int((n // qk) * block)
	if type_code == 12:  # Q4_K
		qk = 256
		block = 144
		if (n % qk) != 0:
			raise ValueError(f"Q4_K row length {n} is not a multiple of {qk}")
		return int((n // qk) * block)
	raise ValueError(f"unsupported ggml type for row sizing: {ggml_type_name(type_code)} ({type_code})")


def ggml_tensor_nbytes(type_code: int, dims: list[int]) -> int:
	if not dims:
		raise ValueError("tensor has ndim=0")
	n_per_row = int(dims[0])
	n_rows = prod_i64([int(x) for x in dims[1:]]) if len(dims) > 1 else 1
	row_bytes = ggml_row_size_bytes(int(type_code), int(n_per_row))
	return int(row_bytes * int(n_rows))


def must_u32(meta: dict[str, Any], key: str) -> int:
	v = meta.get(key, None)
	if v is None:
		raise KeyError(key)
	try:
		return int(v)
	except Exception as e:
		raise ValueError(f"metadata {key} is not an int: {v!r}") from e


def meta_u32(meta: dict[str, Any], key: str) -> Optional[int]:
	v = meta.get(key, None)
	if v is None:
		return None
	try:
		iv = int(v)
	except Exception:
		return None
	if iv < 0:
		return None
	return int(iv)


def prefer_param(meta_params: dict[str, Optional[int]], derived: dict[str, int], key: str) -> int:
	mv = meta_params.get(key, None)
	if mv is not None and int(mv) != 0:
		return int(mv)
	return int(derived.get(key, 0))


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


def derive_param_from_tensor_1d(errors: list[str], t: Optional[TensorDesc], label: str) -> int:
	if t is None:
		errors.append(f"missing tensor for {label}")
		return 0
	if t.ndim != 1:
		errors.append(f"tensor {t.name} ndim={t.ndim}, expected 1 for {label}")
		return 0
	if len(t.dims) != 1:
		errors.append(f"tensor {t.name} dims={t.dims}, expected len=1 for {label}")
		return 0
	return int(t.dims[0])


def derive_param_from_tensor_2d(errors: list[str], t: Optional[TensorDesc], label: str) -> tuple[int, int]:
	if t is None:
		errors.append(f"missing tensor for {label}")
		return (0, 0)
	if t.ndim != 2:
		errors.append(f"tensor {t.name} ndim={t.ndim}, expected 2 for {label}")
		return (0, 0)
	if len(t.dims) != 2:
		errors.append(f"tensor {t.name} dims={t.dims}, expected len=2 for {label}")
		return (0, 0)
	return (int(t.dims[0]), int(t.dims[1]))


def derive_sidecar_params(errors: list[str], tmap: dict[str, TensorDesc]) -> dict[str, int]:
	n_hc = derive_param_from_tensor_1d(errors, tmap.get("mtp.0.hc_head_base.weight"), "n_hc")
	(hc_dim, n_hc_2) = derive_param_from_tensor_2d(errors, tmap.get("mtp.0.hc_head_fn.weight"), "hc_head_fn")
	if n_hc and n_hc_2 and n_hc_2 != n_hc:
		errors.append(f"hc_head_fn second dim {n_hc_2} != n_hc {n_hc}")
	n_embd = 0
	if n_hc != 0 and hc_dim != 0:
		if (hc_dim % n_hc) != 0:
			errors.append(f"hc_dim {hc_dim} not divisible by n_hc {n_hc}")
		else:
			n_embd = (hc_dim // n_hc)

	n_head = derive_param_from_tensor_1d(errors, tmap.get("mtp.0.attn_sinks.weight"), "n_head")
	n_head_dim = derive_param_from_tensor_1d(errors, tmap.get("mtp.0.attn_kv_a_norm.weight"), "n_head_dim")
	n_lora_q = derive_param_from_tensor_1d(errors, tmap.get("mtp.0.attn_q_a_norm.weight"), "n_lora_q")

	(q_b_d0, q_b_d1) = derive_param_from_tensor_2d(errors, tmap.get("mtp.0.attn_q_b.weight"), "attn_q_b")
	q_dim = q_b_d1
	if n_head and n_head_dim and q_dim:
		if (n_head_dim * n_head) != q_dim:
			errors.append(f"q_dim {q_dim} != n_head*n_head_dim ({n_head}*{n_head_dim}={n_head*n_head_dim})")

	(out_a_d0, out_a_d1) = derive_param_from_tensor_2d(errors, tmap.get("mtp.0.attn_output_a.weight"), "attn_output_a")
	(out_b_d0, out_b_d1) = derive_param_from_tensor_2d(errors, tmap.get("mtp.0.attn_output_b.weight"), "attn_output_b")
	out_low_dim = out_b_d0
	if n_embd and out_b_d1 and out_b_d1 != n_embd:
		errors.append(f"attn_output_b second dim {out_b_d1} != n_embd {n_embd}")
	if out_a_d1 and out_low_dim and out_a_d1 != out_low_dim:
		errors.append(f"attn_output_a second dim {out_a_d1} != attn_output_b first dim {out_low_dim}")

	n_out_group = 0
	n_lora_o = 0
	if n_head and n_head_dim and out_a_d0:
		if (out_a_d0 % n_head_dim) != 0:
			errors.append(f"attn_output_a dim0 {out_a_d0} not divisible by n_head_dim {n_head_dim}")
		else:
			head_per_group = (out_a_d0 // n_head_dim)
			if head_per_group == 0:
				errors.append(f"attn_output_a implies head_per_group=0 (dim0={out_a_d0}, head_dim={n_head_dim})")
			elif (n_head % head_per_group) != 0:
				errors.append(f"n_head {n_head} not divisible by head_per_group {head_per_group}")
			else:
				n_out_group = (n_head // head_per_group)
	if n_out_group and out_low_dim:
		if (out_low_dim % n_out_group) != 0:
			errors.append(f"out_low_dim {out_low_dim} not divisible by n_out_group {n_out_group}")
		else:
			n_lora_o = (out_low_dim // n_out_group)

	n_expert = derive_param_from_tensor_1d(errors, tmap.get("mtp.0.exp_probs_b.bias"), "n_expert")
	(ffn_down_d0, ffn_down_d1) = derive_param_from_tensor_2d(errors, tmap.get("mtp.0.ffn_down_shexp.weight"), "ffn_down_shexp")
	n_ff_exp = ffn_down_d0
	if n_embd and ffn_down_d1 and ffn_down_d1 != n_embd:
		errors.append(f"ffn_down_shexp dim1 {ffn_down_d1} != n_embd {n_embd}")

	return {
		"n_embd": int(n_embd),
		"n_head": int(n_head),
		"n_head_dim": int(n_head_dim),
		"n_hc": int(n_hc),
		"n_lora_q": int(n_lora_q),
		"n_out_group": int(n_out_group),
		"n_lora_o": int(n_lora_o),
		"n_expert": int(n_expert),
		"n_ff_exp": int(n_ff_exp),
	}


def main() -> int:
	parser = ArgumentParser()
	src = parser.add_mutually_exclusive_group(required=True)
	src.add_argument("--path", type=str, help="Path to MTP sidecar GGUF (DeepSeek4 MTP support).")
	src.add_argument("--url", type=str, help="HTTP(S) URL to MTP sidecar GGUF; downloads only the header/tensor table.")
	parser.add_argument("--json", action="store_true", help="Emit machine-readable JSON output.")
	parser.add_argument(
		"--expect-deepseek-v4-flash",
		"--expect-flash",
		dest="expect_deepseek_v4_flash",
		action="store_true",
		help="Require the sidecar-derived params to match DeepSeek-V4-Flash (n_embd=4096,n_head=64,n_head_dim=512,n_hc=4,n_lora_q=1024,n_out_group=8,n_lora_o=1024,n_expert=256,n_ff_exp=2048).",
	)
	parser.add_argument(
		"--payload-sample-bytes",
		type=int,
		default=0,
		help="When >0, attempt to range-read/sample this many bytes from the start of each tensor payload (never downloads full weights).",
	)
	parser.add_argument("--max-bytes", type=int, default=(16 * 1024 * 1024), help="Max bytes to fetch when using --url (default: 16777216).")
	parser.add_argument("--timeout-s", type=int, default=20, help="HTTP timeout seconds for --url (default: 20).")
	parser.add_argument(
		"--expect-file-size",
		type=int,
		default=None,
		help="When set, require the probed file_size matches this value. For --url, requires a server-provided total size via Content-Range.",
	)
	args = parser.parse_args()

	label = ""
	fetched_bytes: Optional[int] = None
	file_size: Optional[int] = None
	data_off = 0
	alignment = 0
	if args.path is not None:
		path = Path(args.path)
		label = str(path)
		version, meta, tensors, data_off, alignment = parse_gguf(path)
		try:
			file_size = int(path.stat().st_size)
		except Exception:
			file_size = None
	else:
		label = str(args.url)
		version, meta, tensors, fetched_bytes, data_off, alignment, file_size = parse_gguf_url_prefix(
			str(args.url), int(args.max_bytes), timeout_s=int(args.timeout_s)
		)

	out: dict[str, Any] = {
		"path": label,
		"gguf_version": int(version),
		"metadata": {k: meta[k] for k in sorted(meta.keys()) if not k.startswith("_")},
		"tensor_count": len(tensors),
		"architecture": meta.get("general.architecture", None),
		"data_offset": int(data_off),
		"alignment": int(alignment),
	}
	if fetched_bytes is not None:
		out["url_prefix_bytes"] = int(fetched_bytes)
	if file_size is not None:
		out["file_size"] = int(file_size)
	if args.expect_file_size is not None:
		out["expect_file_size"] = int(args.expect_file_size)

	tensors_by_offset = sorted(tensors, key=lambda t: (int(t.rel_offset), t.name))
	spans: dict[str, Optional[int]] = {}
	next_rel_off: dict[str, Optional[int]] = {}
	for i, t in enumerate(tensors_by_offset):
		if i + 1 < len(tensors_by_offset):
			nxt = tensors_by_offset[i + 1]
			delta = int(nxt.rel_offset) - int(t.rel_offset)
			if delta > 0:
				spans[t.name] = int(delta)
			else:
				spans[t.name] = None
			next_rel_off[t.name] = int(nxt.rel_offset)
		else:
			spans[t.name] = None
			next_rel_off[t.name] = None

	errors: list[str] = []
	payload_bytes: dict[str, Optional[int]] = {}
	n_elements: dict[str, Optional[int]] = {}
	for t in tensors:
		dims = [int(x) for x in t.dims]
		try:
			n_elements[t.name] = int(prod_i64(dims))
			payload_bytes[t.name] = int(ggml_tensor_nbytes(int(t.ggml_type), dims))
		except Exception as e:
			n_elements[t.name] = None
			payload_bytes[t.name] = None
			errors.append(f"tensor {t.name} payload sizing failed: {e}")

	out_tensors = []
	for t in sorted(tensors, key=lambda x: x.name):
		dims = [int(x) for x in t.dims]
		abs_off = int(data_off + int(t.rel_offset))
		span = spans.get(t.name, None)
		if span is None and file_size is not None:
			span = int(int(file_size) - abs_off)
		pbytes = payload_bytes.get(t.name, None)
		p_end = (int(abs_off) + int(pbytes)) if pbytes is not None else None
		out_tensors.append(
			{
				"name": t.name,
				"type": ggml_type_name(int(t.ggml_type)),
				"type_code": int(t.ggml_type),
				"dims": dims,
				"n_elements": n_elements.get(t.name, None),
				"payload_bytes": pbytes,
				"rel_offset": int(t.rel_offset),
				"abs_offset": abs_off,
				"payload_end_abs": p_end,
				"span_bytes": span,
				"next_rel_offset": next_rel_off.get(t.name, None),
			}
		)
	out["tensors"] = out_tensors

	if version != 3:
		errors.append(f"gguf version is {version}, expected 3")
	if meta.get("general.architecture", None) != "deepseek4_mtp_support":
		errors.append(f"general.architecture is {meta.get('general.architecture', None)!r}, expected 'deepseek4_mtp_support'")
	if args.expect_file_size is not None:
		if file_size is None:
			errors.append("expect-file-size was set but file_size is unavailable (missing stat or Content-Range total bytes)")
		elif int(file_size) != int(args.expect_file_size):
			errors.append(f"file_size is {int(file_size)}, expected {int(args.expect_file_size)}")

	if (data_off % alignment) != 0:
		errors.append(f"data_offset {data_off} is not aligned to alignment {alignment}")

	last_rel = -1
	for t in tensors_by_offset:
		if (int(t.rel_offset) % alignment) != 0:
			errors.append(f"tensor {t.name} rel_offset {t.rel_offset} is not aligned to alignment {alignment}")
		if int(t.rel_offset) < last_rel:
			errors.append(f"tensor offsets not sorted (saw {t.rel_offset} after {last_rel})")
		last_rel = int(t.rel_offset)

	prev_end: Optional[int] = None
	for t in tensors_by_offset:
		abs_off = int(data_off + int(t.rel_offset))
		pbytes = payload_bytes.get(t.name, None)
		if pbytes is None:
			errors.append(f"tensor {t.name} has no computed payload_bytes (unsupported type/dims?)")
			continue
		end_off = int(abs_off + int(pbytes))
		if prev_end is not None and abs_off < int(prev_end):
			errors.append(f"tensor payload overlap: {t.name} abs_offset {abs_off} < prev_end {prev_end}")
		prev_end = int(end_off) if prev_end is None else int(max(int(prev_end), int(end_off)))

		span = spans.get(t.name, None)
		if span is None and file_size is not None:
			span = int(int(file_size) - abs_off)
		if span is not None and int(span) < int(pbytes):
			errors.append(f"tensor {t.name} span_bytes {span} < payload_bytes {pbytes}")

		if file_size is not None:
			if abs_off < 0 or abs_off >= int(file_size):
				errors.append(f"tensor {t.name} abs_offset {abs_off} out of file bounds (file_size={file_size})")
			if end_off > int(file_size):
				errors.append(f"tensor {t.name} end_offset {end_off} exceeds file_size {file_size}")

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

	if int(args.payload_sample_bytes) < 0:
		errors.append("--payload-sample-bytes must be >= 0")

	tmap = {t.name: t for t in tensors}
	derived = derive_sidecar_params(errors, tmap)
	out["derived_params"] = derived

	meta_params: dict[str, Optional[int]] = {
		"n_embd": meta_u32(meta, "deepseek4.embedding_length"),
		"n_head": meta_u32(meta, "deepseek4.attention.head_count"),
		"n_head_dim": meta_u32(meta, "deepseek4.attention.key_length"),
		"n_lora_q": meta_u32(meta, "deepseek4.attention.q_lora_rank"),
		"n_lora_o": meta_u32(meta, "deepseek4.attention.output_lora_rank"),
		"n_out_group": meta_u32(meta, "deepseek4.attention.output_group_count"),
		"n_expert": meta_u32(meta, "deepseek4.expert_count"),
		"n_ff_exp": meta_u32(meta, "deepseek4.expert_feed_forward_length"),
		"n_hc": meta_u32(meta, "deepseek4.hyper_connection.count"),
		"mtp_layer_count": meta_u32(meta, "deepseek4.mtp_layer_count"),
		"nextn_predict_layers": meta_u32(meta, "deepseek4.nextn_predict_layers"),
	}
	out["metadata_params"] = {k: meta_params[k] for k in sorted(meta_params.keys())}

	if meta_params.get("mtp_layer_count", None) not in (None, 0, 1):
		errors.append(
			f"deepseek4.mtp_layer_count is {meta_params.get('mtp_layer_count')}, expected 1 for mtp.0.* sidecar"
		)
	if meta_params.get("nextn_predict_layers", None) not in (None, 0, 1):
		errors.append(
			f"deepseek4.nextn_predict_layers is {meta_params.get('nextn_predict_layers')}, expected 1 for mtp.0.* sidecar"
		)

	n_embd = prefer_param(meta_params, derived, "n_embd")
	n_head = prefer_param(meta_params, derived, "n_head")
	n_head_dim = prefer_param(meta_params, derived, "n_head_dim")
	n_lora_q = prefer_param(meta_params, derived, "n_lora_q")
	n_lora_o = prefer_param(meta_params, derived, "n_lora_o")
	n_out_group = prefer_param(meta_params, derived, "n_out_group")
	n_expert = prefer_param(meta_params, derived, "n_expert")
	n_ff_exp = prefer_param(meta_params, derived, "n_ff_exp")
	n_hc = prefer_param(meta_params, derived, "n_hc")

	for k in ("n_embd", "n_head", "n_head_dim", "n_lora_q", "n_lora_o", "n_out_group", "n_expert", "n_ff_exp", "n_hc"):
		mv = meta_params.get(k, None)
		dv = int(derived.get(k, 0))
		if mv is not None and int(mv) != 0 and dv != 0 and int(mv) != int(dv):
			errors.append(f"metadata param {k}={int(mv)} disagrees with derived {k}={int(dv)}")

	if args.expect_deepseek_v4_flash:
		want = {
			"n_embd": 4096,
			"n_head": 64,
			"n_head_dim": 512,
			"n_hc": 4,
			"n_lora_q": 1024,
			"n_out_group": 8,
			"n_lora_o": 1024,
			"n_expert": 256,
			"n_ff_exp": 2048,
		}
		got = {
			"n_embd": int(n_embd),
			"n_head": int(n_head),
			"n_head_dim": int(n_head_dim),
			"n_hc": int(n_hc),
			"n_lora_q": int(n_lora_q),
			"n_out_group": int(n_out_group),
			"n_lora_o": int(n_lora_o),
			"n_expert": int(n_expert),
			"n_ff_exp": int(n_ff_exp),
		}
		for k in sorted(want.keys()):
			if int(got[k]) != int(want[k]):
				errors.append(f"param {k} is {got[k]}, expected {want[k]} (--expect-deepseek-v4-flash)")

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

	if args.payload_sample_bytes and errors == []:
		sample_n = int(args.payload_sample_bytes)
		out["payload_sample_bytes"] = int(sample_n)
		out["payload_samples"] = {}

		def clamp_payload_sample_want(t: TensorDesc, abs_off: int) -> int:
			want = int(sample_n)
			pbytes = payload_bytes.get(t.name, None)
			if pbytes is not None and pbytes > 0 and pbytes < want:
				want = int(pbytes)
			span = spans.get(t.name, None)
			if span is None and file_size is not None:
				span = int(int(file_size) - int(abs_off))
			if span is not None and span > 0 and span < want:
				want = int(span)
			return int(want)

		if args.path is not None:
			with Path(args.path).open("rb") as f:
				for t in tensors_by_offset:
					abs_off = int(data_off + int(t.rel_offset))
					want = clamp_payload_sample_want(t, abs_off)
					f.seek(abs_off)
					b = f.read(want)
					if len(b) != want:
						errors.append(f"payload sample short read for {t.name}: got {len(b)} bytes, expected {want}")
						continue
					out["payload_samples"][t.name] = {"offset": abs_off, "n": want, "fnv1a64": sample_hash_fnv1a64(b)}
		else:
			url = str(args.url)
			timeout_s = int(args.timeout_s)
			for t in tensors_by_offset:
				abs_off = int(data_off + int(t.rel_offset))
				want = clamp_payload_sample_want(t, abs_off)
				try:
					b = fetch_url_range(url, abs_off, want, timeout_s=timeout_s)
				except Exception as e:
					errors.append(f"payload sample fetch failed for {t.name}: {e}")
					continue
				if len(b) != want:
					errors.append(f"payload sample short fetch for {t.name}: got {len(b)} bytes, expected {want}")
					continue
				out["payload_samples"][t.name] = {"offset": abs_off, "n": want, "fnv1a64": sample_hash_fnv1a64(b)}

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
