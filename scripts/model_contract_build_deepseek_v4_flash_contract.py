#!/usr/bin/env python3

import argparse
import ast
import json
from collections import Counter
from hashlib import sha256
from pathlib import Path
from typing import Optional


ROOT = Path(__file__).resolve().parents[1]
FIX = ROOT / "fixtures" / "model_contract" / "deepseek_v4_flash"
DEFAULT_OUT = FIX / "contract_summary.json"
INFERENCE_MODEL_PY = FIX / "inference" / "model.py"
ENCODING_PY = FIX / "encoding" / "encoding_dsv4.py"


def load_json(path: Path):
	with path.open("r", encoding="utf-8") as f:
		return json.load(f)


def dump_json(path: Path, obj) -> None:
	path.parent.mkdir(parents=True, exist_ok=True)
	tmp = path.with_suffix(path.suffix + ".tmp")
	with tmp.open("w", encoding="utf-8") as f:
		json.dump(obj, f, indent=2, sort_keys=True)
		f.write("\n")
	tmp.replace(path)

def sha256_file(path: Path) -> str:
	h = sha256()
	with path.open("rb") as f:
		for chunk in iter(lambda: f.read(1024 * 1024), b""):
			h.update(chunk)
	return h.hexdigest()

def sha256_lines(lines: list[str]) -> str:
	h = sha256()
	for line in lines:
		h.update(line.encode("utf-8"))
		h.update(b"\n")
	return h.hexdigest()

def parse_encoding_constants(encoding_py: Path) -> dict:
	if not encoding_py.exists():
		return {"encoding_constants": None}

	text = encoding_py.read_text(encoding="utf-8")

	try:
		mod = ast.parse(text, filename=str(encoding_py))
	except SyntaxError:
		return {"encoding_constants": None}

	assigns: dict[str, ast.AST] = {}
	for node in mod.body:
		if isinstance(node, ast.Assign) and len(node.targets) == 1 and isinstance(node.targets[0], ast.Name):
			assigns[node.targets[0].id] = node.value
		if isinstance(node, ast.AnnAssign) and isinstance(node.target, ast.Name):
			assigns[node.target.id] = node.value

	env: dict[str, object] = {}

	def eval_expr(expr: Optional[ast.AST]) -> object:
		if expr is None:
			return None
		if isinstance(expr, ast.Constant):
			return expr.value
		if isinstance(expr, ast.Name):
			return env.get(expr.id, None)
		if isinstance(expr, ast.BinOp) and isinstance(expr.op, ast.Add):
			l = eval_expr(expr.left)
			r = eval_expr(expr.right)
			if isinstance(l, str) and isinstance(r, str):
				return l + r
			return None
		if isinstance(expr, ast.Dict):
			out: dict[object, object] = {}
			for k, v in zip(expr.keys, expr.values):
				kk = eval_expr(k)
				vv = eval_expr(v)
				out[kk] = vv
			return out
		return None

	for _ in range(8):
		progress = False
		for name, expr in assigns.items():
			if name in env:
				continue
			v = eval_expr(expr)
			if v is None:
				continue
			env[name] = v
			progress = True
		if not progress:
			break

	def str_or_none(v: object) -> Optional[str]:
		return v if isinstance(v, str) else None

	def dict_str_str_or_none(v: object) -> Optional[dict[str, str]]:
		if not isinstance(v, dict):
			return None
		out: dict[str, str] = {}
		for kk, vv in v.items():
			if not isinstance(kk, str) or not isinstance(vv, str):
				return None
			out[kk] = vv
		return out

	return {
		"encoding_constants": {
			"bos_token": str_or_none(env.get("bos_token")),
			"eos_token": str_or_none(env.get("eos_token")),
			"thinking_start_token": str_or_none(env.get("thinking_start_token")),
			"thinking_end_token": str_or_none(env.get("thinking_end_token")),
			"dsml_token": str_or_none(env.get("dsml_token")),
			"user_sp_token": str_or_none(env.get("USER_SP_TOKEN")),
			"assistant_sp_token": str_or_none(env.get("ASSISTANT_SP_TOKEN")),
			"latest_reminder_sp_token": str_or_none(env.get("LATEST_REMINDER_SP_TOKEN")),
			"ds_task_sp_tokens": dict_str_str_or_none(env.get("DS_TASK_SP_TOKENS")),
			"system_msg_template": str_or_none(env.get("system_msg_template")),
			"user_msg_template": str_or_none(env.get("user_msg_template")),
			"latest_reminder_msg_template": str_or_none(env.get("latest_reminder_msg_template")),
			"assistant_msg_template": str_or_none(env.get("assistant_msg_template")),
			"assistant_msg_wo_eos_template": str_or_none(env.get("assistant_msg_wo_eos_template")),
			"thinking_template": str_or_none(env.get("thinking_template")),
			"tool_calls_block_name": str_or_none(env.get("tool_calls_block_name")),
			"tool_call_template": str_or_none(env.get("tool_call_template")),
			"tool_calls_template": str_or_none(env.get("tool_calls_template")),
			"tool_output_template": str_or_none(env.get("tool_output_template")),
		}
	}

def parse_tokenizer_json_summary(tokenizer_json: Path, expected_vocab_size: int) -> dict:
	if not tokenizer_json.exists():
		return {"tokenizer_json_summary": None}

	try:
		tok = load_json(tokenizer_json)
	except Exception:
		return {"tokenizer_json_summary": None}

	model = tok.get("model", {}) if isinstance(tok, dict) else {}
	model_type = model.get("type") if isinstance(model, dict) else None
	vocab = model.get("vocab") if isinstance(model, dict) else None
	merges = model.get("merges") if isinstance(model, dict) else None

	base_vocab_size: Optional[int] = None
	if isinstance(vocab, dict):
		base_vocab_size = int(len(vocab))

	merges_count: Optional[int] = None
	if isinstance(merges, list):
		merges_count = int(len(merges))

	added_tokens = tok.get("added_tokens") if isinstance(tok, dict) else None
	added_tokens_count: Optional[int] = None
	added_special_tokens_count: Optional[int] = None
	added_id_min: Optional[int] = None
	added_id_max: Optional[int] = None
	if isinstance(added_tokens, list):
		added_tokens_count = int(len(added_tokens))
		added_special_tokens_count = int(sum(1 for t in added_tokens if isinstance(t, dict) and t.get("special") is True))
		ids: list[int] = [int(t["id"]) for t in added_tokens if isinstance(t, dict) and isinstance(t.get("id"), int)]
		if ids:
			added_id_min = int(min(ids))
			added_id_max = int(max(ids))

	effective_vocab_size: Optional[int] = None
	if isinstance(base_vocab_size, int):
		effective_vocab_size = int(base_vocab_size)
		if isinstance(added_id_max, int):
			effective_vocab_size = int(max(effective_vocab_size, added_id_max + 1))

	def summarize_tok_component(node: object) -> Optional[dict]:
		if not isinstance(node, dict):
			return None
		t = node.get("type")
		if not isinstance(t, str):
			return None
		out: dict[str, object] = {"type": t}
		if t == "Sequence":
			items = node.get("normalizers")
			if items is None:
				items = node.get("pretokenizers")
			if isinstance(items, list):
				out["sequence"] = [summarize_tok_component(c) for c in items]
		elif t == "Split":
			pat = node.get("pattern", {})
			pat_re = None
			if isinstance(pat, dict):
				pat_re = pat.get("Regex")
			out["pattern_regex"] = pat_re
			out["behavior"] = node.get("behavior")
			out["invert"] = node.get("invert")
		elif t == "ByteLevel":
			for k in ("add_prefix_space", "trim_offsets", "use_regex"):
				if k in node:
					out[k] = node.get(k)
		return out

	return {
		"tokenizer_json_summary": {
			"tokenizers_json_version": tok.get("version"),
			"model_type": model_type,
			"base_vocab_size": base_vocab_size,
			"merges_count": merges_count,
			"added_tokens_count": added_tokens_count,
			"added_special_tokens_count": added_special_tokens_count,
			"added_token_id_min": added_id_min,
			"added_token_id_max": added_id_max,
			"effective_vocab_size": effective_vocab_size,
			"effective_vocab_size_matches_config": (effective_vocab_size == int(expected_vocab_size)) if isinstance(effective_vocab_size, int) else None,
			"normalizer": summarize_tok_component(tok.get("normalizer")),
			"pre_tokenizer": summarize_tok_component(tok.get("pre_tokenizer")),
			"post_processor": summarize_tok_component(tok.get("post_processor")),
			"decoder": summarize_tok_component(tok.get("decoder")),
		}
	}


def layer_type_from_ratio(ratio: int) -> str:
	if ratio == 0:
		return "sliding"
	if ratio == 4:
		return "csa"
	return "hca"

def find_first_line_containing(text: str, needle: str) -> Optional[str]:
	for raw in text.splitlines():
		if needle in raw:
			return raw.strip()
	return None

def parse_inference_mla_and_cache_semantics(model_py: Path) -> dict:
	text = model_py.read_text(encoding="utf-8")

	q_extra_norm = find_first_line_containing(text, "q *= torch.rsqrt(")
	o_derotate = find_first_line_containing(text, "apply_rotary_emb(o[..., -rd:], freqs_cis, True)")
	rope_q = find_first_line_containing(text, "apply_rotary_emb(q[..., -rd:], freqs_cis)")
	rope_kv = find_first_line_containing(text, "apply_rotary_emb(kv[..., -rd:], freqs_cis)")
	kv_decode_ring = find_first_line_containing(text, "start_pos % win")
	kv_decode_compress = find_first_line_containing(text, "start_pos // ratio")
	kv_prefill_wrap = find_first_line_containing(text, "cutoff = seqlen % win")

	return {
		"mla": {
			"rope_slice_rule": "RoPE applies to trailing rope_head_dim dims via x[..., -rope_head_dim:]",
			"q_extra_rms_norm_present": q_extra_norm is not None,
			"q_extra_rms_norm_expr": q_extra_norm,
			"output_derotate_present": o_derotate is not None,
			"output_derotate_expr": o_derotate,
			"q_rope_apply_expr": rope_q,
			"kv_rope_apply_expr": rope_kv,
		},
		"cache_update_semantics": {
			"decode_sliding_ring_update_expr": kv_decode_ring,
			"decode_compressed_update_expr": kv_decode_compress,
			"prefill_sliding_wrap_expr": kv_prefill_wrap,
		},
	}

def parse_inference_moe_semantics(model_py: Path) -> dict:
	text = model_py.read_text(encoding="utf-8")
	score_fp32 = find_first_line_containing(text, "scores = linear(x.float(), self.weight.float())")
	bias_comment = find_first_line_containing(text, "Bias shifts scores for expert selection")
	weights_norm = find_first_line_containing(text, "weights /= weights.sum")
	weights_scale = find_first_line_containing(text, "weights *= self.route_scale")
	score_softmax = find_first_line_containing(text, "scores = scores.softmax")
	score_sigmoid = find_first_line_containing(text, "scores = scores.sigmoid")
	score_sqrtsoftplus = find_first_line_containing(text, "scores = F.softplus(scores).sqrt()")
	expert_fp32 = find_first_line_containing(text, "gate = self.w1(x).float()")

	return {
		"gate_scores_fp32_expr": score_fp32,
		"bias_affects_selection_only_comment": bias_comment,
		"weights_normalize_expr": weights_norm,
		"weights_scale_expr": weights_scale,
		"score_func_exprs": {
			"softmax": score_softmax,
			"sigmoid": score_sigmoid,
			"sqrtsoftplus": score_sqrtsoftplus,
		},
		"expert_compute_fp32_expr": expert_fp32,
	}

def parse_inference_moe_hash_routing(model_py: Path) -> dict:
	text = model_py.read_text(encoding="utf-8")
	hash_enable = find_first_line_containing(text, "self.hash = layer_id < args.n_hash_layers")
	tid2eid_decl = find_first_line_containing(text, "self.tid2eid = nn.Parameter")
	hash_indices = find_first_line_containing(text, "indices = self.tid2eid")
	bias_none = find_first_line_containing(text, "self.bias = None")

	return {
		"hash_enabled_expr": hash_enable,
		"tid2eid_decl_expr": tid2eid_decl,
		"hash_indices_expr": hash_indices,
		"bias_none_expr": bias_none,
	}

def kv_cache_size(window_size: int, max_seq_len: int, compress_ratio: int) -> int:
	if compress_ratio == 0:
		return int(window_size)
	return int(window_size + (int(max_seq_len) // int(compress_ratio)))


def parse_inference_quant_constants(model_py: Path) -> dict:
	text = model_py.read_text(encoding="utf-8")

	def modelargs_defaults() -> dict:
		in_model_args = False
		out: dict[str, Optional[int]] = {"max_batch_size": None, "max_seq_len": None}
		for raw in text.splitlines():
			line = raw.strip()
			if line.startswith("class ModelArgs"):
				in_model_args = True
				continue
			if in_model_args and line.startswith("class ") and not line.startswith("class ModelArgs"):
				break
			if not in_model_args:
				continue
			if not line.startswith(("max_batch_size:", "max_seq_len:")):
				continue
			if " = " not in line:
				continue
			field = line.split(":", 1)[0].strip()
			rhs = line.split("=", 1)[1].strip()
			try:
				out[field] = int(rhs)
			except ValueError:
				out[field] = None
		return out

	def find_dataclass_float(field: str) -> Optional[float]:
		for line in text.splitlines():
			line = line.strip()
			if not line.startswith(field + ":"):
				continue
			if " = " not in line:
				continue
			rhs = line.split("=", 1)[1].strip()
			try:
				return float(rhs)
			except ValueError:
				return None
		return None

	def find_int(name: str) -> Optional[int]:
		for line in text.splitlines():
			line = line.strip()
			if not line.startswith(name + " = "):
				continue
			rhs = line.split("=", 1)[1].strip()
			try:
				return int(rhs)
			except ValueError:
				return None
		return None

	def split_top_level_args(call_args: str) -> list[str]:
		args: list[str] = []
		buf: list[str] = []
		paren = 0
		brack = 0
		brace = 0
		in_quote: Optional[str] = None
		escaped = False
		for ch in call_args:
			if in_quote is not None:
				buf.append(ch)
				if escaped:
					escaped = False
					continue
				if ch == "\\":
					escaped = True
					continue
				if ch == in_quote:
					in_quote = None
				continue

			if ch in ("'", '"'):
				in_quote = ch
				buf.append(ch)
				continue

			if ch == "(":
				paren += 1
			elif ch == ")":
				paren = max(0, paren - 1)
			elif ch == "[":
				brack += 1
			elif ch == "]":
				brack = max(0, brack - 1)
			elif ch == "{":
				brace += 1
			elif ch == "}":
				brace = max(0, brace - 1)

			if ch == "," and paren == 0 and brack == 0 and brace == 0:
				args.append("".join(buf).strip())
				buf = []
				continue
			buf.append(ch)
		if buf:
			args.append("".join(buf).strip())
		return args

	def iter_call_args(src: str, func: str) -> list[list[str]]:
		out: list[list[str]] = []
		needle = func + "("
		i = 0
		while True:
			start = src.find(needle, i)
			if start < 0:
				break
			j = start + len(needle)
			depth = 1
			in_quote: Optional[str] = None
			escaped = False
			buf: list[str] = []
			while j < len(src):
				ch = src[j]
				if in_quote is not None:
					buf.append(ch)
					if escaped:
						escaped = False
					elif ch == "\\":
						escaped = True
					elif ch == in_quote:
						in_quote = None
					j += 1
					continue
				if ch in ("'", '"'):
					in_quote = ch
					buf.append(ch)
					j += 1
					continue
				if ch == "(":
					depth += 1
				elif ch == ")":
					depth -= 1
					if depth == 0:
						break
				buf.append(ch)
				j += 1
			if depth == 0:
				out.append(split_top_level_args("".join(buf)))
				i = j + 1
			else:
				i = start + len(needle)
		return out

	def find_unique_act_quant_group_sizes() -> list[int]:
		sizes: set[int] = set()
		for args in iter_call_args(text, "act_quant"):
			if len(args) < 2:
				continue
			arg0 = args[0].replace(" ", "")
			if ":-rd" not in arg0:
				continue
			try:
				sizes.add(int(args[1]))
			except ValueError:
				continue
		return sorted(sizes)

	def find_line_rhs(prefix: str) -> Optional[str]:
		for raw in text.splitlines():
			line = raw.strip()
			if not line.startswith(prefix):
				continue
			if " = " not in line:
				continue
			return line.split("=", 1)[1].strip()
		return None

	block_size = find_int("block_size")
	fp4_block_size = find_int("fp4_block_size")
	hc_eps = find_dataclass_float("hc_eps")
	defaults = modelargs_defaults()
	kv_act_quant_group_sizes = find_unique_act_quant_group_sizes()
	attn_softmax_scale_expr = find_line_rhs("self.softmax_scale")
	indexer_weights_expr = find_line_rhs("weights")

	return {
		"inference_model_constants": {
			"block_size": block_size,
			"fp4_block_size": fp4_block_size,
			"hc_eps": hc_eps,
			"kv_act_quant_group_sizes": kv_act_quant_group_sizes,
			"attn_softmax_scale_expr": attn_softmax_scale_expr,
			"indexer_weights_expr": indexer_weights_expr,
		},
		"reference_defaults": defaults,
	}


def find_mtp_layer_ids(weight_keys: list[str]) -> list[int]:
	ids = set()
	for k in weight_keys:
		if not k.startswith("mtp."):
			continue
		parts = k.split(".", 2)
		if len(parts) < 2:
			continue
		try:
			ids.add(int(parts[1]))
		except ValueError:
			continue
	return sorted(ids)


def build_tensor_key_summary(weight_keys: list[str], n_layers: int, n_routed_experts: int) -> dict:
	top = Counter(k.split(".", 1)[0] for k in weight_keys)
	mtp0_key_count = sum(1 for k in weight_keys if k.startswith("mtp.0."))
	mtp_embed_present = any(k.startswith("mtp.") and ".embed." in k for k in weight_keys)
	mtp_head_present = any(k.startswith("mtp.") and ".head." in k for k in weight_keys)

	def layer_ids_matching(suffix: str) -> list[int]:
		ids = set()
		for k in weight_keys:
			if not k.startswith("layers."):
				continue
			if not k.endswith(suffix):
				continue
			parts = k.split(".")
			if len(parts) < 2:
				continue
			try:
				i = int(parts[1])
			except ValueError:
				continue
			if 0 <= i < n_layers:
				ids.add(i)
		return sorted(ids)

	return {
		"tensor_key_count": len(weight_keys),
		"namespaces": sorted(top.keys()),
		"top_level_prefix_counts": dict(top),
		"mtp0": {
			"present": mtp0_key_count > 0,
			"tensor_key_count": mtp0_key_count,
		},
		"mtp_shared_embed_head_rule": "MTP blocks share top-level embed/head; mtp.{j}.embed.* and mtp.{j}.head.* are absent in official checkpoints",
		"mtp_embed_present": mtp_embed_present,
		"mtp_head_present": mtp_head_present,
		"mtp_layer_ids": find_mtp_layer_ids(weight_keys),
		"layer_gate": {
			"tid2eid_layer_ids": layer_ids_matching("ffn.gate.tid2eid"),
			"gate_bias_layer_ids": layer_ids_matching("ffn.gate.bias"),
		},
		"expected_expert_key_count_per_layer": int(n_routed_experts) * 6,
		"required_top_level": [
			"embed.weight",
			"norm.weight",
			"head.weight",
			"hc_head_fn",
			"hc_head_base",
			"hc_head_scale",
		],
		"required_layer_suffixes": [
			"attn.attn_sink",
			"attn.wq_a.weight",
			"attn.wq_a.scale",
			"attn.q_norm.weight",
			"attn.wq_b.weight",
			"attn.wq_b.scale",
			"attn.wkv.weight",
			"attn.wkv.scale",
			"attn.kv_norm.weight",
			"attn.wo_a.weight",
			"attn.wo_a.scale",
			"attn.wo_b.weight",
			"attn.wo_b.scale",
			"attn_norm.weight",
			"ffn.gate.weight",
			"ffn.shared_experts.w1.weight",
			"ffn.shared_experts.w1.scale",
			"ffn.shared_experts.w2.weight",
			"ffn.shared_experts.w2.scale",
			"ffn.shared_experts.w3.weight",
			"ffn.shared_experts.w3.scale",
			"ffn_norm.weight",
			"hc_attn_fn",
			"hc_attn_base",
			"hc_attn_scale",
			"hc_ffn_fn",
			"hc_ffn_base",
			"hc_ffn_scale",
		],
		"required_layer_suffixes_compress_ratio_nonzero": [
			"attn.compressor.ape",
			"attn.compressor.norm.weight",
			"attn.compressor.wgate.weight",
			"attn.compressor.wkv.weight",
		],
		"required_layer_suffixes_compress_ratio_4": [
			"attn.indexer.wq_b.weight",
			"attn.indexer.wq_b.scale",
			"attn.indexer.weights_proj.weight",
			"attn.indexer.compressor.ape",
			"attn.indexer.compressor.norm.weight",
			"attn.indexer.compressor.wgate.weight",
			"attn.indexer.compressor.wkv.weight",
		],
		"required_mtp_additional_suffixes": [
			"e_proj.weight",
			"e_proj.scale",
			"h_proj.weight",
			"h_proj.scale",
			"enorm.weight",
			"hnorm.weight",
			"norm.weight",
			"hc_head_fn",
			"hc_head_base",
			"hc_head_scale",
		],
		"mtp_score_gate_tensor_key_suffix": "ffn.gate.bias",
		"hash_gate_tensor_key_suffix": "ffn.gate.tid2eid",
		"score_gate_tensor_key_suffix": "ffn.gate.bias",
		"weight_index_source": "model.safetensors.index.json:weight_map",
	}

def build_compat_mappings() -> dict:
	# Source-derived aliases between:
	# - Transformers-style config.json fields (fixtures/.../config.json)
	# - Upstream reference runtime inference/config.json fields
	# - Canonical contract_summary.json paths used by DS4
	#
	# This is intended for interpreting external runtime logs/configs without guessing semantics.
	fields = [
		{"concept": "vocab_size", "transformers_key": "vocab_size", "inference_key": "vocab_size", "canonical_path": "topology.vocab_size"},
		{"concept": "hidden_size", "transformers_key": "hidden_size", "inference_key": "dim", "canonical_path": "topology.hidden_size"},
		{"concept": "num_hidden_layers", "transformers_key": "num_hidden_layers", "inference_key": "n_layers", "canonical_path": "topology.num_hidden_layers"},
		{"concept": "num_attention_heads", "transformers_key": "num_attention_heads", "inference_key": "n_heads", "canonical_path": "topology.num_attention_heads"},
		{"concept": "num_key_value_heads", "transformers_key": "num_key_value_heads", "inference_key": None, "canonical_path": "topology.num_key_value_heads"},
		{"concept": "head_dim", "transformers_key": "head_dim", "inference_key": "head_dim", "canonical_path": "topology.head_dim"},
		{"concept": "rope_head_dim", "transformers_key": "qk_rope_head_dim", "inference_key": "rope_head_dim", "canonical_path": "topology.rope_head_dim"},
		{"concept": "q_lora_rank", "transformers_key": "q_lora_rank", "inference_key": "q_lora_rank", "canonical_path": "topology.q_lora_rank"},
		{"concept": "o_groups", "transformers_key": "o_groups", "inference_key": "o_groups", "canonical_path": "topology.o_groups"},
		{"concept": "o_lora_rank", "transformers_key": "o_lora_rank", "inference_key": "o_lora_rank", "canonical_path": "topology.o_lora_rank"},
		{"concept": "sliding_window", "transformers_key": "sliding_window", "inference_key": "window_size", "canonical_path": "topology.sliding_window"},
		{"concept": "compress_ratios", "transformers_key": "compress_ratios", "inference_key": "compress_ratios", "canonical_path": "attention_schedule.compress_ratios"},
		{"concept": "moe_inter_dim", "transformers_key": "moe_intermediate_size", "inference_key": "moe_inter_dim", "canonical_path": "moe.moe_inter_dim"},
		{"concept": "n_routed_experts", "transformers_key": "n_routed_experts", "inference_key": "n_routed_experts", "canonical_path": "moe.n_routed_experts"},
		{"concept": "n_shared_experts", "transformers_key": "n_shared_experts", "inference_key": "n_shared_experts", "canonical_path": "moe.n_shared_experts"},
		{"concept": "n_activated_experts", "transformers_key": "num_experts_per_tok", "inference_key": "n_activated_experts", "canonical_path": "moe.n_activated_experts"},
		{"concept": "n_hash_layers", "transformers_key": "num_hash_layers", "inference_key": "n_hash_layers", "canonical_path": "moe.n_hash_layers"},
		{"concept": "route_scale", "transformers_key": "routed_scaling_factor", "inference_key": "route_scale", "canonical_path": "moe.route_scale"},
		{"concept": "scoring_func", "transformers_key": "scoring_func", "inference_key": "score_func", "canonical_path": "moe.scoring_func"},
		{"concept": "num_nextn_predict_layers", "transformers_key": "num_nextn_predict_layers", "inference_key": None, "canonical_path": "mtp.n_mtp_layers"},
		{"concept": "rope_theta", "transformers_key": "rope_theta", "inference_key": "rope_theta", "canonical_path": "yarn_rope.rope_theta"},
		{"concept": "compress_rope_theta", "transformers_key": "compress_rope_theta", "inference_key": "compress_rope_theta", "canonical_path": "yarn_rope.compress_rope_theta"},
		{"concept": "original_seq_len", "transformers_key": "original_max_position_embeddings", "inference_key": "original_seq_len", "canonical_path": "yarn_rope.original_seq_len"},
		{"concept": "rope_factor", "transformers_key": "rope_scaling.factor", "inference_key": "rope_factor", "canonical_path": "yarn_rope.rope_factor"},
		{"concept": "beta_fast", "transformers_key": "rope_scaling.beta_fast", "inference_key": "beta_fast", "canonical_path": "yarn_rope.beta_fast"},
		{"concept": "beta_slow", "transformers_key": "rope_scaling.beta_slow", "inference_key": "beta_slow", "canonical_path": "yarn_rope.beta_slow"},
		{"concept": "dtype", "transformers_key": None, "inference_key": "dtype", "canonical_path": "quantization.inference_config.dtype"},
		{"concept": "expert_dtype", "transformers_key": "expert_dtype", "inference_key": "expert_dtype", "canonical_path": "quantization.inference_config.expert_dtype"},
		{"concept": "scale_fmt", "transformers_key": None, "inference_key": "scale_fmt", "canonical_path": "quantization.inference_config.scale_fmt"},
		{"concept": "quant_method", "transformers_key": "quantization_config.quant_method", "inference_key": None, "canonical_path": "quantization.config_quantization_config.quant_method"},
		{"concept": "quant_fmt", "transformers_key": "quantization_config.fmt", "inference_key": None, "canonical_path": "quantization.config_quantization_config.fmt"},
		{"concept": "activation_scheme", "transformers_key": "quantization_config.activation_scheme", "inference_key": None, "canonical_path": "quantization.config_quantization_config.activation_scheme"},
		{"concept": "scale_fmt_cfg", "transformers_key": "quantization_config.scale_fmt", "inference_key": None, "canonical_path": "quantization.config_quantization_config.scale_fmt"},
		{"concept": "weight_block_size", "transformers_key": "quantization_config.weight_block_size", "inference_key": None, "canonical_path": "quantization.config_quantization_config.weight_block_size"},
	]

	by_transformers_key: dict[str, str] = {}
	by_inference_key: dict[str, str] = {}
	for f in fields:
		tk = f.get("transformers_key", None)
		ik = f.get("inference_key", None)
		cp = str(f.get("canonical_path"))
		if isinstance(tk, str) and tk:
			by_transformers_key[tk] = cp
		if isinstance(ik, str) and ik:
			by_inference_key[ik] = cp

	return {"fields": fields, "by_transformers_key": by_transformers_key, "by_inference_key": by_inference_key}


def build_contract() -> dict:
	cfg = load_json(FIX / "config.json")
	inf = load_json(FIX / "inference" / "config.json")
	tok_cfg = load_json(FIX / "tokenizer_config.json")
	idx = load_json(FIX / "model.safetensors.index.json")
	tok_json_sum = parse_tokenizer_json_summary(FIX / "tokenizer.json", int(cfg["vocab_size"]))
	inf_model = parse_inference_quant_constants(INFERENCE_MODEL_PY) if INFERENCE_MODEL_PY.exists() else {}
	sem = parse_inference_mla_and_cache_semantics(INFERENCE_MODEL_PY) if INFERENCE_MODEL_PY.exists() else {}
	moe_sem = parse_inference_moe_semantics(INFERENCE_MODEL_PY) if INFERENCE_MODEL_PY.exists() else {}
	moe_hash_sem = parse_inference_moe_hash_routing(INFERENCE_MODEL_PY) if INFERENCE_MODEL_PY.exists() else {}
	enc = parse_encoding_constants(ENCODING_PY)

	upstream_commit = (FIX / "upstream_commit.txt").read_text(encoding="utf-8").strip()
	compress_ratios = list(cfg["compress_ratios"])
	n_layers = int(cfg["num_hidden_layers"])
	n_mtp_layers = int(cfg.get("num_nextn_predict_layers", 0))
	mtp_ratios = compress_ratios[n_layers:]
	layer_types = [layer_type_from_ratio(int(r)) for r in compress_ratios[:n_layers]]
	type_counts = {t: layer_types.count(t) for t in ("sliding", "csa", "hca")}

	weight_map = idx.get("weight_map", {})
	weight_keys = sorted(weight_map.keys())
	tensor_keys = build_tensor_key_summary(weight_keys, n_layers, int(cfg["n_routed_experts"]))
	weight_map_files = [str(v) for v in weight_map.values()]
	weight_map_file_counts = Counter(weight_map_files)
	weight_map_keys_sha256 = sha256_lines(weight_keys)

	window_size = int(cfg["sliding_window"])
	ref_defaults = inf_model.get("reference_defaults", {}) if isinstance(inf_model, dict) else {}
	ref_max_seq_len = ref_defaults.get("max_seq_len", None)
	ref_max_batch_size = ref_defaults.get("max_batch_size", None)
	if not isinstance(ref_max_seq_len, int):
		ref_max_seq_len = None
	if not isinstance(ref_max_batch_size, int):
		ref_max_batch_size = None

	kv_cache_sizes_by_layer: Optional[list[int]] = None
	kv_cache_sizes_by_ratio: Optional[dict[str, int]] = None
	kv_cache_slots_total: Optional[int] = None
	kv_cache_slots_mtp_total: Optional[int] = None
	if ref_max_seq_len is not None:
		kv_cache_sizes_by_layer = [kv_cache_size(window_size, ref_max_seq_len, int(r)) for r in compress_ratios[:n_layers]]
		kv_cache_sizes_by_ratio = {str(r): kv_cache_size(window_size, ref_max_seq_len, int(r)) for r in sorted(set(int(x) for x in compress_ratios))}
		kv_cache_slots_total = int(sum(kv_cache_sizes_by_layer))
		if n_mtp_layers > 0:
			kv_cache_slots_mtp_total = int(sum(kv_cache_size(window_size, ref_max_seq_len, int(r)) for r in mtp_ratios))

	block_size = inf_model.get("inference_model_constants", {}).get("block_size", None)
	fp4_block_size = inf_model.get("inference_model_constants", {}).get("fp4_block_size", None)

	fixture_sha = {}
	for rel in (
		"config.json",
		"upstream_commit.txt",
		"generation_config.json",
		"inference/config.json",
		"inference/kernel.py",
		"inference/model.py",
		"model.safetensors.index.json",
		"tokenizer.json",
		"tokenizer_config.json",
		"encoding/encoding_dsv4.py",
	):
		p = FIX / rel
		if p.exists():
			fixture_sha[rel] = sha256_file(p)
	for p in sorted((FIX / "encoding" / "tests").glob("*")):
		if p.is_file():
			fixture_sha[str(p.relative_to(FIX))] = sha256_file(p)
	for rel in (
		"oracle/prompts.json",
	):
		p = FIX / rel
		if p.exists():
			fixture_sha[rel] = sha256_file(p)

	contract = {
		"format_version": 1,
		"model": "deepseek_v4_flash",
		"upstream": {
			"hf_repo_id": "deepseek-ai/DeepSeek-V4-Flash",
			"hf_revision": "main",
			"x_repo_commit": upstream_commit,
			"fixtures_sha256": fixture_sha,
			"fixtures": {
				"config_json": "config.json",
				"inference_config_json": "inference/config.json",
				"inference_model_py": "inference/model.py",
				"inference_kernel_py": "inference/kernel.py",
				"tokenizer_json": "tokenizer.json",
				"tokenizer_config_json": "tokenizer_config.json",
				"weight_index_json": "model.safetensors.index.json",
				"encoding_oracle": "encoding/tests/*",
				"oracle_prompts_json": "oracle/prompts.json",
				"upstream_commit_txt": "upstream_commit.txt",
			},
		},
		"compat": build_compat_mappings(),
		"mla": sem.get("mla", {}) if isinstance(sem, dict) else {},
		"topology": {
			"vocab_size": int(cfg["vocab_size"]),
			"hidden_size": int(cfg["hidden_size"]),
			"num_hidden_layers": n_layers,
			"num_attention_heads": int(cfg["num_attention_heads"]),
			"num_key_value_heads": int(cfg["num_key_value_heads"]),
			"head_dim": int(cfg["head_dim"]),
			"rope_head_dim": int(cfg["qk_rope_head_dim"]),
			"nope_head_dim": int(cfg["head_dim"]) - int(cfg["qk_rope_head_dim"]),
			"q_lora_rank": int(cfg["q_lora_rank"]),
			"o_groups": int(cfg["o_groups"]),
			"o_lora_rank": int(cfg["o_lora_rank"]),
			"sliding_window": int(cfg["sliding_window"]),
		},
		"yarn_rope": {
			"rope_theta": float(cfg.get("rope_theta", 10000)),
			"compress_rope_theta": float(cfg.get("compress_rope_theta", inf.get("compress_rope_theta", 0))),
			"original_seq_len": int(cfg.get("original_max_position_embeddings", inf.get("original_seq_len", 0))),
			"rope_factor": float(cfg.get("rope_scaling", {}).get("factor", inf.get("rope_factor", 0))),
			"beta_fast": int(cfg.get("rope_scaling", {}).get("beta_fast", inf.get("beta_fast", 0))),
			"beta_slow": int(cfg.get("rope_scaling", {}).get("beta_slow", inf.get("beta_slow", 0))),
			"per_layer_rule": {
				"if_compress_ratio_nonzero": {
					"rope_theta": "yarn_rope.compress_rope_theta",
					"original_seq_len": "yarn_rope.original_seq_len",
				},
				"if_compress_ratio_zero": {
					"rope_theta": "yarn_rope.rope_theta",
					"original_seq_len": 0,
				},
			},
		},
		"attention_schedule": {
			"compress_ratios": [int(r) for r in compress_ratios],
			"main_layer_types": layer_types,
			"type_counts": type_counts,
			"mtp_compress_ratios": [int(r) for r in mtp_ratios],
		},
		"cache": {
			"window_size": window_size,
			"kv_cache_size_formula": "window_size + (max_seq_len // compress_ratio if compress_ratio else 0)",
			"kv_cache_shape": "[max_batch_size, kv_cache_size, head_dim]",
			"update_semantics": sem.get("cache_update_semantics", {}) if isinstance(sem, dict) else {},
			"kv_cache_sizes_at_reference_defaults": {
				"max_seq_len": ref_max_seq_len,
				"max_batch_size": ref_max_batch_size,
				"kv_cache_size_by_compress_ratio": kv_cache_sizes_by_ratio,
				"kv_cache_size_by_layer": kv_cache_sizes_by_layer,
				"kv_cache_slots_total_main": kv_cache_slots_total,
				"kv_cache_slots_total_mtp": kv_cache_slots_mtp_total,
			},
			"topk_mask_value": -1,
			"sparse_attn_mask_rule": "idx == -1 => score=-inf, kv=0",
			"prefill": {
				"compressed_index_offset": "seqlen",
				"window_indices": "get_window_topk_idxs(window_size,...,start_pos=0)",
				"compress_indices": {"csa": "Indexer(...)", "hca": "get_compress_topk_idxs(...,offset=seqlen)"},
			},
			"decode": {
				"compressed_index_offset": "window_size",
				"window_indices": "get_window_topk_idxs(window_size,...,start_pos>0)",
				"compress_indices": {"csa": "Indexer(...,offset=window_size)", "hca": "get_compress_topk_idxs(...,offset=window_size)"},
			},
		},
			"moe": {
			"n_routed_experts": int(cfg["n_routed_experts"]),
			"n_shared_experts": int(cfg["n_shared_experts"]),
			"n_activated_experts": int(cfg["num_experts_per_tok"]),
			"moe_inter_dim": int(cfg["moe_intermediate_size"]),
			"scoring_func": str(cfg["scoring_func"]),
			"route_scale": float(cfg["routed_scaling_factor"]),
			"n_hash_layers": int(cfg["num_hash_layers"]),
			"hash_gate_tensor_key": "layers.{i}.ffn.gate.tid2eid",
			"score_gate_tensor_key": "layers.{i}.ffn.gate.bias",
			"semantics": moe_sem,
			"hash_routing": {
				"hash_layer_ids": list(range(int(cfg["num_hash_layers"]))),
				"tid2eid_dtype": "int32",
				"tid2eid_shape": [int(cfg["vocab_size"]), int(cfg["num_experts_per_tok"])],
				**moe_hash_sem,
			},
			},
				"mtp": {
					"n_mtp_layers": int(cfg["num_nextn_predict_layers"]),
					"compress_ratio_rule": "compress_ratios[n_layers+mtp_id] == 0",
					"namespace_prefix": "mtp.{j}.",
				},
				"runtime": {
					"reference_defaults": inf_model.get("reference_defaults", {}),
					"indexer": {
						"index_n_heads": int(inf["index_n_heads"]),
						"index_head_dim": int(inf["index_head_dim"]),
						"index_topk": int(inf["index_topk"]),
					},
					"hyper_connections": {
						"hc_mult": int(inf["hc_mult"]),
						"hc_sinkhorn_iters": int(inf["hc_sinkhorn_iters"]),
						"hc_eps": float(inf_model.get("inference_model_constants", {}).get("hc_eps", 1e-6)),
					},
				"swiglu_limit": float(inf["swiglu_limit"]) if "swiglu_limit" in inf else None,
				},
				"tokenizer": {
					"tokenizer_class": tok_cfg.get("tokenizer_class"),
					"model_max_length": int(tok_cfg.get("model_max_length")),
					"add_bos_token": bool(tok_cfg.get("add_bos_token")),
					"add_eos_token": bool(tok_cfg.get("add_eos_token")),
					"bos_token": tok_cfg.get("bos_token", {}).get("content"),
					"eos_token": tok_cfg.get("eos_token", {}).get("content"),
					"bos_token_id": int(cfg["bos_token_id"]),
					"eos_token_id": int(cfg["eos_token_id"]),
					"pad_token_is_eos": True,
					"encoding_oracle_dir": "encoding/tests",
					**tok_json_sum,
				},
			"quantization": {
				"config_quantization_config": cfg.get("quantization_config"),
				"inference_config": {
					"dtype": inf.get("dtype"),
					"scale_fmt": inf.get("scale_fmt"),
					"expert_dtype": inf.get("expert_dtype"),
				},
				"linear_tensor_contract": {
					"reference_source": "inference/model.py:Linear",
					"fp8": {
						"weight_dtype": "float8_e4m3fn",
						"weight_shape": "[out_features, in_features]",
						"scale_dtype": "float8_e8m0fnu",
						"scale_shape_formula": "[(out_features+block_size-1)//block_size, (in_features+block_size-1)//block_size]",
						"block_size": block_size,
					},
					"fp4": {
						"weight_dtype": "float4_e2m1fn_x2",
						"weight_storage_shape": "[out_features, in_features//2]",
						"weight_logical_shape": "[out_features, in_features]",
						"scale_dtype": "float8_e8m0fnu",
						"scale_shape_formula": "[out_features, in_features//fp4_block_size]",
						"fp4_block_size": fp4_block_size,
					},
				},
					**inf_model,
				},
				**enc,
				"tensor_keys": tensor_keys,
				"checkpoint_index": {
					"weight_map_num_tensors": int(len(weight_keys)),
					"weight_map_keys_sha256": weight_map_keys_sha256,
					"weight_map_unique_files": int(len(weight_map_file_counts)),
					"weight_map_file_counts": dict(weight_map_file_counts),
					"metadata": idx.get("metadata", {}),
				},
		}
	return contract


def main() -> int:
	ap = argparse.ArgumentParser(description="Build DeepSeek V4 Flash contract_summary.json from fixtures.")
	ap.add_argument("--out", type=Path, default=DEFAULT_OUT, help="Output JSON path.")
	ap.add_argument("--check", action="store_true", help="Exit non-zero if output differs from existing file.")
	args = ap.parse_args()

	contract = build_contract()
	out_path: Path = args.out

	if args.check and out_path.exists():
		prev = json.loads(out_path.read_text(encoding="utf-8"))
		if prev != contract:
			print(f"ERROR: {out_path} is stale; re-run without --check to regenerate")
			return 1
		print(f"OK: {out_path} up to date")
		return 0

	dump_json(out_path, contract)
	print(f"OK: wrote {out_path.relative_to(ROOT)}")
	return 0


if __name__ == "__main__":
	raise SystemExit(main())
