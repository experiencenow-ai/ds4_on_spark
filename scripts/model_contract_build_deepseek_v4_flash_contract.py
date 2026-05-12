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
MTP_SIDECAR_PROBE_PY = ROOT / "scripts" / "model_contract_probe_mtp_sidecar.py"
MTP_SIDECAR_REFERENCE_JSON = ROOT / "docs" / "mtp-sidecar-probe-antirez-c566ab6-payload64.json"

def repo_relpath(path: Path) -> str:
	try:
		return path.relative_to(ROOT).as_posix()
	except ValueError:
		return str(path)


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



def parse_ds4_mtp_sidecar_expected_tensor_names(probe_py: Path) -> Optional[list[str]]:
	if not probe_py.exists():
		return None
	text = probe_py.read_text(encoding="utf-8")
	try:
		mod = ast.parse(text, filename=str(probe_py))
	except SyntaxError:
		return None

	found: list[list[str]] = []
	for node in ast.walk(mod):
		if not isinstance(node, ast.Assign):
			continue
		if len(node.targets) != 1:
			continue
		t = node.targets[0]
		if not isinstance(t, ast.Name) or t.id != "expected_names":
			continue
		if not isinstance(node.value, ast.List):
			continue
		vals: list[str] = []
		ok = True
		for elt in node.value.elts:
			if isinstance(elt, ast.Constant) and isinstance(elt.value, str):
				vals.append(elt.value)
			else:
				ok = False
				break
		if ok and vals:
			found.append(vals)
	if not found:
		return None
	found.sort(key=len, reverse=True)
	return list(found[0])


def parse_ds4_mtp_sidecar_payload_samples_fingerprint(reference_json: Path) -> dict:
	reference_json_display = repo_relpath(reference_json)
	if not reference_json.exists():
		return {
			"reference_json": reference_json_display,
			"reference_sha256": None,
			"payload_sample_bytes": None,
			"payload_samples_count": None,
			"payload_samples_sha256": None,
		}

	try:
		doc = load_json(reference_json)
	except Exception:
		return {
			"reference_json": reference_json_display,
			"reference_sha256": sha256_file(reference_json),
			"payload_sample_bytes": None,
			"payload_samples_count": None,
			"payload_samples_sha256": None,
		}

	sample_bytes = doc.get("payload_sample_bytes", None) if isinstance(doc, dict) else None
	samples = doc.get("payload_samples", None) if isinstance(doc, dict) else None

	lines: list[str] = []
	if isinstance(samples, dict):
		for name in sorted(samples.keys()):
			s = samples.get(name, None)
			if not isinstance(name, str) or not isinstance(s, dict):
				continue
			n = s.get("n", None)
			fnv = s.get("fnv1a64", None)
			off = s.get("offset", None)
			if not isinstance(n, int) or not isinstance(fnv, str) or not isinstance(off, int):
				continue
			lines.append(f"{name}\t{int(n)}\t{fnv}\t{int(off)}")

	out_sha = sha256_lines(lines) if lines else None
	return {
		"reference_json": reference_json_display,
		"reference_sha256": sha256_file(reference_json),
		"payload_sample_bytes": int(sample_bytes) if isinstance(sample_bytes, int) else None,
		"payload_samples_count": int(len(lines)) if lines else None,
		"payload_samples_sha256": out_sha,
	}


def build_ds4_mtp_sidecar_contract() -> dict:
	expected = parse_ds4_mtp_sidecar_expected_tensor_names(MTP_SIDECAR_PROBE_PY)
	expected_sha = sha256_lines(expected) if isinstance(expected, list) else None
	return {
		"reference_source": "scripts/model_contract_probe_mtp_sidecar.py (DS4-tuned sidecar tensor table)",
		"general_architecture": "deepseek4_mtp_support",
		"expected_tensor_names": expected,
		"expected_tensor_names_sha256": expected_sha,
		"expected_tensor_count": int(len(expected)) if isinstance(expected, list) else None,
		"reference_payload_samples": parse_ds4_mtp_sidecar_payload_samples_fingerprint(MTP_SIDECAR_REFERENCE_JSON),
	}

def build_weight_key_prefix_fingerprints(weight_keys: list[str]) -> dict:
	prefix_to_keys: dict[str, list[str]] = {}
	for k in weight_keys:
		prefix = k.split(".", 1)[0]
		prefix_to_keys.setdefault(prefix, []).append(k)

	out: dict[str, dict] = {}
	for prefix in sorted(prefix_to_keys.keys()):
		keys = sorted(prefix_to_keys[prefix])
		out[prefix] = {
			"count": int(len(keys)),
			"keys_sha256": sha256_lines(keys),
		}
	return out

def build_oracle_contract() -> dict:
	prompts_default_topk = None
	prompts_path = FIX / "oracle" / "prompts.json"
	try:
		prompts = load_json(prompts_path)
		default_topk = prompts.get("default_topk")
		if isinstance(default_topk, int):
			prompts_default_topk = int(default_topk)
	except Exception:
		prompts_default_topk = None
	return {
		"encoding_oracle": {
			"required": True,
			"fixtures_glob": "encoding/tests/*",
			"verifier": "scripts/model_contract_verify_deepseek_v4_flash.py",
			"note": "Tokenizer/chat rendering must match upstream encoding vectors before any logit comparison is meaningful.",
		},
		"logits_oracle": {
			"required": True,
			"weights_required": True,
			"prompts_fixture": "oracle/prompts.json",
			"generator": "scripts/model_contract_generate_deepseek_v4_flash_oracle.py",
			"output_fixture": "oracle/logits_oracle.json",
			"acceptance": {
				"requires_prefill_and_decode": True,
				"topk_k": prompts_default_topk,
				"topk_ids_exact": True,
				"logits_tolerance_note": "Tolerance depends on quantization/kernels; see docs/model-contract.md.",
			},
			"note": "Do not commit oracle outputs until reviewed; the default automation refuses to download weights.",
		},
		"mtp": {
			"required": True,
			"weights_required": True,
			"generator_hint": "scripts/model_contract_generate_deepseek_v4_flash_oracle.py --include-mtp",
			"acceptance": {
				"requires_mtp_trace": True,
				"topk_k": prompts_default_topk,
				"topk_ids_exact": True,
				"logits_tolerance_note": "MTP is a separate execution path; validate draft logits against the upstream oracle before trusting speculative decoding.",
			},
		},
	}

def build_tensor_shapes(cfg: dict, inf: dict, inf_model: dict) -> dict:
	dim = int(cfg["hidden_size"])
	vocab_size = int(cfg["vocab_size"])
	n_heads = int(cfg["num_attention_heads"])
	head_dim = int(cfg["head_dim"])
	q_lora_rank = int(cfg["q_lora_rank"])
	o_groups = int(cfg["o_groups"])
	o_lora_rank = int(cfg["o_lora_rank"])
	rope_head_dim = int(cfg["qk_rope_head_dim"])
	nope_head_dim = head_dim - rope_head_dim
	n_routed_experts = int(cfg["n_routed_experts"])
	n_activated_experts = int(cfg["num_experts_per_tok"])
	moe_inter_dim = int(cfg["moe_intermediate_size"])
	hc_mult = int(inf["hc_mult"])
	hc_dim = hc_mult * dim
	mix_hc = (2 + hc_mult) * hc_mult
	index_n_heads = int(inf["index_n_heads"])
	index_head_dim = int(inf["index_head_dim"])

	inf_consts = inf_model.get("inference_model_constants", {}) if isinstance(inf_model, dict) else {}
	block_size = inf_consts.get("block_size", None) if isinstance(inf_consts, dict) else None
	fp4_block_size = inf_consts.get("fp4_block_size", None) if isinstance(inf_consts, dict) else None
	if not isinstance(block_size, int):
		block_size = None
	if not isinstance(fp4_block_size, int):
		fp4_block_size = None

	def fp8_scale_shape(out_features: int, in_features: int) -> list[int]:
		assert block_size is not None
		return [
			(int(out_features) + int(block_size) - 1) // int(block_size),
			(int(in_features) + int(block_size) - 1) // int(block_size),
		]

	def fp4_scale_shape(out_features: int, in_features: int) -> list[int]:
		assert fp4_block_size is not None
		return [int(out_features), int(in_features) // int(fp4_block_size)]

	return {
		"reference_source": "fixtures/model_contract/deepseek_v4_flash/inference/model.py (logical/unsharded shapes)",
		"top_level": {
			"embed.weight": [vocab_size, dim],
			"norm.weight": [dim],
			"head.weight": [vocab_size, dim],
			"hc_head_fn": [hc_mult, hc_dim],
			"hc_head_base": [hc_mult],
			"hc_head_scale": [1],
		},
		"per_layer": {
			"attn": {
				"attn_sink": [n_heads],
				"wq_a.weight": [q_lora_rank, dim],
				"wq_a.scale": fp8_scale_shape(q_lora_rank, dim) if block_size is not None else None,
				"q_norm.weight": [q_lora_rank],
				"wq_b.weight": [n_heads * head_dim, q_lora_rank],
				"wq_b.scale": fp8_scale_shape(n_heads * head_dim, q_lora_rank) if block_size is not None else None,
				"wkv.weight": [head_dim, dim],
				"wkv.scale": fp8_scale_shape(head_dim, dim) if block_size is not None else None,
				"kv_norm.weight": [head_dim],
				"wo_a.weight": [o_groups * o_lora_rank, (n_heads * head_dim) // o_groups],
				"wo_a.scale": fp8_scale_shape(o_groups * o_lora_rank, (n_heads * head_dim) // o_groups) if block_size is not None else None,
				"wo_b.weight": [dim, o_groups * o_lora_rank],
				"wo_b.scale": fp8_scale_shape(dim, o_groups * o_lora_rank) if block_size is not None else None,
				"attn_norm.weight": [dim],
			},
			"compressor": {
				"note": "Compressor tensors exist only when compress_ratio != 0. For CSA (ratio==4), overlap=true and coff=2; otherwise coff=1.",
				"ape.shape_formula": "[compress_ratio, (1+overlap)*head_dim]",
				"wkv.weight.shape_formula": "[(1+overlap)*head_dim, hidden_size]",
				"wgate.weight.shape_formula": "[(1+overlap)*head_dim, hidden_size]",
				"norm.weight": [head_dim],
				"overlap_rule": "overlap = (compress_ratio == 4)",
			},
			"indexer": {
				"note": "Indexer tensors exist only for CSA layers (compress_ratio==4).",
				"wq_b.weight": [index_n_heads * index_head_dim, q_lora_rank],
				"wq_b.scale": fp8_scale_shape(index_n_heads * index_head_dim, q_lora_rank) if block_size is not None else None,
				"weights_proj.weight": [index_n_heads, dim],
				"compressor": {
					"ape.shape_formula": "[compress_ratio, (1+overlap)*index_head_dim]",
					"wkv.weight.shape_formula": "[(1+overlap)*index_head_dim, hidden_size]",
					"wgate.weight.shape_formula": "[(1+overlap)*index_head_dim, hidden_size]",
					"norm.weight": [index_head_dim],
				},
			},
			"moe": {
				"gate.weight": [n_routed_experts, dim],
				"gate.tid2eid": [vocab_size, n_activated_experts],
				"gate.bias": [n_routed_experts],
				"experts.{eid}.w1.weight": [moe_inter_dim, dim],
				"experts.{eid}.w1.scale": fp4_scale_shape(moe_inter_dim, dim) if fp4_block_size is not None else None,
				"experts.{eid}.w2.weight": [dim, moe_inter_dim],
				"experts.{eid}.w2.scale": fp4_scale_shape(dim, moe_inter_dim) if fp4_block_size is not None else None,
				"experts.{eid}.w3.weight": [moe_inter_dim, dim],
				"experts.{eid}.w3.scale": fp4_scale_shape(moe_inter_dim, dim) if fp4_block_size is not None else None,
				"shared_experts.w1.weight": [moe_inter_dim, dim],
				"shared_experts.w1.scale": fp4_scale_shape(moe_inter_dim, dim) if fp4_block_size is not None else None,
				"shared_experts.w2.weight": [dim, moe_inter_dim],
				"shared_experts.w2.scale": fp4_scale_shape(dim, moe_inter_dim) if fp4_block_size is not None else None,
				"shared_experts.w3.weight": [moe_inter_dim, dim],
				"shared_experts.w3.scale": fp4_scale_shape(moe_inter_dim, dim) if fp4_block_size is not None else None,
			},
			"hyper_connections": {
				"hc_mult": hc_mult,
				"hc_dim": hc_dim,
				"mix_hc": mix_hc,
				"hc_attn_fn": [mix_hc, hc_dim],
				"hc_attn_base": [mix_hc],
				"hc_attn_scale": [3],
				"hc_ffn_fn": [mix_hc, hc_dim],
				"hc_ffn_base": [mix_hc],
				"hc_ffn_scale": [3],
			},
		},
		"mtp_per_layer": {
			"note": "MTP blocks are implemented as MTPBlock(Block) in inference/model.py; the block-level tensor shapes under mtp.{j}.attn.* / mtp.{j}.ffn.* match the trunk per-layer shapes under layers.{i}.attn.* / layers.{i}.ffn.*.",
			"per_layer": {
				"attn": {
					"attn_sink": [n_heads],
					"wq_a.weight": [q_lora_rank, dim],
					"wq_a.scale": fp8_scale_shape(q_lora_rank, dim) if block_size is not None else None,
					"q_norm.weight": [q_lora_rank],
					"wq_b.weight": [n_heads * head_dim, q_lora_rank],
					"wq_b.scale": fp8_scale_shape(n_heads * head_dim, q_lora_rank) if block_size is not None else None,
					"wkv.weight": [head_dim, dim],
					"wkv.scale": fp8_scale_shape(head_dim, dim) if block_size is not None else None,
					"kv_norm.weight": [head_dim],
					"wo_a.weight": [o_groups * o_lora_rank, (n_heads * head_dim) // o_groups],
					"wo_a.scale": fp8_scale_shape(o_groups * o_lora_rank, (n_heads * head_dim) // o_groups) if block_size is not None else None,
					"wo_b.weight": [dim, o_groups * o_lora_rank],
					"wo_b.scale": fp8_scale_shape(dim, o_groups * o_lora_rank) if block_size is not None else None,
					"attn_norm.weight": [dim],
				},
				"compressor": {
					"note": "MTP compress_ratios are required to be 0 (sliding-only), so compressor/indexer tensors should be absent under mtp.{j}.attn.*.",
				},
				"moe": {
					"gate.weight": [n_routed_experts, dim],
					"gate.tid2eid": [vocab_size, n_activated_experts],
					"gate.bias": [n_routed_experts],
					"experts.{eid}.w1.weight": [moe_inter_dim, dim],
					"experts.{eid}.w1.scale": fp4_scale_shape(moe_inter_dim, dim) if fp4_block_size is not None else None,
					"experts.{eid}.w2.weight": [dim, moe_inter_dim],
					"experts.{eid}.w2.scale": fp4_scale_shape(dim, moe_inter_dim) if fp4_block_size is not None else None,
					"experts.{eid}.w3.weight": [moe_inter_dim, dim],
					"experts.{eid}.w3.scale": fp4_scale_shape(moe_inter_dim, dim) if fp4_block_size is not None else None,
					"shared_experts.w1.weight": [moe_inter_dim, dim],
					"shared_experts.w1.scale": fp4_scale_shape(moe_inter_dim, dim) if fp4_block_size is not None else None,
					"shared_experts.w2.weight": [dim, moe_inter_dim],
					"shared_experts.w2.scale": fp4_scale_shape(dim, moe_inter_dim) if fp4_block_size is not None else None,
					"shared_experts.w3.weight": [moe_inter_dim, dim],
					"shared_experts.w3.scale": fp4_scale_shape(moe_inter_dim, dim) if fp4_block_size is not None else None,
				},
				"hyper_connections": {
					"hc_mult": hc_mult,
					"hc_dim": hc_dim,
					"mix_hc": mix_hc,
					"hc_attn_fn": [mix_hc, hc_dim],
					"hc_attn_base": [mix_hc],
					"hc_attn_scale": [3],
					"hc_ffn_fn": [mix_hc, hc_dim],
					"hc_ffn_base": [mix_hc],
					"hc_ffn_scale": [3],
				},
			},
		},
		"mla": {
			"rope_head_dim": rope_head_dim,
			"nope_head_dim": nope_head_dim,
			"rope_slice_rule": "RoPE applies to trailing rope_head_dim dims via x[..., -rope_head_dim:]",
		},
		"mtp": {
			"e_proj.weight": [dim, dim],
			"e_proj.scale": fp8_scale_shape(dim, dim) if block_size is not None else None,
			"h_proj.weight": [dim, dim],
			"h_proj.scale": fp8_scale_shape(dim, dim) if block_size is not None else None,
			"enorm.weight": [dim],
			"hnorm.weight": [dim],
			"norm.weight": [dim],
			"hc_head_fn": [hc_mult, hc_dim],
			"hc_head_base": [hc_mult],
			"hc_head_scale": [1],
		},
	}

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
	added_tokens_count_ge_base_vocab: Optional[int] = None
	added_special_tokens_count_ge_base_vocab: Optional[int] = None
	added_id_min_ge_base_vocab: Optional[int] = None
	added_id_max_ge_base_vocab: Optional[int] = None
	if isinstance(added_tokens, list):
		added_tokens_count = int(len(added_tokens))
		added_special_tokens_count = int(sum(1 for t in added_tokens if isinstance(t, dict) and t.get("special") is True))
		ids: list[int] = [int(t["id"]) for t in added_tokens if isinstance(t, dict) and isinstance(t.get("id"), int)]
		if ids:
			added_id_min = int(min(ids))
			added_id_max = int(max(ids))
		if isinstance(base_vocab_size, int):
			ids_ge_base = [i for i in ids if i >= base_vocab_size]
			added_tokens_count_ge_base_vocab = int(len(ids_ge_base))
			added_special_tokens_count_ge_base_vocab = int(sum(1 for t in added_tokens if isinstance(t, dict) and isinstance(t.get("id"), int) and int(t.get("id")) >= base_vocab_size and t.get("special") is True))
			if ids_ge_base:
				added_id_min_ge_base_vocab = int(min(ids_ge_base))
				added_id_max_ge_base_vocab = int(max(ids_ge_base))

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
			"added_tokens_count_ge_base_vocab": added_tokens_count_ge_base_vocab,
			"added_special_tokens_count_ge_base_vocab": added_special_tokens_count_ge_base_vocab,
			"added_token_id_min_ge_base_vocab": added_id_min_ge_base_vocab,
			"added_token_id_max_ge_base_vocab": added_id_max_ge_base_vocab,
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

def transformers_layer_type_from_ratio(ratio: int) -> str:
	# Official Transformers deepseek_v4 naming for `config.layer_types[i]`.
	if ratio == 0:
		return "sliding_attention"
	if ratio == 4:
		return "compressed_sparse_attention"
	return "heavily_compressed_attention"

def find_first_line_containing(text: str, needle: str) -> Optional[str]:
	for raw in text.splitlines():
		if needle in raw:
			return raw.strip()
	return None

def extract_function_source_lines(text: str, func_name: str) -> Optional[list[str]]:
	try:
		mod = ast.parse(text)
	except Exception:
		return None
	lines = text.splitlines()
	for node in mod.body:
		if not isinstance(node, ast.FunctionDef):
			continue
		if node.name != func_name:
			continue
		start = node.lineno
		if node.decorator_list:
			start = min((getattr(d, "lineno", start) for d in node.decorator_list))
		end = getattr(node, "end_lineno", None)
		if not isinstance(start, int) or not isinstance(end, int) or start <= 0 or end <= 0:
			return None
		if end < start or end > len(lines):
			return None
		out = [ln.rstrip() for ln in lines[start - 1 : end]]
		while out and out[-1] == "":
			out.pop()
		return out
	return None

def extract_class_method_source_lines(text: str, class_name: str, method_name: str) -> Optional[list[str]]:
	try:
		mod = ast.parse(text)
	except Exception:
		return None
	lines = text.splitlines()
	for node in mod.body:
		if not isinstance(node, ast.ClassDef):
			continue
		if node.name != class_name:
			continue
		for sub in node.body:
			if not isinstance(sub, ast.FunctionDef):
				continue
			if sub.name != method_name:
				continue
			start = sub.lineno
			if sub.decorator_list:
				start = min((getattr(d, "lineno", start) for d in sub.decorator_list))
			end = getattr(sub, "end_lineno", None)
			if not isinstance(start, int) or not isinstance(end, int) or start <= 0 or end <= 0:
				return None
			if end < start or end > len(lines):
				return None
			out = [ln.rstrip() for ln in lines[start - 1 : end]]
			while out and out[-1] == "":
				out.pop()
			return out
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
	kv_prefill_write_le_win = find_first_line_containing(text, "self.kv_cache[:bsz, :seqlen] = kv")
	kv_prefill_write_gt_win = find_first_line_containing(text, "self.kv_cache[:bsz, cutoff: win], self.kv_cache[:bsz, :cutoff] = kv[:, -win:].split([win - cutoff, cutoff], dim=1)")
	kv_compressed_segment_view = find_first_line_containing(text, "self.compressor.kv_cache = self.kv_cache[:, win:]")
	topk_offset_expr = find_first_line_containing(text, "offset = kv.size(1) if start_pos == 0 else win")
	compress_prefill_gate = find_first_line_containing(text, "should_compress = seqlen >= ratio")
	compress_decode_gate = find_first_line_containing(text, "should_compress = (start_pos + 1) % self.compress_ratio == 0")
	compress_prefill_write = find_first_line_containing(text, "self.kv_cache[:bsz, :seqlen // ratio] = kv")
	compress_decode_write = find_first_line_containing(text, "self.kv_cache[:bsz, start_pos // ratio] = kv.squeeze(1)")
	compress_freqs_prefill = find_first_line_containing(text, "freqs_cis = self.freqs_cis[:cutoff:ratio]")
	compress_freqs_decode = find_first_line_containing(text, "freqs_cis = self.freqs_cis[start_pos + 1 - self.compress_ratio].unsqueeze(0)")

	precompute_freqs_lines = extract_function_source_lines(text, "precompute_freqs_cis")
	apply_rotary_lines = extract_function_source_lines(text, "apply_rotary_emb")

	win_topk_lines = extract_function_source_lines(text, "get_window_topk_idxs")
	compress_topk_lines = extract_function_source_lines(text, "get_compress_topk_idxs")

	compressor_forward_lines = extract_class_method_source_lines(text, "Compressor", "forward")
	indexer_forward_lines = extract_class_method_source_lines(text, "Indexer", "forward")
	attention_forward_lines = extract_class_method_source_lines(text, "Attention", "forward")

	return {
		"mla": {
			"rope_slice_rule": "RoPE applies to trailing rope_head_dim dims via x[..., -rope_head_dim:]",
			"q_extra_rms_norm_present": q_extra_norm is not None,
			"q_extra_rms_norm_expr": q_extra_norm,
			"output_derotate_present": o_derotate is not None,
			"output_derotate_expr": o_derotate,
			"q_rope_apply_expr": rope_q,
			"kv_rope_apply_expr": rope_kv,
			"source_helpers": {
				"reference_source": "fixtures/model_contract/deepseek_v4_flash/inference/model.py (precompute_freqs_cis, apply_rotary_emb)",
				"precompute_freqs_cis": {
					"source_lines": precompute_freqs_lines,
					"source_lines_sha256": sha256_lines(precompute_freqs_lines) if isinstance(precompute_freqs_lines, list) else None,
				},
				"apply_rotary_emb": {
					"source_lines": apply_rotary_lines,
					"source_lines_sha256": sha256_lines(apply_rotary_lines) if isinstance(apply_rotary_lines, list) else None,
				},
			},
		},
		"cache_update_semantics": {
			"decode_sliding_ring_update_expr": kv_decode_ring,
			"decode_compressed_update_expr": kv_decode_compress,
			"prefill_sliding_wrap_expr": kv_prefill_wrap,
			"prefill_sliding_write_seqlen_le_win_expr": kv_prefill_write_le_win,
			"prefill_sliding_write_seqlen_gt_win_expr": kv_prefill_write_gt_win,
			"compressed_segment_view_expr": kv_compressed_segment_view,
			"topk_offset_expr": topk_offset_expr,
			"compressor_prefill_should_compress_expr": compress_prefill_gate,
			"compressor_decode_should_compress_expr": compress_decode_gate,
			"compressor_prefill_write_expr": compress_prefill_write,
			"compressor_decode_write_expr": compress_decode_write,
			"compressor_freqs_cis_prefill_expr": compress_freqs_prefill,
			"compressor_freqs_cis_decode_expr": compress_freqs_decode,
		},
		"cache_topk_index_helpers": {
			"reference_source": "fixtures/model_contract/deepseek_v4_flash/inference/model.py (get_window_topk_idxs, get_compress_topk_idxs)",
			"sentinel_index": -1,
			"get_window_topk_idxs": {
				"source_lines": win_topk_lines,
				"source_lines_sha256": sha256_lines(win_topk_lines) if isinstance(win_topk_lines, list) else None,
			},
			"get_compress_topk_idxs": {
				"source_lines": compress_topk_lines,
				"source_lines_sha256": sha256_lines(compress_topk_lines) if isinstance(compress_topk_lines, list) else None,
			},
		},
		"cache_source_helpers": {
			"reference_source": "fixtures/model_contract/deepseek_v4_flash/inference/model.py (Compressor.forward, Indexer.forward, Attention.forward)",
			"compressor_forward": {
				"source_lines": compressor_forward_lines,
				"source_lines_sha256": sha256_lines(compressor_forward_lines) if isinstance(compressor_forward_lines, list) else None,
			},
			"indexer_forward": {
				"source_lines": indexer_forward_lines,
				"source_lines_sha256": sha256_lines(indexer_forward_lines) if isinstance(indexer_forward_lines, list) else None,
			},
			"attention_forward": {
				"source_lines": attention_forward_lines,
				"source_lines_sha256": sha256_lines(attention_forward_lines) if isinstance(attention_forward_lines, list) else None,
			},
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
	swiglu_gate = find_first_line_containing(text, "if self.swiglu_limit > 0:")
	swiglu_up_clamp = find_first_line_containing(text, "up = torch.clamp(up, min=-self.swiglu_limit, max=self.swiglu_limit)")
	swiglu_gate_clamp = find_first_line_containing(text, "gate = torch.clamp(gate, max=self.swiglu_limit)")

	gate_forward_lines = extract_class_method_source_lines(text, "Gate", "forward")
	moe_forward_lines = extract_class_method_source_lines(text, "MoE", "forward")

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
		"swiglu_clamp_enabled_expr": swiglu_gate,
		"swiglu_clamp_up_expr": swiglu_up_clamp,
		"swiglu_clamp_gate_expr": swiglu_gate_clamp,
		"source_helpers": {
			"reference_source": "fixtures/model_contract/deepseek_v4_flash/inference/model.py (Gate.forward, MoE.forward)",
			"gate_forward": {
				"source_lines": gate_forward_lines,
				"source_lines_sha256": sha256_lines(gate_forward_lines) if isinstance(gate_forward_lines, list) else None,
			},
			"moe_forward": {
				"source_lines": moe_forward_lines,
				"source_lines_sha256": sha256_lines(moe_forward_lines) if isinstance(moe_forward_lines, list) else None,
			},
		},
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

def parse_inference_mtp_semantics(model_py: Path) -> dict:
	text = model_py.read_text(encoding="utf-8")
	input_shape_comment = find_first_line_containing(text, "# x: [b,s,hc,d]")
	embed_head_assert = find_first_line_containing(text, "assert self.embed is not None and self.head is not None")
	embed = find_first_line_containing(text, "e = self.embed(input_ids)")
	enorm = find_first_line_containing(text, "e = self.enorm(e)")
	hnorm = find_first_line_containing(text, "x = self.hnorm(x)")
	combine = find_first_line_containing(text, "x = self.e_proj(e).unsqueeze(2) + self.h_proj(x)")
	super_forward = find_first_line_containing(text, "x = super().forward(x, start_pos, input_ids)")
	head = find_first_line_containing(text, "logits = self.head(x, self.hc_head_fn, self.hc_head_scale, self.hc_head_base, self.norm)")
	mtp_forward_lines = extract_class_method_source_lines(text, "MTPBlock", "forward")

	return {
		"input_shape_comment": input_shape_comment,
		"assert_embed_head_expr": embed_head_assert,
		"embed_expr": embed,
		"enorm_expr": enorm,
		"hnorm_expr": hnorm,
		"combine_e_and_h_expr": combine,
		"super_forward_expr": super_forward,
		"head_logits_expr": head,
		"source_helpers": {
			"reference_source": "fixtures/model_contract/deepseek_v4_flash/inference/model.py (MTPBlock.forward)",
			"mtp_block_forward": {
				"source_lines": mtp_forward_lines,
				"source_lines_sha256": sha256_lines(mtp_forward_lines) if isinstance(mtp_forward_lines, list) else None,
			},
		},
	}

def kv_cache_size(window_size: int, max_seq_len: int, compress_ratio: int) -> int:
	if compress_ratio == 0:
		return int(window_size)
	return int(window_size + (int(max_seq_len) // int(compress_ratio)))


def parse_inference_quant_constants(model_py: Path) -> dict:
	text = model_py.read_text(encoding="utf-8")

	def parse_modelargs_defaults() -> dict:
		in_model_args = False
		out: dict[str, object] = {
			"max_batch_size": None,
			"max_seq_len": None,
			"dtype": None,
			"scale_fmt": None,
			"scale_dtype": None,
			"expert_dtype": None,
		}
		for raw in text.splitlines():
			line = raw.strip()
			if line.startswith("class ModelArgs"):
				in_model_args = True
				continue
			if in_model_args and line.startswith("class ") and not line.startswith("class ModelArgs"):
				break
			if not in_model_args:
				continue
			if not line.startswith(tuple(f + ":" for f in out.keys())):
				continue
			if " = " not in line:
				continue
			field = line.split(":", 1)[0].strip()
			rhs = line.split("=", 1)[1].strip()

			if rhs == "None":
				out[field] = None
				continue
			if len(rhs) >= 2 and rhs[0] in ("'", '"') and rhs[-1] == rhs[0]:
				out[field] = rhs[1:-1]
				continue
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
	modelargs_defaults = parse_modelargs_defaults()
	defaults = {
		"max_batch_size": modelargs_defaults.get("max_batch_size"),
		"max_seq_len": modelargs_defaults.get("max_seq_len"),
	}
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
		"modelargs_defaults": modelargs_defaults,
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
	mtp_layer_ids = find_mtp_layer_ids(weight_keys)
	expected_expert_key_count_per_layer = int(n_routed_experts) * 6
	expert_tensor_key_templates = [
		"ffn.experts.{eid}.w1.weight",
		"ffn.experts.{eid}.w1.scale",
		"ffn.experts.{eid}.w2.weight",
		"ffn.experts.{eid}.w2.scale",
		"ffn.experts.{eid}.w3.weight",
		"ffn.experts.{eid}.w3.scale",
	]

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

	required_top_level = [
		"embed.weight",
		"norm.weight",
		"head.weight",
		"hc_head_fn",
		"hc_head_base",
		"hc_head_scale",
	]

	required_layer_suffixes = [
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
	]

	required_layer_suffixes_compress_ratio_nonzero = [
		"attn.compressor.ape",
		"attn.compressor.norm.weight",
		"attn.compressor.wgate.weight",
		"attn.compressor.wkv.weight",
	]

	required_layer_suffixes_compress_ratio_4 = [
		"attn.indexer.wq_b.weight",
		"attn.indexer.wq_b.scale",
		"attn.indexer.weights_proj.weight",
		"attn.indexer.compressor.ape",
		"attn.indexer.compressor.norm.weight",
		"attn.indexer.compressor.wgate.weight",
		"attn.indexer.compressor.wkv.weight",
	]

	required_mtp_additional_suffixes = [
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
	]

	mtp_score_gate_tensor_key_suffix = "ffn.gate.bias"
	hash_gate_tensor_key_suffix = "ffn.gate.tid2eid"
	score_gate_tensor_key_suffix = "ffn.gate.bias"
	mtp_required_nonexpert_suffixes = list(required_layer_suffixes) + list(required_mtp_additional_suffixes) + [
		mtp_score_gate_tensor_key_suffix
	]

	mtp_expected_tensor_key_count_per_layer = (
		expected_expert_key_count_per_layer + len(required_layer_suffixes) + len(required_mtp_additional_suffixes) + 1
	)
	mtp_key_count_by_layer_id: dict[str, int] = {}
	mtp_expected_key_count_by_layer_id_ok: dict[str, bool] = {}
	for mtp_id in mtp_layer_ids:
		prefix = f"mtp.{mtp_id}."
		c = sum(1 for k in weight_keys if k.startswith(prefix))
		mtp_key_count_by_layer_id[str(mtp_id)] = int(c)
		mtp_expected_key_count_by_layer_id_ok[str(mtp_id)] = (int(c) == int(mtp_expected_tensor_key_count_per_layer))

	mtp_forbidden_key_suffixes = [
		"attn.compressor.",
		"attn.indexer.",
		"ffn.gate.tid2eid",
		"embed.weight",
		"head.weight",
	]

	return {
		"tensor_key_count": len(weight_keys),
		"namespaces": sorted(top.keys()),
		"top_level_prefix_counts": dict(top),
		"expert_tensor_key_templates": expert_tensor_key_templates,
		"mtp0": {
			"present": mtp0_key_count > 0,
			"tensor_key_count": mtp0_key_count,
		},
		"mtp_shared_embed_head_rule": "MTP blocks share top-level embed/head; mtp.{j}.embed.* and mtp.{j}.head.* are absent in official checkpoints",
		"mtp_embed_present": mtp_embed_present,
		"mtp_head_present": mtp_head_present,
		"mtp_layer_ids": mtp_layer_ids,
		"layer_gate": {
			"tid2eid_layer_ids": layer_ids_matching("ffn.gate.tid2eid"),
			"gate_bias_layer_ids": layer_ids_matching("ffn.gate.bias"),
		},
		"expected_expert_key_count_per_layer": expected_expert_key_count_per_layer,
		"required_top_level": required_top_level,
		"required_layer_suffixes": required_layer_suffixes,
		"required_layer_suffixes_compress_ratio_nonzero": required_layer_suffixes_compress_ratio_nonzero,
		"required_layer_suffixes_compress_ratio_4": required_layer_suffixes_compress_ratio_4,
		"required_mtp_additional_suffixes": required_mtp_additional_suffixes,
		"mtp_required_nonexpert_suffixes": mtp_required_nonexpert_suffixes,
		"mtp_score_gate_tensor_key_suffix": mtp_score_gate_tensor_key_suffix,
		"hash_gate_tensor_key_suffix": hash_gate_tensor_key_suffix,
		"score_gate_tensor_key_suffix": score_gate_tensor_key_suffix,
		"mtp_expected_tensor_key_count_per_layer": int(mtp_expected_tensor_key_count_per_layer),
		"mtp_expected_tensor_key_count_breakdown": {
			"experts": int(expected_expert_key_count_per_layer),
			"required_layer_suffixes": int(len(required_layer_suffixes)),
			"required_mtp_additional_suffixes": int(len(required_mtp_additional_suffixes)),
			"score_gate_bias": 1,
		},
		"mtp_tensor_key_count_by_layer_id": mtp_key_count_by_layer_id,
		"mtp_expected_tensor_key_count_by_layer_id_ok": mtp_expected_key_count_by_layer_id_ok,
		"mtp_forbidden_key_suffixes": mtp_forbidden_key_suffixes,
		"weight_index_source": "model.safetensors.index.json:weight_map",
	}


def augment_tensor_key_summary_with_trunk_layer_expectations(
	tensor_keys: dict[str, Any],
	weight_keys: list[str],
	compress_ratios_main: list[int],
	n_hash_layers: int,
) -> None:
	required_layer_suffixes = tensor_keys.get("required_layer_suffixes", None)
	required_nonzero = tensor_keys.get("required_layer_suffixes_compress_ratio_nonzero", None)
	required_ratio4 = tensor_keys.get("required_layer_suffixes_compress_ratio_4", None)
	expected_expert = tensor_keys.get("expected_expert_key_count_per_layer", None)
	hash_gate_suffix = tensor_keys.get("hash_gate_tensor_key_suffix", "ffn.gate.tid2eid")
	score_gate_suffix = tensor_keys.get("score_gate_tensor_key_suffix", "ffn.gate.bias")

	if not isinstance(required_layer_suffixes, list):
		return
	if not isinstance(required_nonzero, list) or not isinstance(required_ratio4, list):
		return
	if not isinstance(expected_expert, int) or expected_expert <= 0:
		return

	n_layers = len(compress_ratios_main)
	required_by_layer_id: dict[str, list[str]] = {}
	expected_count_by_layer_id: dict[str, int] = {}
	for i in range(n_layers):
		try:
			ratio_i = int(compress_ratios_main[i])
		except Exception:
			ratio_i = 0
		req = list(required_layer_suffixes)
		if ratio_i != 0:
			req += list(required_nonzero)
		if ratio_i == 4:
			req += list(required_ratio4)
		req.append(str(hash_gate_suffix if i < int(n_hash_layers) else score_gate_suffix))
		required_by_layer_id[str(i)] = req
		expected_count_by_layer_id[str(i)] = int(expected_expert + len(req))

	actual_counts = [0 for _ in range(n_layers)]
	for k in weight_keys:
		if not k.startswith("layers."):
			continue
		parts = k.split(".", 2)
		if len(parts) < 3:
			continue
		try:
			i = int(parts[1])
		except Exception:
			continue
		if 0 <= i < n_layers:
			actual_counts[i] += 1

	actual_by_layer_id: dict[str, int] = {str(i): int(actual_counts[i]) for i in range(n_layers)}
	ok_by_layer_id: dict[str, bool] = {}
	for i in range(n_layers):
		key = str(i)
		ok_by_layer_id[key] = (int(actual_counts[i]) == int(expected_count_by_layer_id[key]))

	tensor_keys["layer_required_nonexpert_suffixes_by_layer_id"] = required_by_layer_id
	tensor_keys["layer_expected_tensor_key_count_by_layer_id"] = expected_count_by_layer_id
	tensor_keys["layer_tensor_key_count_by_layer_id"] = actual_by_layer_id
	tensor_keys["layer_expected_tensor_key_count_by_layer_id_ok"] = ok_by_layer_id

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
		{
			"concept": "layer_types",
			"transformers_key": "layer_types",
			"inference_key": None,
			"canonical_path": "attention_schedule.transformers_main_layer_types",
			"note": "Transformers DeepseekV4Config.layer_types is a per-trunk-layer attention schedule (length num_hidden_layers). DS4 also records the MTP schedule separately under attention_schedule.transformers_mtp_layer_types.",
		},
		{
			"concept": "compress_rates",
			"transformers_key": "compress_rates",
			"inference_key": None,
			"canonical_path": "attention_schedule.transformers_compress_rates",
			"note": "Transformers exposes per-layer-type compression rates as compress_rates; DS4 derives them from the pinned compress_ratios contract (CSA->4, HCA->128, sliding->0).",
		},
		{
			"concept": "compress_rate_csa",
			"transformers_key": "compress_rate_csa",
			"inference_key": None,
			"canonical_path": "attention_schedule.transformers_compress_rates.compressed_sparse_attention",
			"note": "Legacy Transformers config kwarg; folded into compress_rates at __post_init__ time.",
		},
		{
			"concept": "compress_rate_hca",
			"transformers_key": "compress_rate_hca",
			"inference_key": None,
			"canonical_path": "attention_schedule.transformers_compress_rates.heavily_compressed_attention",
			"note": "Legacy Transformers config kwarg; folded into compress_rates at __post_init__ time.",
		},
		{"concept": "moe_inter_dim", "transformers_key": "moe_intermediate_size", "inference_key": "moe_inter_dim", "canonical_path": "moe.moe_inter_dim"},
		{"concept": "n_routed_experts", "transformers_key": "n_routed_experts", "inference_key": "n_routed_experts", "canonical_path": "moe.n_routed_experts"},
		{"concept": "n_shared_experts", "transformers_key": "n_shared_experts", "inference_key": "n_shared_experts", "canonical_path": "moe.n_shared_experts"},
		{"concept": "n_activated_experts", "transformers_key": "num_experts_per_tok", "inference_key": "n_activated_experts", "canonical_path": "moe.n_activated_experts"},
		{"concept": "n_hash_layers", "transformers_key": "num_hash_layers", "inference_key": "n_hash_layers", "canonical_path": "moe.n_hash_layers"},
		{
			"concept": "mlp_layer_types",
			"transformers_key": "mlp_layer_types",
			"inference_key": None,
			"canonical_path": "moe.transformers_mlp_layer_types",
			"note": "Transformers DeepseekV4Config.mlp_layer_types is a per-trunk-layer MoE schedule (length num_hidden_layers). DS4 derives it from num_hash_layers for interpreting external runtimes.",
		},
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
		{
			"concept": "expert_dtype",
			"transformers_key": "expert_dtype",
			"inference_key": "expert_dtype",
			"canonical_path": "quantization.inference_config.expert_dtype",
			"transformers_key_optional": True,
			"note": "HF refs/pr/14 removes config.json expert_dtype; treat inference/config.json expert_dtype as canonical.",
		},
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

	return {
		"fields": fields,
		"by_transformers_key": by_transformers_key,
		"by_inference_key": by_inference_key,
		"transformers_cache_layers": {
			"reference_source": "https://huggingface.co/docs/transformers/main/model_doc/deepseek_v4 (Cache layers; accessed 2026-05-11)",
			"dynamic_cache_note": "Transformers uses DynamicCache(config=...) to select cache layer classes per config.layer_types[i].",
			"layer_type_to_cache_class": {
				"compressed_sparse_attention": "DeepseekV4CSACache",
				"heavily_compressed_attention": "DeepseekV4HCACache",
			},
			"note": "This mapping is for interpreting Transformers runtime behavior/logs; upstream DeepSeek-V4-Flash reference code derives layer types from compress_ratios instead of shipping config.layer_types[].",
		},
	}


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
	mtp_sem = parse_inference_mtp_semantics(INFERENCE_MODEL_PY) if INFERENCE_MODEL_PY.exists() else {}
	enc = parse_encoding_constants(ENCODING_PY)

	upstream_commit = (FIX / "upstream_commit.txt").read_text(encoding="utf-8").strip()
	compress_ratios = list(cfg["compress_ratios"])
	n_layers = int(cfg["num_hidden_layers"])
	n_mtp_layers = int(cfg.get("num_nextn_predict_layers", 0))
	mtp_ratios = compress_ratios[n_layers:]
	layer_types = [layer_type_from_ratio(int(r)) for r in compress_ratios[:n_layers]]
	transformers_layer_types = [transformers_layer_type_from_ratio(int(r)) for r in compress_ratios[:n_layers]]
	transformers_mtp_layer_types = [transformers_layer_type_from_ratio(int(r)) for r in mtp_ratios]
	layer_ids_by_type = {t: [i for i, v in enumerate(layer_types) if v == t] for t in ("sliding", "csa", "hca")}
	layer_ids_by_compress_ratio: dict[str, list[int]] = {}
	for i, r in enumerate(compress_ratios[:n_layers]):
		layer_ids_by_compress_ratio.setdefault(str(int(r)), []).append(int(i))
	transformers_layer_types_full = list(transformers_layer_types) + list(transformers_mtp_layer_types)
	type_counts = {t: layer_types.count(t) for t in ("sliding", "csa", "hca")}
	transformers_mlp_layer_types = [("hash_moe" if i < int(cfg["num_hash_layers"]) else "moe") for i in range(n_layers)]
	moe_score_layer_ids = [int(i) for i in range(int(cfg["num_hash_layers"]), n_layers)]

	weight_map = idx.get("weight_map", {})
	weight_keys = sorted(weight_map.keys())
	tensor_keys = build_tensor_key_summary(weight_keys, n_layers, int(cfg["n_routed_experts"]))
	augment_tensor_key_summary_with_trunk_layer_expectations(
		tensor_keys,
		weight_keys,
		[int(x) for x in compress_ratios[:n_layers]],
		int(cfg["num_hash_layers"]),
	)
	weight_map_files = [str(v) for v in weight_map.values()]
	weight_map_file_counts = Counter(weight_map_files)
	weight_map_keys_sha256 = sha256_lines(weight_keys)
	top_level_keys = [k for k in weight_keys if not (k.startswith("layers.") or k.startswith("mtp."))]
	weight_map_top_level_keys_sha256 = sha256_lines(sorted(top_level_keys))
	weight_map_prefix_fingerprints = build_weight_key_prefix_fingerprints(weight_keys)
	mtp_prefix_fp = weight_map_prefix_fingerprints.get("mtp", {}) if isinstance(weight_map_prefix_fingerprints, dict) else {}
	layers_prefix_fp = weight_map_prefix_fingerprints.get("layers", {}) if isinstance(weight_map_prefix_fingerprints, dict) else {}
	top_level_tensor_key_count = sum(int(v.get("count", 0)) for k, v in weight_map_prefix_fingerprints.items() if k not in ("layers", "mtp") and isinstance(v, dict))

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
		"DeepSeek_V4.pdf",
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

	mtp_sidecar = build_ds4_mtp_sidecar_contract()
	requested_hf_rev = "main"
	pinned_hf_rev = requested_hf_rev
	if isinstance(upstream_commit, str) and len(upstream_commit) == 40:
		pinned_hf_rev = upstream_commit

	contract = {
		"format_version": 1,
		"model": "deepseek_v4_flash",
		"upstream": {
			"hf_repo_id": "deepseek-ai/DeepSeek-V4-Flash",
			"hf_revision": pinned_hf_rev,
			"hf_revision_requested": requested_hf_rev,
			"hf_revision_pinned": pinned_hf_rev,
			"x_repo_commit": upstream_commit,
			"fixtures_sha256": fixture_sha,
			"fixtures": {
				"config_json": "config.json",
				"technical_report_pdf": "DeepSeek_V4.pdf",
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
		"mtp_sidecar": mtp_sidecar,
		"compat": build_compat_mappings(),
		"oracle": build_oracle_contract(),
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
		"tensor_shapes": build_tensor_shapes(cfg, inf, inf_model),
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
			"main_compress_ratios": [int(r) for r in compress_ratios[:n_layers]],
			"main_layer_types": layer_types,
			"main_layer_ids_by_type": layer_ids_by_type,
			"main_layer_ids_by_compress_ratio": layer_ids_by_compress_ratio,
			"transformers_main_layer_types": transformers_layer_types,
			"transformers_layer_types": transformers_layer_types_full,
			"transformers_compress_rates": {
				"compressed_sparse_attention": 4,
				"heavily_compressed_attention": 128,
				"sliding_attention": 0,
			},
			"type_counts": type_counts,
			"mtp_compress_ratios": [int(r) for r in mtp_ratios],
			"transformers_mtp_layer_types": transformers_mtp_layer_types,
		},
			"cache": {
				"window_size": window_size,
				"kv_cache_size_formula": "window_size + (max_seq_len // compress_ratio if compress_ratio else 0)",
				"kv_cache_shape": "[max_batch_size, kv_cache_size, head_dim]",
				"layer_cache_kind_by_layer_id": list(layer_types),
				"layer_compress_ratio_by_layer_id": [int(r) for r in compress_ratios[:n_layers]],
				"mtp_cache_kind_by_mtp_layer_id": [layer_type_from_ratio(int(r)) for r in mtp_ratios],
				"mtp_compress_ratio_by_mtp_layer_id": [int(r) for r in mtp_ratios],
				"update_semantics": sem.get("cache_update_semantics", {}) if isinstance(sem, dict) else {},
				"topk_index_helpers": sem.get("cache_topk_index_helpers", {}) if isinstance(sem, dict) else {},
				"semantics": {
					"source_helpers": sem.get("cache_source_helpers", {}) if isinstance(sem, dict) else {},
				},
				"compression_semantics": {
					"reference_source": "fixtures/model_contract/deepseek_v4_flash/inference/model.py (Compressor, Indexer, Attention)",
					"overlap_rule": "overlap = (compress_ratio == 4)",
					"indexer_present_rule": "indexer exists iff compress_ratio == 4 (CSA only)",
					"attention_compressor": {
						"rotate": False,
						"kv_quant_rule": "act_quant(kv[..., :-rope_head_dim], group=64, inplace=True); rope dims stay bf16",
					},
					"indexer_scoring_path": {
						"compressor_rotate": True,
						"kv_quant_rule": "rotate_activation(kv); fp4_act_quant(kv, fp4_block_size, inplace=True)",
						"q_quant_rule": "rotate_activation(q); fp4_act_quant(q, fp4_block_size, inplace=True)",
					},
					"notes": [
						"The attention KV compressor (used for actual attention) runs with rotate=false; only the CSA Indexer scoring path uses rotate=true + FP4 act quantization.",
						"Both compressors apply RoPE to the trailing rope_head_dim slice before activation quantization; non-RoPE dims are quantized.",
					],
				},
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
			"swiglu_limit": float(inf["swiglu_limit"]) if "swiglu_limit" in inf else None,
			"n_hash_layers": int(cfg["num_hash_layers"]),
			"score_layer_ids": moe_score_layer_ids,
			"transformers_mlp_layer_types": transformers_mlp_layer_types,
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
						"num_nextn_predict_layers": int(cfg["num_nextn_predict_layers"]),
						"compress_ratios": [int(r) for r in mtp_ratios],
						"compress_ratio_rule": "compress_ratios[n_layers+mtp_id] == 0",
						"namespace_prefix": "mtp.{j}.",
						"checkpoint_key_fingerprint": {
						"note": "Fingerprint of the official checkpoint key subset under the mtp.* namespace (from model.safetensors.index.json weight_map keys).",
						"tensor_key_count": mtp_prefix_fp.get("count", None),
						"keys_sha256": mtp_prefix_fp.get("keys_sha256", None),
					},
					"semantics": mtp_sem,
						"trust_gates": {
							"artifact_requires_mtp_contract_complete": True,
							"artifact_requires_mtp_keys_sha256_match_official": True,
							"artifact_requires_namespace_prefix": "mtp.{j}.",
							"artifact_requires_mtp_namespace_expected_complete": True,
							"artifact_requires_mtp_namespace_has_mtp0": True,
							"oracle_requires_include_mtp": True,
						"oracle_requires_mtp_trace": True,
						"oracle_generator_hint": "scripts/model_contract_generate_deepseek_v4_flash_oracle.py --include-mtp",
						"acceptance_requires_prefill_and_decode": True,
						"acceptance_topk_ids_exact": True,
						"acceptance_logits_tolerance_note": "Tolerance depends on quantization/kernels; see docs/model-contract.md",
					},
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
					"scale_dtype": inf.get("scale_dtype", (inf_model.get("modelargs_defaults", {}) if isinstance(inf_model, dict) else {}).get("scale_dtype")),
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
					"weight_map_layers_tensor_key_count": int(layers_prefix_fp.get("count", 0)) if isinstance(layers_prefix_fp, dict) else None,
					"weight_map_mtp_tensor_key_count": int(mtp_prefix_fp.get("count", 0)) if isinstance(mtp_prefix_fp, dict) else None,
					"weight_map_keys_sha256": weight_map_keys_sha256,
					"weight_map_top_level_keys_sha256": weight_map_top_level_keys_sha256,
					"weight_map_top_level_tensor_key_count": int(top_level_tensor_key_count),
					"weight_map_prefix_fingerprints": weight_map_prefix_fingerprints,
					"weight_map_layers_keys_sha256": layers_prefix_fp.get("keys_sha256", None),
					"weight_map_mtp_keys_sha256": mtp_prefix_fp.get("keys_sha256", None),
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
	if not out_path.is_absolute():
		out_path = (ROOT / out_path).resolve()
	else:
		out_path = out_path.resolve()

	if args.check and out_path.exists():
		prev = json.loads(out_path.read_text(encoding="utf-8"))
		if prev != contract:
			print(f"ERROR: {out_path} is stale; re-run without --check to regenerate")
			return 1
		print(f"OK: {out_path} up to date")
		return 0

	dump_json(out_path, contract)
	try:
		display = str(out_path.relative_to(ROOT))
	except ValueError:
		display = str(out_path)
	print(f"OK: wrote {display}")
	return 0


if __name__ == "__main__":
	raise SystemExit(main())
