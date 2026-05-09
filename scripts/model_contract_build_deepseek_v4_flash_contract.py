#!/usr/bin/env python3

import argparse
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

def parse_encoding_constants(encoding_py: Path) -> dict:
	if not encoding_py.exists():
		return {"encoding_constants": None}

	text = encoding_py.read_text(encoding="utf-8")

	def find_str(field: str) -> Optional[str]:
		for line in text.splitlines():
			line = line.strip()
			if not line.startswith(field + ":"):
				continue
			if " = " not in line:
				continue
			rhs = line.split("=", 1)[1].strip()
			if rhs.startswith('"') and rhs.endswith('"'):
				return rhs[1:-1]
			if rhs.startswith("'") and rhs.endswith("'"):
				return rhs[1:-1]
		return None

	def find_template_concat(field: str, suffix_field: str, suffix_value: Optional[str]) -> Optional[str]:
		if suffix_value is None:
			return None
		for line in text.splitlines():
			line = line.strip()
			if not line.startswith(field + ":"):
				continue
			if " = " not in line:
				continue
			rhs = line.split("=", 1)[1].strip()
			needle = "+ " + suffix_field
			if needle not in rhs:
				continue
			prefix = rhs.split(needle, 1)[0].strip()
			if prefix.startswith('"') and prefix.endswith('"'):
				return prefix[1:-1] + suffix_value
			if prefix.startswith("'") and prefix.endswith("'"):
				return prefix[1:-1] + suffix_value
		return None

	bos_token = find_str("bos_token")
	eos_token = find_str("eos_token")
	thinking_start_token = find_str("thinking_start_token")
	thinking_end_token = find_str("thinking_end_token")
	dsml_token = find_str("dsml_token")
	tool_calls_block_name = find_str("tool_calls_block_name")
	assistant_msg_wo_eos_template = find_str("assistant_msg_wo_eos_template")
	assistant_msg_template = find_str("assistant_msg_template")
	if assistant_msg_template is None:
		assistant_msg_template = find_template_concat("assistant_msg_template", "eos_token", eos_token)

	return {
		"encoding_constants": {
			"bos_token": bos_token,
			"eos_token": eos_token,
			"thinking_start_token": thinking_start_token,
			"thinking_end_token": thinking_end_token,
			"dsml_token": dsml_token,
			"tool_calls_block_name": tool_calls_block_name,
			"assistant_msg_template": assistant_msg_template,
			"assistant_msg_wo_eos_template": assistant_msg_wo_eos_template,
		}
	}


def layer_type_from_ratio(ratio: int) -> str:
	if ratio == 0:
		return "sliding"
	if ratio == 4:
		return "csa"
	return "hca"


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

	def find_unique_act_quant_group_sizes() -> list[int]:
		sizes: set[int] = set()
		for raw in text.splitlines():
			line = raw.strip()
			if not line.startswith("act_quant("):
				continue
			parts = [p.strip() for p in line.split(",")]
			if len(parts) < 3:
				continue
			if "[...:-rd]" not in parts[0].replace(" ", "") and ":-rd" not in parts[0]:
				continue
			try:
				sizes.add(int(parts[1]))
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
		{"concept": "rope_theta", "transformers_key": "rope_theta", "inference_key": "rope_theta", "canonical_path": "yarn_rope.rope_theta"},
		{"concept": "compress_rope_theta", "transformers_key": "compress_rope_theta", "inference_key": "compress_rope_theta", "canonical_path": "yarn_rope.compress_rope_theta"},
		{"concept": "original_seq_len", "transformers_key": "original_max_position_embeddings", "inference_key": "original_seq_len", "canonical_path": "yarn_rope.original_seq_len"},
		{"concept": "rope_factor", "transformers_key": "rope_scaling.factor", "inference_key": "rope_factor", "canonical_path": "yarn_rope.rope_factor"},
		{"concept": "beta_fast", "transformers_key": "rope_scaling.beta_fast", "inference_key": "beta_fast", "canonical_path": "yarn_rope.beta_fast"},
		{"concept": "beta_slow", "transformers_key": "rope_scaling.beta_slow", "inference_key": "beta_slow", "canonical_path": "yarn_rope.beta_slow"},
		{"concept": "dtype", "transformers_key": None, "inference_key": "dtype", "canonical_path": "quantization.inference_config.dtype"},
		{"concept": "expert_dtype", "transformers_key": None, "inference_key": "expert_dtype", "canonical_path": "quantization.inference_config.expert_dtype"},
		{"concept": "scale_fmt", "transformers_key": None, "inference_key": "scale_fmt", "canonical_path": "quantization.inference_config.scale_fmt"},
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
	inf_model = parse_inference_quant_constants(INFERENCE_MODEL_PY) if INFERENCE_MODEL_PY.exists() else {}
	enc = parse_encoding_constants(ENCODING_PY)

	upstream_commit = (FIX / "upstream_commit.txt").read_text(encoding="utf-8").strip()
	compress_ratios = list(cfg["compress_ratios"])
	n_layers = int(cfg["num_hidden_layers"])
	mtp_ratios = compress_ratios[n_layers:]
	layer_types = [layer_type_from_ratio(int(r)) for r in compress_ratios[:n_layers]]
	type_counts = {t: layer_types.count(t) for t in ("sliding", "csa", "hca")}

	weight_map = idx.get("weight_map", {})
	weight_keys = sorted(weight_map.keys())
	tensor_keys = build_tensor_key_summary(weight_keys, n_layers, int(cfg["n_routed_experts"]))

	block_size = inf_model.get("inference_model_constants", {}).get("block_size", None)
	fp4_block_size = inf_model.get("inference_model_constants", {}).get("fp4_block_size", None)

	fixture_sha = {}
	for rel in (
		"config.json",
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
			},
		},
		"compat": build_compat_mappings(),
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
			"window_size": int(cfg["sliding_window"]),
			"kv_cache_size_formula": "window_size + (max_seq_len // compress_ratio if compress_ratio else 0)",
			"kv_cache_shape": "[max_batch_size, kv_cache_size, head_dim]",
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
