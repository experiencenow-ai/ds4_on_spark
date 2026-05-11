#!/usr/bin/env python3

from collections import Counter
import io
import json
import struct
import sys
from argparse import ArgumentParser
from dataclasses import dataclass
from pathlib import Path
from typing import Any, BinaryIO, Callable, Optional
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen


@dataclass(frozen=True)
class InspectResult:
	path: str
	artifact_type: str
	gguf_version: Optional[int]
	url_prefix_bytes: Optional[int]
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
	tensor_type_profile: Optional[dict[str, Any]] = None


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


def read_gguf_string(f: BinaryIO, n: int) -> str:
	b = read_bytes(f, n)
	try:
		return b.decode("utf-8")
	except UnicodeDecodeError:
		return b.decode("utf-8", errors="replace")


def skip_gguf_value(read_size, f: BinaryIO, value_type: int) -> None:
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
		_ = read_gguf_string(f, int(read_size()))
		return
	if value_type == 9:  # array
		elem_type = read_u32_le(f)
		n = int(read_size())
		for _ in range(int(n)):
			skip_gguf_value(read_size, f, int(elem_type))
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


def read_gguf_value(read_size, f: BinaryIO, value_type: int) -> Any:
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
		return read_gguf_string(f, int(read_size()))
	if value_type == 10:
		return read_u64_le(f)
	if value_type == 11:
		return read_i64_le(f)
	if value_type == 12:
		return read_f64_le(f)
	if value_type == 9:
		# Arrays can be huge (e.g. tokenizer.ggml.tokens). Avoid loading them here.
		skip_gguf_value(read_size, f, value_type)
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
		url_prefix_bytes=None,
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


def fetch_url_prefix(url: str, want_bytes: int, timeout_s: int) -> bytes:
	req = Request(url, headers={"Range": f"bytes=0-{want_bytes - 1}"})
	with urlopen(req, timeout=timeout_s) as resp:
		status = getattr(resp, "status", None)
		if status is None:
			try:
				status = resp.getcode()
			except Exception:
				status = None
		content_range = resp.headers.get("Content-Range", None)
		if status is not None and int(status) != 206:
			raise RuntimeError(
				f"server did not honor Range request for {url} (status={status}); refusing to risk a full download"
			)
		if content_range is None:
			raise RuntimeError(f"server did not return Content-Range for {url}; refusing to risk a full download")
		return resp.read(want_bytes)


def parse_gguf_url_prefix(url: str, max_bytes: int, timeout_s: int) -> tuple[int, dict[str, Any], list[str], list[int], int]:
	want = 256 * 1024
	while want <= max_bytes:
		try:
			prefix = fetch_url_prefix(url, want, timeout_s=timeout_s)
			f = io.BytesIO(prefix)
			vers, metadata, weight_keys, weight_types = parse_gguf_stream(f, url)
			return (vers, metadata, weight_keys, weight_types, len(prefix))
		except EOFError:
			want *= 2
			continue
		except HTTPError as e:
			raise RuntimeError(f"HTTP error fetching {url}: {e}") from e
		except URLError as e:
			raise RuntimeError(f"URL error fetching {url}: {e}") from e
	raise RuntimeError(f"unable to parse gguf header/tensor table from {url} within max_bytes={max_bytes}")


def parse_gguf_stream(f: BinaryIO, label: str) -> tuple[int, dict[str, Any], list[str], list[int]]:
	magic = read_bytes(f, 4)
	if magic != b"GGUF":
		raise ValueError(f"{label} does not look like a GGUF file (bad magic {magic!r})")
	vers = int(read_u32_le(f))

	def read_size() -> int:
		if vers == 1:
			return int(read_u32_le(f))
		return int(read_u64_le(f))

	n_tensors = int(read_size())
	n_kv = int(read_size())

	metadata: dict[str, Any] = {}
	for _ in range(int(n_kv)):
		key = read_gguf_string(f, int(read_size()))
		vtype = read_u32_le(f)
		if should_capture_gguf_metadata(key, int(vtype)):
			metadata[key] = read_gguf_value(read_size, f, int(vtype))
		else:
			skip_gguf_value(read_size, f, int(vtype))

	weight_keys: list[str] = []
	weight_types: list[int] = []
	for _ in range(int(n_tensors)):
		name = read_gguf_string(f, int(read_size()))
		nd = read_u32_le(f)
		for _ in range(int(nd)):
			_ = read_u64_le(f)
		tensor_type = read_u32_le(f)  # ggml_type
		_ = read_u64_le(f)  # offset
		weight_keys.append(name)
		weight_types.append(int(tensor_type))

	return (vers, metadata, weight_keys, weight_types)


def guess_tensor_key_namespace(weight_keys: list[str]) -> tuple[str, list[str]]:
	if not weight_keys:
		return ("empty", ["no tensor keys"])

	evidence: list[str] = []

	def saw_prefix(prefix: str) -> bool:
		return any(k.startswith(prefix) for k in weight_keys)

	def saw_any(keys: set[str]) -> bool:
		return any(k in keys for k in weight_keys)

	if saw_prefix("layers.") or saw_any({"embed.weight", "head.weight", "norm.weight"}):
		evidence.append("found deepseek upstream-style keys (layers.* and/or embed/head/norm)")
		return ("deepseek-upstream", evidence)

	if saw_prefix("mtp."):
		evidence.append("found mtp.* tensor namespace")
		return ("deepseek-upstream-mtp-only", evidence)

	if saw_prefix("blk.") or saw_any({"token_embd.weight", "output.weight"}):
		evidence.append("found llama.cpp-style keys (blk.* and/or token_embd/output)")
		return ("llama.cpp", evidence)

	if saw_prefix("block.") or saw_prefix("model.layers."):
		evidence.append("found transformer-style keys (block.* or model.layers.*), not deepseek upstream namespace")
		return ("hf-transformers", evidence)

	evidence.append("no known key namespace patterns matched")
	return ("unknown", evidence)


def compute_tensor_type_profile(
	weight_keys: list[str],
	weight_types: list[int],
	metadata: dict[str, Any],
	type_name: Callable[[int], str],
) -> Optional[dict[str, Any]]:
	if not weight_keys or not weight_types:
		return None
	if len(weight_keys) != len(weight_types):
		return None

	namespace_guess, _ = guess_tensor_key_namespace(weight_keys)
	arch = None
	if isinstance(metadata, dict):
		arch = metadata.get("general.architecture", None)

	def categorize_upstream(k: str) -> str:
		if k.startswith("mtp."):
			return "mtp"
		if k.startswith("layers."):
			if ".ffn.experts." in k:
				return "experts"
			if ".ffn.shared_experts." in k:
				return "shared_experts"
			if ".attn." in k:
				return "attn"
			if ".ffn.gate." in k:
				return "gate"
			if ".ffn." in k:
				return "ffn_other"
			if ".hc_" in k:
				return "hc"
			return "layers_other"
		if k.startswith("embed.") or k.startswith("head.") or k.startswith("norm.") or k.startswith("hc_head_"):
			return "top_level"
		return "other"

	def categorize_llamacpp(k: str) -> str:
		if k == "token_embd.weight":
			return "embed"
		if k == "output.weight":
			return "head"
		if k.endswith("_exps.weight"):
			return "experts_packed"
		if k.endswith("_shexp.weight"):
			return "shared_expert_packed"
		if ".ffn_gate_" in k:
			return "ffn_gate"
		if ".ffn_" in k:
			return "ffn_other"
		if ".attn_" in k:
			return "attn"
		if ".hc_" in k:
			return "hc"
		if k.endswith("norm.weight") or k.endswith("_norm.weight"):
			return "norm"
		return "other"

	if namespace_guess in ("deepseek-upstream", "deepseek-upstream-mtp-only"):
		categorize = categorize_upstream
	elif namespace_guess == "llama.cpp":
		categorize = categorize_llamacpp
	else:
		return {"checked": False, "namespace_guess": namespace_guess, "reason": "unsupported tensor-key namespace for type profiling"}

	category_counts: dict[str, Counter[str]] = {}
	for k, t in zip(weight_keys, weight_types):
		cat = categorize(str(k))
		c = category_counts.get(cat, None)
		if c is None:
			c = Counter()
			category_counts[cat] = c
		c[type_name(int(t))] += 1

	def summarize_primary(counter: Counter[str]) -> Optional[dict[str, Any]]:
		if not counter:
			return None
		t, n = counter.most_common(1)[0]
		return {"type": t, "count": int(n)}

	expert_primary = summarize_primary(category_counts.get("experts_packed", Counter()) or category_counts.get("experts", Counter()))
	shared_expert_primary = summarize_primary(category_counts.get("shared_expert_packed", Counter()) or category_counts.get("shared_experts", Counter()))

	non_expert = Counter()
	for cat, cnt in category_counts.items():
		if cat in ("experts_packed", "experts", "shared_expert_packed", "shared_experts"):
			continue
		non_expert.update(cnt)
	dense_primary = summarize_primary(non_expert)

	hints: dict[str, Any] = {
		"expert_primary": expert_primary,
		"shared_expert_primary": shared_expert_primary,
		"dense_primary": dense_primary,
	}
	if expert_primary and expert_primary.get("type") == "MXFP4":
		hints["flash_variant_hint"] = {"flash_like": True, "reason": "expert weights appear primarily MXFP4 (matches Flash expert_dtype=fp4)"}

	return {
		"checked": True,
		"namespace_guess": namespace_guess,
		"general_architecture": arch,
		"category_type_counts": {k: dict(sorted(v.items())) for k, v in sorted(category_counts.items())},
		"hints": hints,
	}


def compute_quantization_contract_hint(
	tensor_type_profile: Optional[dict[str, Any]],
	contract_summary: Optional[dict[str, Any]],
) -> Optional[dict[str, Any]]:
	if not (isinstance(tensor_type_profile, dict) and tensor_type_profile.get("checked") is True):
		return None
	if not isinstance(contract_summary, dict):
		return None

	q = contract_summary.get("quantization", {})
	inf_q = q.get("inference_config", {}) if isinstance(q, dict) else {}
	if not isinstance(inf_q, dict):
		return None

	expected_dense = inf_q.get("dtype", None)
	expected_expert = inf_q.get("expert_dtype", None)
	expected_scale_fmt = inf_q.get("scale_fmt", None)

	hints = tensor_type_profile.get("hints", {})
	if not isinstance(hints, dict):
		hints = {}

	def _hint_primary_type(name: str) -> Optional[str]:
		v = hints.get(name, None)
		if not isinstance(v, dict):
			return None
		t = v.get("type", None)
		return t if isinstance(t, str) and t else None

	obs_dense_type = _hint_primary_type("dense_primary")
	obs_expert_type = _hint_primary_type("expert_primary")

	def _fp8_like(t: Optional[str]) -> Optional[bool]:
		if t is None:
			return None
		if t.startswith("F8_E4M3"):
			return True
		return False

	def _fp4_like(t: Optional[str]) -> Optional[bool]:
		if t is None:
			return None
		if t == "MXFP4":
			return True
		return False

	expert_like = _fp4_like(obs_expert_type) if expected_expert == "fp4" else None
	dense_like = _fp8_like(obs_dense_type) if expected_dense == "fp8" else None

	notes: list[str] = []
	if expected_expert == "fp4" and expert_like is False:
		notes.append(
			f"expected Flash experts fp4; artifact expert primary type is {obs_expert_type!r} (likely re-quantized or non-native conversion)"
		)
	if expected_dense == "fp8" and dense_like is False:
		notes.append(
			f"expected Flash trunk fp8; artifact dense primary type is {obs_dense_type!r} (likely re-quantized or non-native conversion)"
		)
	if expected_scale_fmt is not None:
		notes.append(f"scale_fmt is source-derived as {expected_scale_fmt!r}; GGUF headers typically do not encode scale-tensor semantics")

	return {
		"checked": True,
		"expected": {"dense_dtype": expected_dense, "expert_dtype": expected_expert, "scale_fmt": expected_scale_fmt},
		"observed": {"dense_primary_type": obs_dense_type, "expert_primary_type": obs_expert_type},
		"dense_fp8_like": dense_like,
		"expert_fp4_like": expert_like,
		"notes": notes,
	}


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
		return {"checked": False, "reason": "contract_summary missing tensor_keys.required_top_level or tensor_keys.required_layer_suffixes"}
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

	def note_missing_factory(missing_sample_limit: int = 20):
		missing_count = 0
		missing_sample: list[str] = []

		def note_missing(key: str) -> None:
			nonlocal missing_count
			missing_count += 1
			if len(missing_sample) < missing_sample_limit:
				missing_sample.append(key)

		return note_missing, lambda: missing_count, lambda: missing_sample

	def compute_llamacpp_trunk_contract() -> dict[str, Any]:
		# llama.cpp DeepSeek-V4 GGUFs typically use:
		# - token_embd.weight / output.weight / output_norm.weight
		# - per-block tensors under blk.{i}.*
		# These names are not part of the upstream safetensors contract; they are a
		# compatibility signal for interpreting quantized single-Spark artifacts.
		block_ids: set[int] = set()
		for k in weight_keys:
			if not k.startswith("blk."):
				continue
			parts = k.split(".", 2)
			if len(parts) < 2:
				continue
			try:
				block_ids.add(int(parts[1]))
			except ValueError:
				continue

		if not block_ids:
			return {"checked": False, "reason": "no blk.{i}.* tensors present (llama.cpp deepseek4 namespace not detected)"}

		need_top_level = [
			"token_embd.weight",
			"output.weight",
			"output_norm.weight",
		]
		# These HC head tensors are present in many deepseek4 GGUF conversions; treat
		# them as optional soft-signal rather than hard requirements.
		optional_top_level = [
			"hc_head_base",
			"hc_head_fn",
			"hc_head_scale",
		]

		need_block_suffixes = [
			"attn_norm.weight",
			"attn_q_a.weight",
			"attn_q_a_norm.weight",
			"attn_q_b.weight",
			"attn_kv_a_norm.weight",
			"attn_output_a.weight",
			"attn_output_b.weight",
			"ffn_norm.weight",
			"ffn_gate_inp.weight",
			"ffn_gate_exps.weight",
			"ffn_gate_shexp.weight",
			"ffn_up_exps.weight",
			"ffn_up_shexp.weight",
			"ffn_down_exps.weight",
			"ffn_down_shexp.weight",
		]

		note_missing, get_missing_count, get_missing_sample = note_missing_factory()

		for k in need_top_level:
			if k not in weight_keys:
				note_missing(k)

		optional_missing = []
		for k in optional_top_level:
			if k not in weight_keys:
				optional_missing.append(k)

		for i in range(n_layers_i):
			prefix = f"blk.{i}."
			for suffix in need_block_suffixes:
				need = prefix + suffix
				if need not in weight_keys:
					note_missing(need)

		present_sorted = sorted(block_ids)
		expected_block_ids = list(range(n_layers_i))
		missing_blocks = [i for i in expected_block_ids if i not in block_ids]
		extra_blocks = [i for i in present_sorted if i not in set(expected_block_ids)]

		notes = []
		if optional_missing:
			notes.append(f"optional_top_level_missing={optional_missing}")
		if missing_blocks:
			notes.append(f"missing_block_ids={missing_blocks[:20]}")
		if extra_blocks:
			notes.append(f"extra_block_ids={extra_blocks[:20]}")

		missing_count = int(get_missing_count())
		forbidden_sorted: list[str] = []
		return {
			"checked": True,
			"kind": "llama.cpp",
			"complete": (missing_count == 0 and len(forbidden_sorted) == 0 and not missing_blocks),
			"n_layers_checked": n_layers_i,
			"block_ids_present_sample": present_sorted[:20],
			"missing_required_count": missing_count,
			"missing_required_sample": get_missing_sample(),
			"forbidden_present": forbidden_sorted,
			"notes": notes,
		}

	# Most GGUF conversion toolchains rename layer tensor keys; only run this
	# check when the artifact appears to preserve the upstream `layers.{i}.*`
	# namespace.
	if not any(k.startswith("layers.") for k in weight_keys):
		if any(k.startswith("blk.") for k in weight_keys):
			return compute_llamacpp_trunk_contract()
		return {
			"checked": False,
			"reason": "artifact tensor keys do not appear to preserve DeepSeek upstream `layers.{i}.*` namespace; trunk_contract check not applicable",
		}

	forbidden_present: set[str] = set()

	note_missing, get_missing_count, get_missing_sample = note_missing_factory()

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
	missing_count = int(get_missing_count())
	return {
		"checked": True,
		"kind": "deepseek-upstream",
		"complete": (missing_count == 0 and len(forbidden_sorted) == 0),
		"n_layers_checked": n_layers_i,
		"missing_required_count": missing_count,
		"missing_required_sample": get_missing_sample(),
		"forbidden_present": forbidden_sorted,
	}


def compute_topology_contract(metadata: dict[str, Any], contract_summary: dict[str, Any]) -> dict[str, Any]:
	if not metadata:
		return {"checked": False, "reason": "no metadata captured from artifact header"}

	topo = contract_summary.get("topology", {})
	mtp = contract_summary.get("mtp", {})
	yarn = contract_summary.get("yarn_rope", {})

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
	expected_rope_dim = expected_int("rope_head_dim")
	try:
		expected_rope_theta = float(yarn.get("rope_theta"))
	except Exception:
		expected_rope_theta = None
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

	def pick_float(keys: list[str]) -> Optional[float]:
		for k in keys:
			v = metadata.get(k, None)
			try:
				return float(v)
			except Exception:
				continue
		return None

	embedding_keys = [k for k in metadata.keys() if k.endswith(".embedding_length")]
	block_keys = [k for k in metadata.keys() if k.endswith(".block_count")]
	vocab_keys = [k for k in metadata.keys() if k.endswith(".vocab_size")]
	head_keys = [k for k in metadata.keys() if k.endswith(".head_count")]
	kv_head_keys = [k for k in metadata.keys() if k.endswith(".head_count_kv")]
	rope_dim_keys = [k for k in metadata.keys() if k.endswith(".rope.dimension_count")]
	rope_freq_base_keys = [k for k in metadata.keys() if k.endswith(".rope.freq_base")]

	embedding_len = pick_int(sorted(embedding_keys))
	block_count = pick_int(sorted(block_keys))
	vocab_size = pick_int(sorted(vocab_keys))
	head_count = pick_int(sorted(head_keys))
	kv_head_count = pick_int(sorted(kv_head_keys))
	rope_dim = pick_int(sorted(rope_dim_keys))
	rope_freq_base = pick_float(sorted(rope_freq_base_keys))

	mismatches: list[str] = []

	def check_eq(label: str, got: Optional[int], expected: Optional[int]) -> None:
		if got is None or expected is None:
			return
		if int(got) != int(expected):
			mismatches.append(f"{label}: got={got} expected={expected}")

	def check_eq_float(label: str, got: Optional[float], expected: Optional[float]) -> None:
		if got is None or expected is None:
			return
		if float(got) != float(expected):
			mismatches.append(f"{label}: got={got} expected={expected}")

	check_eq("embedding_length", embedding_len, expected_hidden)
	check_eq("vocab_size", vocab_size, expected_vocab)
	check_eq("head_count", head_count, expected_heads)
	check_eq("head_count_kv", kv_head_count, expected_kv_heads)
	check_eq("rope_dimension_count", rope_dim, expected_rope_dim)
	check_eq_float("rope_freq_base", rope_freq_base, expected_rope_theta)

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
		"rope_dimension_count": rope_dim,
		"rope_freq_base": rope_freq_base,
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
		return {"checked": False, "reason": "contract_summary missing tensor_keys.required_layer_suffixes or tensor_keys.required_mtp_additional_suffixes"}
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


def compute_mtp_namespace_status(mtp_layer_ids: list[int], contract_summary: Optional[dict[str, Any]]) -> dict[str, Any]:
	present_ids: list[int] = sorted({int(i) for i in mtp_layer_ids})
	present_prefixes = [f"mtp.{i}." for i in present_ids]

	expected_ids: list[int] = []
	if isinstance(contract_summary, dict):
		try:
			n_mtp_layers = int(contract_summary.get("mtp", {}).get("n_mtp_layers", 0))
		except Exception:
			n_mtp_layers = 0
		if n_mtp_layers > 0:
			expected_ids = list(range(int(n_mtp_layers)))

	missing_expected_ids = [i for i in expected_ids if i not in present_ids]
	return {
		"checked": True,
		"present_layer_ids": present_ids,
		"present_prefixes": present_prefixes,
		"has_mtp0": (0 in present_ids),
		"expected_layer_ids": expected_ids,
		"missing_expected_layer_ids": missing_expected_ids,
		"expected_complete": (len(expected_ids) > 0 and len(missing_expected_ids) == 0),
	}

def compute_mtp_trust(mtp_present: bool, mtp_contract: Optional[dict[str, Any]], contract_summary: Optional[dict[str, Any]]) -> dict[str, Any]:
	if not mtp_present:
		return {"checked": True, "trusted": False, "status": "absent", "reasons": ["no mtp.* tensors present"]}

	if not isinstance(mtp_contract, dict) or mtp_contract.get("checked") is not True:
		return {"checked": False, "trusted": False, "status": "unknown", "reasons": ["mtp_contract not checked"]}

	trust_gates = None
	if isinstance(contract_summary, dict):
		trust_gates = contract_summary.get("mtp", {}).get("trust_gates", None)
	if not isinstance(trust_gates, dict):
		trust_gates = {}

	# Namespace contract: MTP must preserve the expected `mtp.{j}.` prefixes (and
	# include mtp.0.* when the contract expects mtp ids starting at 0).
	if isinstance(contract_summary, dict):
		ids = mtp_contract.get("mtp_layer_ids_present", [])
		if isinstance(ids, list):
			ns = compute_mtp_namespace_status(ids, contract_summary)
			if trust_gates.get("artifact_requires_mtp_namespace_expected_complete") is True and ns.get("expected_complete") is not True:
				missing = ns.get("missing_expected_layer_ids", [])
				return {
					"checked": True,
					"trusted": False,
					"status": "namespace_incomplete",
					"reasons": [f"mtp_namespace.expected_complete != true (missing_expected_layer_ids={missing})"],
				}
			if trust_gates.get("artifact_requires_mtp_namespace_has_mtp0") is True and ns.get("has_mtp0") is not True:
				return {
					"checked": True,
					"trusted": False,
					"status": "namespace_missing_mtp0",
					"reasons": ["mtp_namespace.has_mtp0 != true"],
				}

	requires_complete = bool(trust_gates.get("artifact_requires_mtp_contract_complete", True))
	if requires_complete and mtp_contract.get("complete") is not True:
		return {
			"checked": True,
			"trusted": False,
			"status": "incomplete",
			"reasons": ["mtp_contract.complete != true"],
		}

	reasons = ["structural mtp.* keys complete"]
	if trust_gates.get("oracle_requires_include_mtp") is True or trust_gates.get("oracle_requires_mtp_trace") is True:
		reasons.append("requires logits oracle with include_mtp before trusting MTP")

	return {
		"checked": True,
		"trusted": False,
		"status": "structural_complete_untrusted",
		"reasons": reasons,
	}

def compute_mtp_preservation(mtp_present: bool, mtp_namespace: Optional[dict[str, Any]], mtp_contract: Optional[dict[str, Any]]) -> dict[str, Any]:
	if not mtp_present:
		return {"checked": True, "preserves": False, "status": "absent", "reasons": ["no mtp.* tensors present"]}

	if not isinstance(mtp_contract, dict) or mtp_contract.get("checked") is not True:
		return {"checked": False, "preserves": False, "status": "unknown", "reasons": ["mtp_contract not checked"]}

	if isinstance(mtp_namespace, dict):
		expected_ids = mtp_namespace.get("expected_layer_ids", [])
		if isinstance(expected_ids, list) and len(expected_ids) > 0:
			if mtp_namespace.get("expected_complete") is not True:
				missing = mtp_namespace.get("missing_expected_layer_ids", [])
				return {
					"checked": True,
					"preserves": False,
					"status": "namespace_incomplete",
					"reasons": [f"mtp_namespace.expected_complete != true (missing_expected_layer_ids={missing})"],
				}
			if mtp_namespace.get("has_mtp0") is not True:
				return {
					"checked": True,
					"preserves": False,
					"status": "namespace_missing_mtp0",
					"reasons": ["mtp_namespace.has_mtp0 != true"],
				}

	if mtp_contract.get("complete") is not True:
		return {"checked": True, "preserves": False, "status": "incomplete", "reasons": ["mtp_contract.complete != true"]}

	return {"checked": True, "preserves": True, "status": "complete", "reasons": ["mtp.* keys satisfy upstream contract"]}


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
		40: "NVFP4",
		41: "Q1_0",
	}

	with path.open("rb") as f:
		vers, metadata, weight_keys, weight_types = parse_gguf_stream(f, str(path))

	def ggml_type_name(code: int) -> str:
		# Some DeepSeek-V4-capable forks extend ggml_type beyond upstream gguf spec.
		# Example: nsparks' DeepSeek-V4-Flash native FP4/FP8 GGUF uses type code 42 for F8_E4M3_B128.
		if code == 42:
			arch = metadata.get("general.architecture", None)
			if arch == "deepseek4":
				return "F8_E4M3_B128"
		return ggml_type_names.get(code, f"TYPE_{code}")

	type_counts = Counter(ggml_type_name(t) for t in weight_types)
	mtp_type_counts = Counter(ggml_type_name(t) for k, t in zip(weight_keys, weight_types) if k.startswith("mtp."))
	profile = compute_tensor_type_profile(weight_keys, weight_types, metadata, ggml_type_name)
	res = inspect_weight_keys(weight_keys, str(path), "gguf")
	return InspectResult(
		path=res.path,
		artifact_type=res.artifact_type,
		gguf_version=vers,
		url_prefix_bytes=None,
		metadata=metadata,
		tensor_count=res.tensor_count,
		tensor_type_counts=dict(sorted(type_counts.items())),
		tensor_type_profile=profile,
		weight_keys_all=res.weight_keys_all,
		mtp_present=res.mtp_present,
		mtp_tensor_count=res.mtp_tensor_count,
		mtp_tensor_type_counts=dict(sorted(mtp_type_counts.items())),
		mtp_layer_ids=res.mtp_layer_ids,
		first_mtp_keys=res.first_mtp_keys,
		mtp_keys_all=res.mtp_keys_all,
	)


def inspect_gguf_url(url: str, max_bytes: int, timeout_s: int) -> InspectResult:
	# See inspect_gguf for ggml_type mapping.
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
		40: "NVFP4",
		41: "Q1_0",
	}

	vers, metadata, weight_keys, weight_types, prefix_bytes = parse_gguf_url_prefix(url, max_bytes=max_bytes, timeout_s=timeout_s)

	def ggml_type_name(code: int) -> str:
		# See inspect_gguf note: DeepSeek-V4-capable forks may extend ggml_type beyond upstream gguf spec.
		if code == 42:
			arch = metadata.get("general.architecture", None)
			if arch == "deepseek4":
				return "F8_E4M3_B128"
		return ggml_type_names.get(code, f"TYPE_{code}")

	type_counts = Counter(ggml_type_name(t) for t in weight_types)
	mtp_type_counts = Counter(ggml_type_name(t) for k, t in zip(weight_keys, weight_types) if k.startswith("mtp."))
	profile = compute_tensor_type_profile(weight_keys, weight_types, metadata, ggml_type_name)
	res = inspect_weight_keys(weight_keys, url, "gguf.url")
	return InspectResult(
		path=res.path,
		artifact_type=res.artifact_type,
		gguf_version=vers,
		url_prefix_bytes=int(prefix_bytes),
		metadata=metadata,
		tensor_count=res.tensor_count,
		tensor_type_counts=dict(sorted(type_counts.items())),
		tensor_type_profile=profile,
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
		default=[],
		help="Quantized artifact path: .gguf, model.safetensors.index.json, or a directory containing it. May be passed multiple times (e.g. trunk + MTP sidecar).",
	)
	parser.add_argument(
		"--url",
		type=str,
		action="append",
		default=[],
		help="HTTP(S) URL to a GGUF file; downloads only the header/tensor table via range reads. May be passed multiple times (e.g. trunk + MTP sidecar).",
	)
	parser.add_argument("--json", action="store_true", help="Emit machine-readable JSON output.")
	parser.add_argument("--require-mtp", action="store_true", help="Exit non-zero if no mtp.* tensors are present.")
	parser.add_argument(
		"--require-mtp-complete",
		action="store_true",
		help="Exit non-zero unless mtp.* tensors satisfy the upstream MTP contract (requires --contract-summary or repo default).",
	)
	parser.add_argument(
		"--contract-summary",
		type=str,
		default=None,
		help="Optional path to a DeepSeek V4 Flash contract_summary.json. When provided (or when the repo default exists), emits an mtp_contract completeness check for mtp.* tensor keys.",
	)
	parser.add_argument("--max-bytes", type=int, default=(16 * 1024 * 1024), help="Max bytes to fetch per --url (default: 16777216).")
	parser.add_argument("--timeout-s", type=int, default=20, help="HTTP timeout seconds for --url (default: 20).")
	args = parser.parse_args()

	if not args.path and not args.url:
		print("ERROR: must provide at least one --path or --url")
		return 2

	results: list[InspectResult] = []
	for p in args.path:
		try:
			results.append(detect_and_inspect(Path(p)))
		except Exception as e:
			print(f"ERROR: {e}")
			return 2
	for u in args.url:
		try:
			if not str(u).lower().endswith(".gguf"):
				raise ValueError(f"unsupported --url artifact type for {u} (expected .gguf)")
			results.append(inspect_gguf_url(str(u), max_bytes=int(args.max_bytes), timeout_s=int(args.timeout_s)))
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

	def as_dict(res: InspectResult) -> dict[str, Any]:
		namespace_guess, namespace_evidence = guess_tensor_key_namespace(res.weight_keys_all)
		mtp_namespace = compute_mtp_namespace_status(res.mtp_layer_ids, contract_summary)
		out = {
			"path": res.path,
			"artifact_type": res.artifact_type,
			"gguf_version": res.gguf_version,
			"url_prefix_bytes": res.url_prefix_bytes,
			"metadata": res.metadata,
			"tensor_count": res.tensor_count,
			"tensor_type_counts": res.tensor_type_counts,
			"first_tensor_keys": res.weight_keys_all[:20],
			"tensor_key_namespace_guess": namespace_guess,
			"tensor_key_namespace_evidence": namespace_evidence,
			"mtp_present": res.mtp_present,
			"mtp_tensor_count": res.mtp_tensor_count,
			"mtp_tensor_type_counts": res.mtp_tensor_type_counts,
			"mtp_layer_ids": res.mtp_layer_ids,
			"mtp_namespace": mtp_namespace,
			"first_mtp_keys": res.first_mtp_keys,
		}
		if res.tensor_type_profile is not None:
			out["tensor_type_profile"] = res.tensor_type_profile
			qh = compute_quantization_contract_hint(res.tensor_type_profile, contract_summary)
			if qh is not None:
				out["quantization_contract"] = qh
		return out

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
		trunk_contract = None
		topology_contract = None
		quantization_contract = None
		mtp_namespace = compute_mtp_namespace_status(sorted(mtp_layer_ids), contract_summary)
		if contract_summary is not None:
			mtp_contract = compute_mtp_contract(mtp_keys_union, contract_summary)
			trunk_contract = compute_trunk_contract(weight_keys_union, contract_summary)
			if topology_candidate is not None:
				topology_contract = compute_topology_contract(topology_candidate.metadata, contract_summary)
			if topology_candidate is not None:
				quantization_contract = compute_quantization_contract_hint(topology_candidate.tensor_type_profile, contract_summary)
		mtp_trust = compute_mtp_trust(any(r.mtp_present for r in results), mtp_contract, contract_summary)
		mtp_preservation = compute_mtp_preservation(any(r.mtp_present for r in results), mtp_namespace, mtp_contract)
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
			"mtp_namespace": mtp_namespace,
			"first_mtp_keys": first_mtp_keys,
			"mtp_contract": mtp_contract,
			"mtp_trust": mtp_trust,
			"mtp_preservation": mtp_preservation,
			"trunk_contract": trunk_contract,
			"topology_contract_source_path": (None if topology_candidate is None else topology_candidate.path),
			"topology_contract": topology_contract,
			"quantization_contract_source_path": (None if topology_candidate is None else topology_candidate.path),
			"quantization_contract": quantization_contract,
		}

	if args.json:
		if len(results) == 1:
			out = as_dict(results[0])
			if contract_summary is not None:
				out["mtp_contract"] = compute_mtp_contract(set(results[0].mtp_keys_all), contract_summary)
				out["mtp_trust"] = compute_mtp_trust(bool(out.get("mtp_present", False)), out.get("mtp_contract"), contract_summary)
				out["mtp_preservation"] = compute_mtp_preservation(bool(out.get("mtp_present", False)), out.get("mtp_namespace"), out.get("mtp_contract"))
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
									{}
									if contract_summary is None
									else {
										"mtp_contract": compute_mtp_contract(set(r.mtp_keys_all), contract_summary),
										"mtp_trust": compute_mtp_trust(bool(r.mtp_present), compute_mtp_contract(set(r.mtp_keys_all), contract_summary), contract_summary),
										"mtp_preservation": compute_mtp_preservation(bool(r.mtp_present), compute_mtp_namespace_status(r.mtp_layer_ids, contract_summary), compute_mtp_contract(set(r.mtp_keys_all), contract_summary)),
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
			mtp_preservation = combined.get("mtp_preservation", None)
			if isinstance(mtp_preservation, dict) and mtp_preservation.get("checked") is True:
				print(f"mtp_preservation_status: {mtp_preservation.get('status')}")
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
				mtp_contract = compute_mtp_contract(set(res.mtp_keys_all), contract_summary)
				if mtp_contract.get("checked") is True:
					print(f"mtp_contract_complete: {str(bool(mtp_contract.get('complete', False))).lower()}")
					print(f"mtp_contract_missing_required_count: {int(mtp_contract.get('missing_required_count', 0))}")
					for k in list(mtp_contract.get("missing_required_sample", []))[:10]:
						print(f"mtp_contract_missing_required: {k}")
					for k in list(mtp_contract.get("forbidden_present", []))[:10]:
						print(f"mtp_contract_forbidden_present: {k}")
				mtp_namespace = compute_mtp_namespace_status(res.mtp_layer_ids, contract_summary)
				mtp_preservation = compute_mtp_preservation(bool(res.mtp_present), mtp_namespace, mtp_contract)
				if isinstance(mtp_preservation, dict) and mtp_preservation.get("checked") is True:
					print(f"mtp_preservation_status: {mtp_preservation.get('status')}")
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

	if args.require_mtp_complete:
		if contract_summary is None:
			print("ERROR: --require-mtp-complete requires a DeepSeek V4 Flash contract_summary.json (use --contract-summary or run from the repo).")
			return 2
		combined = combine(results)
		mtp_preservation = combined.get("mtp_preservation", None)
		if not isinstance(mtp_preservation, dict) or mtp_preservation.get("checked") is not True:
			print("ERROR: unable to compute mtp_preservation (contract missing or artifact missing mtp keys)")
			return 2
		if mtp_preservation.get("preserves") is not True:
			return 1
		return 0
	return 0


if __name__ == "__main__":
	raise SystemExit(main())
