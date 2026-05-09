#!/usr/bin/env python3

from collections import Counter
import json
import struct
import sys
from argparse import ArgumentParser
from dataclasses import dataclass
from pathlib import Path
from typing import Any, BinaryIO, Optional


@dataclass(frozen=True)
class InspectResult:
	path: str
	artifact_type: str
	gguf_version: Optional[int]
	metadata: dict[str, Any]
	tensor_count: int
	tensor_type_counts: dict[str, int]
	weight_keys_all: list[str]
	mtp_present: bool
	mtp_tensor_count: int
	mtp_tensor_type_counts: dict[str, int]
	mtp_layer_ids: list[int]
	first_mtp_keys: list[str]
	mtp_keys_all: list[str]


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
	# GGUF strings are: uint64_t length + UTF-8 bytes (no NUL terminator).
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


def read_i8(f: BinaryIO) -> int:
	b = read_bytes(f, 1)
	return int(struct.unpack("<b", b)[0])


def read_u8(f: BinaryIO) -> int:
	b = read_bytes(f, 1)
	return int(struct.unpack("<B", b)[0])


def read_i16_le(f: BinaryIO) -> int:
	b = read_bytes(f, 2)
	return int(struct.unpack("<h", b)[0])


def read_u16_le(f: BinaryIO) -> int:
	b = read_bytes(f, 2)
	return int(struct.unpack("<H", b)[0])


def read_i32_le(f: BinaryIO) -> int:
	b = read_bytes(f, 4)
	return int(struct.unpack("<i", b)[0])


def read_f32_le(f: BinaryIO) -> float:
	b = read_bytes(f, 4)
	return float(struct.unpack("<f", b)[0])


def read_i64_le(f: BinaryIO) -> int:
	b = read_bytes(f, 8)
	return int(struct.unpack("<q", b)[0])


def read_f64_le(f: BinaryIO) -> float:
	b = read_bytes(f, 8)
	return float(struct.unpack("<d", b)[0])


def read_gguf_value(f: BinaryIO, value_type: int) -> Any:
	# Values follow gguf spec: https://github.com/ggerganov/ggml/blob/master/docs/gguf.md
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
		# Arrays can be huge (e.g. tokenizer.ggml.tokens). Avoid loading them here.
		skip_gguf_value(f, value_type)
		return "<array omitted>"
	raise ValueError(f"unsupported gguf value_type={value_type}")


def should_capture_gguf_metadata(key: str, value_type: int) -> bool:
	# Keep output small: capture stable scalar/string keys used for provenance.
	if value_type == 9:
		return False
	if key.startswith("general."):
		return True
	if key == "tokenizer.ggml.model":
		return True
	if key.endswith(
		(
			".context_length",
			".embedding_length",
			".block_count",
			".vocab_size",
			".head_count",
			".head_count_kv",
			".rope.dimension_count",
			".rope.freq_base",
		)
	):
		return True
	return False


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
		gguf_version=None,
		metadata={},
		tensor_count=len(weight_keys),
		tensor_type_counts={},
		weight_keys_all=weight_keys,
		mtp_present=bool(mtp_keys),
		mtp_tensor_count=len(mtp_keys),
		mtp_tensor_type_counts={},
		mtp_layer_ids=sorted(mtp_layer_ids),
		first_mtp_keys=mtp_keys[:10],
		mtp_keys_all=mtp_keys,
	)


def load_default_contract_summary_path() -> Optional[Path]:
	root = Path(__file__).resolve().parents[1]
	candidate = root / "fixtures" / "model_contract" / "deepseek_v4_flash" / "contract_summary.json"
	if candidate.exists():
		return candidate
	return None


def compute_trunk_contract(weight_keys: set[str], contract_summary: dict[str, Any]) -> dict[str, Any]:
	if not weight_keys:
		return {"checked": False, "reason": "no tensor keys found"}

	tk = contract_summary.get("tensor_keys", {})
	topo = contract_summary.get("topology", {})
	attn = contract_summary.get("attention_schedule", {})
	moe = contract_summary.get("moe", {})

	required_top_level = tk.get("required_top_level", None)
	required_layer_suffixes = tk.get("required_layer_suffixes", None)
	required_nonzero = tk.get("required_layer_suffixes_compress_ratio_nonzero", None)
	required_ratio4 = tk.get("required_layer_suffixes_compress_ratio_4", None)

	hash_gate_suffix = tk.get("hash_gate_tensor_key_suffix", "ffn.gate.tid2eid")
	score_gate_suffix = tk.get("score_gate_tensor_key_suffix", "ffn.gate.bias")

	compress_ratios = attn.get("compress_ratios", None)
	n_layers = topo.get("num_hidden_layers", None)
	n_hash_layers = moe.get("n_hash_layers", None)
	n_routed_experts = moe.get("n_routed_experts", None)

	if not isinstance(required_top_level, list) or not isinstance(required_layer_suffixes, list):
		return {"checked": False, "reason": "contract_summary missing tensor_keys.required_* lists"}
	if not isinstance(required_nonzero, list) or not isinstance(required_ratio4, list):
		return {"checked": False, "reason": "contract_summary missing tensor_keys.required_layer_suffixes_compress_ratio_* lists"}
	if not isinstance(compress_ratios, list):
		return {"checked": False, "reason": "contract_summary missing attention_schedule.compress_ratios"}
	try:
		n_layers_i = int(n_layers)
		n_hash_layers_i = int(n_hash_layers)
		n_routed_experts_i = int(n_routed_experts)
	except Exception:
		return {"checked": False, "reason": "contract_summary missing topology/moe layer counts"}
	if n_layers_i <= 0 or n_routed_experts_i <= 0:
		return {"checked": False, "reason": "contract_summary has invalid layer/expert counts"}
	if len(compress_ratios) < n_layers_i:
		return {"checked": False, "reason": "contract_summary compress_ratios shorter than num_hidden_layers"}

	missing_count = 0
	missing_sample: list[str] = []
	forbidden_present: set[str] = set()

	def note_missing(key: str) -> None:
		nonlocal missing_count
		missing_count += 1
		if len(missing_sample) < 20:
			missing_sample.append(key)

	for k in required_top_level:
		if not isinstance(k, str) or not k:
			continue
		if k not in weight_keys:
			note_missing(k)

	for i in range(n_layers_i):
		prefix = f"layers.{i}."
		try:
			ratio_i = int(compress_ratios[i])
		except Exception:
			ratio_i = 0

		for suffix in required_layer_suffixes:
			if not isinstance(suffix, str) or not suffix:
				continue
			need = prefix + suffix
			if need not in weight_keys:
				note_missing(need)

		if ratio_i != 0:
			for suffix in required_nonzero:
				if not isinstance(suffix, str) or not suffix:
					continue
				need = prefix + suffix
				if need not in weight_keys:
					note_missing(need)

		if ratio_i == 4:
			for suffix in required_ratio4:
				if not isinstance(suffix, str) or not suffix:
					continue
				need = prefix + suffix
				if need not in weight_keys:
					note_missing(need)

		if i < n_hash_layers_i:
			need_hash = prefix + str(hash_gate_suffix)
			if need_hash not in weight_keys:
				note_missing(need_hash)
			bad_score = prefix + str(score_gate_suffix)
			if bad_score in weight_keys:
				forbidden_present.add(bad_score)
		else:
			need_score = prefix + str(score_gate_suffix)
			if need_score not in weight_keys:
				note_missing(need_score)
			bad_hash = prefix + str(hash_gate_suffix)
			if bad_hash in weight_keys:
				forbidden_present.add(bad_hash)

		for eid in range(n_routed_experts_i):
			for w in (1, 2, 3):
				for s in ("weight", "scale"):
					need = f"{prefix}ffn.experts.{eid}.w{w}.{s}"
					if need not in weight_keys:
						note_missing(need)

	forbidden_sorted = sorted(forbidden_present)[:20]
	return {
		"checked": True,
		"complete": (missing_count == 0 and len(forbidden_sorted) == 0),
		"n_layers_checked": n_layers_i,
		"missing_required_count": missing_count,
		"missing_required_sample": missing_sample,
		"forbidden_present": forbidden_sorted,
	}


def compute_topology_contract(metadata: dict[str, Any], contract_summary: dict[str, Any]) -> dict[str, Any]:
	if not metadata:
		return {"checked": False, "reason": "no metadata captured from artifact header"}

	topo = contract_summary.get("topology", {})
	mtp = contract_summary.get("mtp", {})

	def expected_int(name: str) -> Optional[int]:
		try:
			return int(topo[name])
		except Exception:
			return None

	expected_hidden = expected_int("hidden_size")
	expected_layers = expected_int("num_hidden_layers")
	expected_heads = expected_int("num_attention_heads")
	expected_kv_heads = expected_int("num_key_value_heads")
	expected_vocab = expected_int("vocab_size")
	try:
		expected_mtp_layers = int(mtp.get("n_mtp_layers", 0))
	except Exception:
		expected_mtp_layers = 0

	def pick_int(keys: list[str]) -> Optional[int]:
		for k in keys:
			v = metadata.get(k, None)
			try:
				return int(v)
			except Exception:
				continue
		return None

	embedding_keys = [k for k in metadata.keys() if k.endswith(".embedding_length")]
	block_keys = [k for k in metadata.keys() if k.endswith(".block_count")]
	vocab_keys = [k for k in metadata.keys() if k.endswith(".vocab_size")]
	head_keys = [k for k in metadata.keys() if k.endswith(".head_count")]
	kv_head_keys = [k for k in metadata.keys() if k.endswith(".head_count_kv")]

	embedding_len = pick_int(sorted(embedding_keys))
	block_count = pick_int(sorted(block_keys))
	vocab_size = pick_int(sorted(vocab_keys))
	head_count = pick_int(sorted(head_keys))
	kv_head_count = pick_int(sorted(kv_head_keys))

	mismatches: list[str] = []

	def check_eq(label: str, got: Optional[int], expected: Optional[int]) -> None:
		if got is None or expected is None:
			return
		if int(got) != int(expected):
			mismatches.append(f"{label}: got={got} expected={expected}")

	check_eq("embedding_length", embedding_len, expected_hidden)
	check_eq("vocab_size", vocab_size, expected_vocab)
	check_eq("head_count", head_count, expected_heads)
	check_eq("head_count_kv", kv_head_count, expected_kv_heads)

	block_count_ok = None
	if block_count is not None and expected_layers is not None:
		ok_values = {int(expected_layers)}
		if expected_mtp_layers > 0:
			ok_values.add(int(expected_layers) + int(expected_mtp_layers))
		block_count_ok = (int(block_count) in ok_values)
		if not block_count_ok:
			mismatches.append(f"block_count: got={block_count} expected_one_of={sorted(ok_values)}")

	return {
		"checked": True,
		"embedding_length": embedding_len,
		"block_count": block_count,
		"block_count_ok": block_count_ok,
		"vocab_size": vocab_size,
		"head_count": head_count,
		"head_count_kv": kv_head_count,
		"mismatches": mismatches[:20],
	}


def compute_mtp_contract(mtp_keys: set[str], contract_summary: dict[str, Any]) -> dict[str, Any]:
	if not mtp_keys:
		return {"checked": False, "reason": "no mtp.* tensors present"}

	tk = contract_summary.get("tensor_keys", {})
	moe = contract_summary.get("moe", {})

	required_layer_suffixes = tk.get("required_layer_suffixes", None)
	required_mtp_additional_suffixes = tk.get("required_mtp_additional_suffixes", None)
	score_gate_suffix = tk.get("mtp_score_gate_tensor_key_suffix", tk.get("score_gate_tensor_key_suffix", "ffn.gate.bias"))
	n_routed_experts = moe.get("n_routed_experts", None)

	if not isinstance(required_layer_suffixes, list) or not isinstance(required_mtp_additional_suffixes, list):
		return {"checked": False, "reason": "contract_summary missing tensor_keys.required_* lists"}
	try:
		n_routed_experts_i = int(n_routed_experts)
	except Exception:
		n_routed_experts_i = 0
	if n_routed_experts_i <= 0:
		return {"checked": False, "reason": "contract_summary missing moe.n_routed_experts"}

	mtp_layer_ids_present: set[int] = set()
	for k in mtp_keys:
		parts = k.split(".", 2)
		if len(parts) < 2:
			continue
		try:
			mtp_layer_ids_present.add(int(parts[1]))
		except ValueError:
			continue

	missing_required: set[str] = set()
	forbidden_present: set[str] = set()

	for mtp_id in sorted(mtp_layer_ids_present):
		prefix = f"mtp.{mtp_id}."

		for bad in ("attn.compressor.", "attn.indexer."):
			if any(k.startswith(prefix + bad) for k in mtp_keys):
				forbidden_present.add(prefix + bad)
		for bad in ("ffn.gate.tid2eid", "embed.weight", "head.weight"):
			if (prefix + bad) in mtp_keys:
				forbidden_present.add(prefix + bad)

		for suffix in required_layer_suffixes:
			need = prefix + suffix
			if need not in mtp_keys:
				missing_required.add(need)

		need_gate = prefix + str(score_gate_suffix)
		if need_gate not in mtp_keys:
			missing_required.add(need_gate)

		for eid in range(n_routed_experts_i):
			for w in (1, 2, 3):
				for s in ("weight", "scale"):
					need = f"{prefix}ffn.experts.{eid}.w{w}.{s}"
					if need not in mtp_keys:
						missing_required.add(need)

		for suffix in required_mtp_additional_suffixes:
			need = prefix + suffix
			if need not in mtp_keys:
				missing_required.add(need)

	missing_sorted = sorted(missing_required)
	forbidden_sorted = sorted(forbidden_present)
	return {
		"checked": True,
		"complete": (len(missing_sorted) == 0 and len(forbidden_sorted) == 0),
		"mtp_layer_ids_present": sorted(mtp_layer_ids_present),
		"missing_required_count": len(missing_sorted),
		"missing_required_sample": missing_sorted[:20],
		"forbidden_present": forbidden_sorted[:20],
	}


MTP_SIDECAR_EXPECTED_TENSORS: list[str] = [
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


def compute_mtp_sidecar_contract(mtp_keys: set[str]) -> dict[str, Any]:
	# DS4-tuned MTP sidecars (general.architecture=deepseek4_mtp_support) are not
	# full official mtp.* checkpoints. They are expected to contain exactly this
	# 32-tensor mtp.0.* table.
	if not mtp_keys:
		return {"checked": False, "reason": "no mtp.* tensors present"}
	expected = set(MTP_SIDECAR_EXPECTED_TENSORS)
	missing = sorted(expected - mtp_keys)
	extra = sorted(mtp_keys - expected)
	out: dict[str, Any] = {
		"checked": True,
		"expected_tensor_count": len(MTP_SIDECAR_EXPECTED_TENSORS),
		"found_tensor_count": len(mtp_keys),
		"complete": (not missing and not extra and len(mtp_keys) == len(MTP_SIDECAR_EXPECTED_TENSORS)),
		"missing_count": len(missing),
		"extra_count": len(extra),
		"missing_sample": missing[:20],
		"extra_sample": extra[:20],
	}
	if any(not k.startswith("mtp.0.") for k in mtp_keys):
		out["complete"] = False
		out["namespace_error"] = True
	return out


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
		vers = int(read_u32_le(f))
		n_tensors = read_u64_le(f)
		n_kv = read_u64_le(f)

		metadata: dict[str, Any] = {}
		for _ in range(int(n_kv)):
			key = read_gguf_string(f)
			vtype = read_u32_le(f)
			if should_capture_gguf_metadata(key, int(vtype)):
				metadata[key] = read_gguf_value(f, int(vtype))
			else:
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
		gguf_version=vers,
		metadata=metadata,
		tensor_count=res.tensor_count,
		tensor_type_counts=dict(sorted(type_counts.items())),
		weight_keys_all=res.weight_keys_all,
		mtp_present=res.mtp_present,
		mtp_tensor_count=res.mtp_tensor_count,
		mtp_tensor_type_counts=dict(sorted(mtp_type_counts.items())),
		mtp_layer_ids=res.mtp_layer_ids,
		first_mtp_keys=res.first_mtp_keys,
		mtp_keys_all=res.mtp_keys_all,
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
	parser.add_argument(
		"--path",
		type=str,
		action="append",
		required=True,
		help="Quantized artifact path: .gguf, model.safetensors.index.json, or a directory containing it. May be passed multiple times (e.g. trunk + MTP sidecar).",
	)
	parser.add_argument("--json", action="store_true", help="Emit machine-readable JSON output.")
	parser.add_argument("--require-mtp", action="store_true", help="Exit non-zero if no mtp.* tensors are present.")
	parser.add_argument(
		"--contract-summary",
		type=str,
		default=None,
		help="Optional path to a DeepSeek V4 Flash contract_summary.json. When provided (or when the repo default exists), emits an mtp_contract completeness check for mtp.* tensor keys.",
	)
	args = parser.parse_args()

	results: list[InspectResult] = []
	for p in args.path:
		try:
			results.append(detect_and_inspect(Path(p)))
		except Exception as e:
			print(f"ERROR: {e}")
			return 2

	contract_summary: Optional[dict[str, Any]] = None
	contract_path = Path(args.contract_summary) if args.contract_summary else load_default_contract_summary_path()
	if contract_path is not None:
		try:
			contract_summary = load_json(contract_path)
		except Exception:
			contract_summary = None

	def is_mtp_sidecar(metadata: dict[str, Any]) -> bool:
		return (metadata.get("general.architecture", None) == "deepseek4_mtp_support")

	def as_dict(res: InspectResult) -> dict[str, Any]:
		return {
			"path": res.path,
			"artifact_type": res.artifact_type,
			"gguf_version": res.gguf_version,
			"metadata": res.metadata,
			"tensor_count": res.tensor_count,
			"tensor_type_counts": res.tensor_type_counts,
			"mtp_present": res.mtp_present,
			"mtp_tensor_count": res.mtp_tensor_count,
			"mtp_tensor_type_counts": res.mtp_tensor_type_counts,
			"mtp_layer_ids": res.mtp_layer_ids,
			"first_mtp_keys": res.first_mtp_keys,
		}

	def combine(results: list[InspectResult]) -> dict[str, Any]:
		type_counts: Counter[str] = Counter()
		mtp_type_counts: Counter[str] = Counter()
		mtp_layer_ids: set[int] = set()
		first_mtp_keys: list[str] = []
		mtp_keys_union: set[str] = set()
		weight_keys_union: set[str] = set()
		topology_candidate: Optional[InspectResult] = None
		for res in results:
			type_counts.update(res.tensor_type_counts)
			mtp_type_counts.update(res.mtp_tensor_type_counts)
			mtp_layer_ids.update(res.mtp_layer_ids)
			mtp_keys_union.update(res.mtp_keys_all)
			weight_keys_union.update(res.weight_keys_all)
			if res.metadata:
				if topology_candidate is None or res.tensor_count > topology_candidate.tensor_count:
					topology_candidate = res
			for k in res.first_mtp_keys:
				if k in first_mtp_keys:
					continue
				first_mtp_keys.append(k)
				if len(first_mtp_keys) >= 20:
					break
		mtp_contract = None
		mtp_sidecar_contract = None
		trunk_contract = None
		topology_contract = None
		if any(is_mtp_sidecar(r.metadata) for r in results):
			sidecar_union = set()
			for r in results:
				if is_mtp_sidecar(r.metadata):
					sidecar_union.update(r.mtp_keys_all)
			mtp_sidecar_contract = compute_mtp_sidecar_contract(sidecar_union)
			mtp_contract = {"checked": False, "reason": "deepseek4_mtp_support sidecar present; mtp_sidecar_contract applies"}
		elif contract_summary is not None:
				mtp_contract = compute_mtp_contract(mtp_keys_union, contract_summary)
		if contract_summary is not None:
			trunk_contract = compute_trunk_contract(weight_keys_union, contract_summary)
			if topology_candidate is not None:
				topology_contract = compute_topology_contract(topology_candidate.metadata, contract_summary)
		return {
			"paths": [r.path for r in results],
			"artifact_types": [r.artifact_type for r in results],
			"tensor_count": sum(r.tensor_count for r in results),
			"tensor_type_counts": dict(sorted(type_counts.items())),
			"mtp_present": any(r.mtp_present for r in results),
			"mtp_paths": [r.path for r in results if r.mtp_present],
			"mtp_tensor_count": sum(r.mtp_tensor_count for r in results),
			"mtp_tensor_type_counts": dict(sorted(mtp_type_counts.items())),
			"mtp_layer_ids": sorted(mtp_layer_ids),
			"first_mtp_keys": first_mtp_keys,
			"mtp_contract": mtp_contract,
			"mtp_sidecar_contract": mtp_sidecar_contract,
			"trunk_contract": trunk_contract,
			"topology_contract_source_path": (None if topology_candidate is None else topology_candidate.path),
			"topology_contract": topology_contract,
		}

	if args.json:
		if len(results) == 1:
			out = as_dict(results[0])
			if is_mtp_sidecar(results[0].metadata):
				out["mtp_sidecar_contract"] = compute_mtp_sidecar_contract(set(results[0].mtp_keys_all))
				out["mtp_contract"] = {"checked": False, "reason": "deepseek4_mtp_support sidecar; mtp_sidecar_contract applies"}
			elif contract_summary is not None:
				out["mtp_contract"] = compute_mtp_contract(set(results[0].mtp_keys_all), contract_summary)
			if contract_summary is not None:
				out["trunk_contract"] = compute_trunk_contract(set(results[0].weight_keys_all), contract_summary)
				out["topology_contract"] = compute_topology_contract(results[0].metadata, contract_summary)
			print(json.dumps(out, indent=2, sort_keys=True))
		else:
			print(
				json.dumps(
					{
						"combined": combine(results),
						"artifacts": [
							{
								**as_dict(r),
								**(
									(
										{
											"mtp_sidecar_contract": compute_mtp_sidecar_contract(set(r.mtp_keys_all)),
											"mtp_contract": {"checked": False, "reason": "deepseek4_mtp_support sidecar; mtp_sidecar_contract applies"},
										}
										if is_mtp_sidecar(r.metadata)
										else (
											{}
											if contract_summary is None
											else {"mtp_contract": compute_mtp_contract(set(r.mtp_keys_all), contract_summary)}
										)
									)
								),
								**(
									{}
									if contract_summary is None
									else {
										"trunk_contract": compute_trunk_contract(set(r.weight_keys_all), contract_summary),
										"topology_contract": compute_topology_contract(r.metadata, contract_summary),
									}
								),
							}
							for r in results
						],
					},
					indent=2,
					sort_keys=True,
				)
			)
	else:
		if len(results) > 1:
			combined = combine(results)
			print(f"tensor_count: {combined['tensor_count']}")
			for k in sorted(combined["tensor_type_counts"].keys()):
				print(f"tensor_type_count: {k}={combined['tensor_type_counts'][k]}")
			print(f"mtp_present: {str(combined['mtp_present']).lower()}")
			print(f"mtp_tensor_count: {combined['mtp_tensor_count']}")
			for k in sorted(combined["mtp_tensor_type_counts"].keys()):
				print(f"mtp_tensor_type_count: {k}={combined['mtp_tensor_type_counts'][k]}")
			print(f"mtp_layer_ids: {combined['mtp_layer_ids']}")
			for k in combined["first_mtp_keys"]:
				print(f"mtp_key: {k}")
			mtp_contract = combined.get("mtp_contract", None)
			if isinstance(mtp_contract, dict) and mtp_contract.get("checked") is True:
				print(f"mtp_contract_complete: {str(bool(mtp_contract.get('complete', False))).lower()}")
				print(f"mtp_contract_missing_required_count: {int(mtp_contract.get('missing_required_count', 0))}")
				for k in list(mtp_contract.get("missing_required_sample", []))[:10]:
					print(f"mtp_contract_missing_required: {k}")
				for k in list(mtp_contract.get("forbidden_present", []))[:10]:
					print(f"mtp_contract_forbidden_present: {k}")
			mtp_sidecar_contract = combined.get("mtp_sidecar_contract", None)
			if isinstance(mtp_sidecar_contract, dict) and mtp_sidecar_contract.get("checked") is True:
				print(f"mtp_sidecar_contract_complete: {str(bool(mtp_sidecar_contract.get('complete', False))).lower()}")
				print(f"mtp_sidecar_contract_missing_count: {int(mtp_sidecar_contract.get('missing_count', 0))}")
				for k in list(mtp_sidecar_contract.get("missing_sample", []))[:10]:
					print(f"mtp_sidecar_contract_missing: {k}")
				for k in list(mtp_sidecar_contract.get("extra_sample", []))[:10]:
					print(f"mtp_sidecar_contract_extra: {k}")
			trunk_contract = combined.get("trunk_contract", None)
			if isinstance(trunk_contract, dict) and trunk_contract.get("checked") is True:
				print(f"trunk_contract_complete: {str(bool(trunk_contract.get('complete', False))).lower()}")
				print(f"trunk_contract_missing_required_count: {int(trunk_contract.get('missing_required_count', 0))}")
				for k in list(trunk_contract.get("missing_required_sample", []))[:10]:
					print(f"trunk_contract_missing_required: {k}")
				for k in list(trunk_contract.get("forbidden_present", []))[:10]:
					print(f"trunk_contract_forbidden_present: {k}")
			topology_contract = combined.get("topology_contract", None)
			if isinstance(topology_contract, dict) and topology_contract.get("checked") is True:
				src = combined.get("topology_contract_source_path", None)
				if isinstance(src, str) and src:
					print(f"topology_contract_source_path: {src}")
				mm = topology_contract.get("mismatches", None)
				if isinstance(mm, list) and mm:
					print(f"topology_contract_mismatches: {len(mm)}")
					for m in mm[:10]:
						print(f"topology_contract_mismatch: {m}")
				else:
					print("topology_contract_mismatches: 0")
			for res in results:
				print(f"artifact_path: {res.path}")
				print(f"artifact_type: {res.artifact_type}")
				if res.gguf_version is not None:
					print(f"gguf_version: {res.gguf_version}")
				for k in sorted(res.metadata.keys()):
					print(f"metadata: {k}={res.metadata[k]}")
				if contract_summary is not None:
					topology_contract = compute_topology_contract(res.metadata, contract_summary)
					if isinstance(topology_contract, dict) and topology_contract.get("checked") is True:
						mismatches = topology_contract.get("mismatches", [])
						print(f"topology_contract_mismatch_count: {len(mismatches) if isinstance(mismatches, list) else 0}")
						for m in list(mismatches)[:10]:
							print(f"topology_contract_mismatch: {m}")
		else:
			res = results[0]
			print(f"path: {res.path}")
			print(f"artifact_type: {res.artifact_type}")
			if res.gguf_version is not None:
				print(f"gguf_version: {res.gguf_version}")
			for k in sorted(res.metadata.keys()):
				print(f"metadata: {k}={res.metadata[k]}")
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
			if contract_summary is not None:
				if is_mtp_sidecar(res.metadata):
					mtp_sidecar_contract = compute_mtp_sidecar_contract(set(res.mtp_keys_all))
					if mtp_sidecar_contract.get("checked") is True:
						print(f"mtp_sidecar_contract_complete: {str(bool(mtp_sidecar_contract.get('complete', False))).lower()}")
						print(f"mtp_sidecar_contract_missing_count: {int(mtp_sidecar_contract.get('missing_count', 0))}")
						for k in list(mtp_sidecar_contract.get("missing_sample", []))[:10]:
							print(f"mtp_sidecar_contract_missing: {k}")
						for k in list(mtp_sidecar_contract.get("extra_sample", []))[:10]:
							print(f"mtp_sidecar_contract_extra: {k}")
					else:
						mtp_contract = compute_mtp_contract(set(res.mtp_keys_all), contract_summary)
						if mtp_contract.get("checked") is True:
							print(f"mtp_contract_complete: {str(bool(mtp_contract.get('complete', False))).lower()}")
							print(f"mtp_contract_missing_required_count: {int(mtp_contract.get('missing_required_count', 0))}")
							for k in list(mtp_contract.get("missing_required_sample", []))[:10]:
								print(f"mtp_contract_missing_required: {k}")
							for k in list(mtp_contract.get("forbidden_present", []))[:10]:
								print(f"mtp_contract_forbidden_present: {k}")
				trunk_contract = compute_trunk_contract(set(res.weight_keys_all), contract_summary)
				if trunk_contract.get("checked") is True:
					print(f"trunk_contract_complete: {str(bool(trunk_contract.get('complete', False))).lower()}")
					print(f"trunk_contract_missing_required_count: {int(trunk_contract.get('missing_required_count', 0))}")
					for k in list(trunk_contract.get("missing_required_sample", []))[:10]:
						print(f"trunk_contract_missing_required: {k}")
					for k in list(trunk_contract.get("forbidden_present", []))[:10]:
						print(f"trunk_contract_forbidden_present: {k}")
				topology_contract = compute_topology_contract(res.metadata, contract_summary)
				if isinstance(topology_contract, dict) and topology_contract.get("checked") is True:
					mismatches = topology_contract.get("mismatches", [])
					print(f"topology_contract_mismatch_count: {len(mismatches) if isinstance(mismatches, list) else 0}")
					for m in list(mismatches)[:10]:
						print(f"topology_contract_mismatch: {m}")

	if args.require_mtp and not any(r.mtp_present for r in results):
		return 1
	return 0


if __name__ == "__main__":
	raise SystemExit(main())
