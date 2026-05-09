#!/usr/bin/env python3

import json
import re
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
FIX = ROOT / "fixtures" / "model_contract" / "deepseek_v4_flash"


def load_json(path: Path):
	with path.open("r", encoding="utf-8") as f:
		return json.load(f)


@dataclass(frozen=True)
class Failure:
	code: int
	msg: str


def find_mtp_layer_ids(weight_keys: set[str]) -> list[int]:
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


def main() -> int:
	failures: list[Failure] = []

	cfg = load_json(FIX / "config.json")
	inf = load_json(FIX / "inference" / "config.json")
	idx = load_json(FIX / "model.safetensors.index.json")
	weight_map = idx.get("weight_map", {})
	weight_keys = set(weight_map.keys())

	upstream_commit_path = FIX / "upstream_commit.txt"
	upstream_commit = upstream_commit_path.read_text(encoding="utf-8").strip() if upstream_commit_path.exists() else ""
	if not re.fullmatch(r"[0-9a-f]{40}", upstream_commit):
		failures.append(Failure(1, f"fixtures must include a pinned upstream commit hash in {upstream_commit_path}"))

	# Contract summary must be generated from fixtures and stay in sync.
	contract_summary = FIX / "contract_summary.json"
	if not contract_summary.exists():
		failures.append(Failure(11, f"missing contract summary fixture: {contract_summary} (run scripts/model_contract_build_deepseek_v4_flash_contract.py)"))
	else:
		r = subprocess.run([sys.executable, str(ROOT / "scripts" / "model_contract_build_deepseek_v4_flash_contract.py"), "--check"], cwd=str(ROOT))
		if r.returncode != 0:
			failures.append(Failure(12, f"contract summary fixture is stale: {contract_summary} (re-run scripts/model_contract_build_deepseek_v4_flash_contract.py)"))
		else:
			try:
				summary = load_json(contract_summary)
				group_sizes = summary.get("quantization", {}).get("inference_model_constants", {}).get("kv_act_quant_group_sizes", [])
				if 64 not in list(group_sizes):
					failures.append(Failure(13, f"contract summary missing expected kv_act_quant_group_sizes=64: {contract_summary}"))
			except Exception as e:
				failures.append(Failure(14, f"failed to parse contract summary JSON {contract_summary}: {e}"))

	# Cross-check the two config sources for the fields they share.
	for k in ("vocab_size", "hidden_size", "num_hidden_layers", "num_attention_heads", "head_dim", "q_lora_rank", "o_groups", "o_lora_rank", "compress_ratios"):
		if k not in cfg:
			failures.append(Failure(2, f"missing {k} in fixtures config.json"))
			continue
	if "dim" in inf and cfg.get("hidden_size") is not None and int(inf["dim"]) != int(cfg["hidden_size"]):
		failures.append(Failure(3, f"inference/config.json dim={inf['dim']} disagrees with config.json hidden_size={cfg['hidden_size']}"))
	if "n_layers" in inf and cfg.get("num_hidden_layers") is not None and int(inf["n_layers"]) != int(cfg["num_hidden_layers"]):
		failures.append(Failure(4, f"inference/config.json n_layers={inf['n_layers']} disagrees with config.json num_hidden_layers={cfg['num_hidden_layers']}"))
	if "n_heads" in inf and cfg.get("num_attention_heads") is not None and int(inf["n_heads"]) != int(cfg["num_attention_heads"]):
		failures.append(Failure(5, f"inference/config.json n_heads={inf['n_heads']} disagrees with config.json num_attention_heads={cfg['num_attention_heads']}"))
	if list(inf.get("compress_ratios", [])) and list(cfg.get("compress_ratios", [])) and list(inf["compress_ratios"]) != list(cfg["compress_ratios"]):
		failures.append(Failure(6, "inference/config.json compress_ratios differs from config.json compress_ratios"))

	n_layers = int(inf["n_layers"])
	n_hash_layers = int(inf["n_hash_layers"])
	n_routed_experts = int(inf["n_routed_experts"])
	compress_ratios = list(inf["compress_ratios"])

	mtp_layer_ids = find_mtp_layer_ids(weight_keys)
	if mtp_layer_ids and mtp_layer_ids != list(range(len(mtp_layer_ids))):
		failures.append(Failure(7, f"mtp layer ids must be 0..N-1 contiguous, got {mtp_layer_ids}"))
	n_mtp_layers = len(mtp_layer_ids)

	if len(compress_ratios) != (n_layers + n_mtp_layers):
		failures.append(Failure(8, f"compress_ratios length must be n_layers+n_mtp_layers ({n_layers}+{n_mtp_layers}), got {len(compress_ratios)}"))
	for j in range(n_mtp_layers):
		if compress_ratios[n_layers + j] != 0:
			failures.append(Failure(9, f"mtp compress_ratio must be 0 (sliding-only) at compress_ratios[{n_layers + j}], got {compress_ratios[n_layers + j]}"))

	# Top-level required tensors.
	for k in ("embed.weight", "norm.weight", "head.weight", "hc_head_fn", "hc_head_base", "hc_head_scale"):
		if k not in weight_keys:
			failures.append(Failure(10, f"missing required tensor key: {k}"))

	# Pre-scan expert key counts (avoid an O(layers*keys) loop).
	expert_key_count = [0 for _ in range(n_layers)]
	expert_id_seen: list[set[int]] = [set() for _ in range(n_layers)]
	for k in weight_keys:
		if not k.startswith("layers."):
			continue
		parts = k.split(".")
		if len(parts) < 6:
			continue
		try:
			layer_id = int(parts[1])
		except ValueError:
			continue
		if layer_id < 0 or layer_id >= n_layers:
			continue
		if parts[2] != "ffn" or parts[3] != "experts":
			continue
		try:
			eid = int(parts[4])
		except ValueError:
			continue
		expert_id_seen[layer_id].add(eid)
		expert_key_count[layer_id] += 1

	# Per-layer required key schedule derived from inference/model.py and compress_ratios.
	for layer_id in range(n_layers):
		ratio = int(compress_ratios[layer_id])
		base = f"layers.{layer_id}."

		def req(suffix: str):
			k = base + suffix
			if k not in weight_keys:
				failures.append(Failure(20, f"missing required tensor key: {k}"))

		# Core attention + norms.
		for suffix in (
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
		):
			req(suffix)

		# Per-layer cache compression auxiliaries.
		if ratio == 0:
			for bad_prefix in ("attn.compressor.", "attn.indexer."):
				if any(k.startswith(base + bad_prefix) for k in weight_keys):
					failures.append(Failure(21, f"unexpected {base}{bad_prefix}* keys for sliding-only layer (compress_ratio=0)"))
		else:
			for suffix in (
				"attn.compressor.ape",
				"attn.compressor.norm.weight",
				"attn.compressor.wgate.weight",
				"attn.compressor.wkv.weight",
			):
				req(suffix)
			if ratio == 4:
				for suffix in (
					"attn.indexer.wq_b.weight",
					"attn.indexer.wq_b.scale",
					"attn.indexer.weights_proj.weight",
					"attn.indexer.compressor.ape",
					"attn.indexer.compressor.norm.weight",
					"attn.indexer.compressor.wgate.weight",
					"attn.indexer.compressor.wkv.weight",
				):
					req(suffix)
			else:
				if any(k.startswith(base + "attn.indexer.") for k in weight_keys):
					failures.append(Failure(22, f"unexpected {base}attn.indexer.* keys for non-CSA layer (compress_ratio={ratio})"))

		# MoE gate conditional: hash layers use tid2eid table; others use gate.bias.
		req("ffn.gate.weight")
		if layer_id < n_hash_layers:
			req("ffn.gate.tid2eid")
			if (base + "ffn.gate.bias") in weight_keys:
				failures.append(Failure(23, f"unexpected gate.bias in hash-routed layer {layer_id}"))
		else:
			req("ffn.gate.bias")
			if (base + "ffn.gate.tid2eid") in weight_keys:
				failures.append(Failure(24, f"unexpected gate.tid2eid in score-routed layer {layer_id}"))

		# Experts: require 0..n_routed_experts-1 and the expected tensor key count.
		if expert_id_seen[layer_id] != set(range(n_routed_experts)):
			failures.append(Failure(25, f"layer {layer_id} expert id set mismatch: expected 0..{n_routed_experts-1} got {sorted(expert_id_seen[layer_id])[:8]}... ({len(expert_id_seen[layer_id])} total)"))
		expected_expert_key_count = n_routed_experts * 6
		if expert_key_count[layer_id] != expected_expert_key_count:
			failures.append(Failure(26, f"layer {layer_id} expert tensor key count mismatch: expected {expected_expert_key_count} got {expert_key_count[layer_id]}"))

		for suffix in (
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
		):
			req(suffix)

	# MTP blocks: verify they have the expected additional projection/norm keys.
	for mtp_id in mtp_layer_ids:
		base = f"mtp.{mtp_id}."

		def req_mtp(suffix: str):
			k = base + suffix
			if k not in weight_keys:
				failures.append(Failure(30, f"missing required tensor key: {k}"))

		for suffix in (
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
			"ffn.gate.weight",
			"ffn.gate.bias",
		):
			req_mtp(suffix)

	# Tokenizer/encoding oracle: run upstream-provided encoding tests (no weights required).
	enc_test = FIX / "encoding" / "test_encoding_dsv4.py"
	if not enc_test.exists():
		failures.append(Failure(40, f"missing encoding oracle test file: {enc_test}"))
	else:
		r = subprocess.run([sys.executable, str(enc_test)], cwd=str(enc_test.parent))
		if r.returncode != 0:
			failures.append(Failure(41, "DeepSeek V4 encoding oracle failed (see test output above)"))

	# Optional: structural validation for a Spark-generated logits oracle (weights are not shipped here).
	oracle_path = FIX / "oracle" / "logits_oracle.json"
	if oracle_path.exists():
		try:
			oracle = load_json(oracle_path)
		except Exception as e:
			failures.append(Failure(50, f"failed to parse logits oracle JSON {oracle_path}: {e}"))
			oracle = None
		if oracle is not None:
			if int(oracle.get("format_version", 0)) != 1:
				failures.append(Failure(51, f"logits oracle has unexpected format_version (expected 1): {oracle_path}"))
			if str(oracle.get("upstream_commit", "")) != upstream_commit:
				failures.append(Failure(54, f"logits oracle upstream_commit must match pinned fixtures upstream_commit.txt ({upstream_commit}): {oracle_path}"))
			ws = oracle.get("world_size")
			if not isinstance(ws, int) or ws < 1:
				failures.append(Failure(55, f"logits oracle world_size must be an integer >= 1: {oracle_path}"))
			seed = oracle.get("seed")
			if not isinstance(seed, int):
				failures.append(Failure(56, f"logits oracle seed must be an integer: {oracle_path}"))
			ref = oracle.get("reference")
			if not isinstance(ref, dict):
				failures.append(Failure(57, f"logits oracle missing reference object: {oracle_path}"))
			else:
				ma = ref.get("model_args")
				if not isinstance(ma, dict):
					failures.append(Failure(58, f"logits oracle reference.model_args must be an object: {oracle_path}"))
				else:
					if not isinstance(ma.get("n_layers"), int) or int(ma.get("n_layers")) != n_layers:
						failures.append(Failure(59, f"logits oracle reference.model_args.n_layers must match fixtures n_layers={n_layers}: {oracle_path}"))
					if not isinstance(ma.get("window_size"), int) or int(ma.get("window_size")) != int(inf["window_size"]):
						failures.append(Failure(60, f"logits oracle reference.model_args.window_size must match fixtures window_size={inf['window_size']}: {oracle_path}"))
					crl = ma.get("compress_ratios_len")
					if not isinstance(crl, int) or crl != len(compress_ratios):
						failures.append(Failure(61, f"logits oracle reference.model_args.compress_ratios_len must match fixtures compress_ratios length={len(compress_ratios)}: {oracle_path}"))

			sha_map = oracle.get("tokenizer_sha256", {})
			if sha_map is not None and not isinstance(sha_map, dict):
				failures.append(Failure(62, f"logits oracle tokenizer_sha256 must be an object when present: {oracle_path}"))
			if isinstance(sha_map, dict):
				for k, v in list(sha_map.items())[:4]:
					if not isinstance(k, str) or not isinstance(v, str) or not re.fullmatch(r"[0-9a-f]{64}", v):
						failures.append(Failure(63, f"logits oracle tokenizer_sha256 entries must be sha256 hex strings: {oracle_path}"))
						break

			cases = oracle.get("cases")
			if not isinstance(cases, list) or not cases:
				failures.append(Failure(52, f"logits oracle must contain non-empty cases[]: {oracle_path}"))
			else:
				include_mtp = bool(oracle.get("include_mtp", False))
				if include_mtp and n_mtp_layers < 1:
					failures.append(Failure(64, f"logits oracle requests include_mtp but fixtures contain no mtp.* weights: {oracle_path}"))
				for c in cases[:4]:
					if "id" not in c or "prompt_tokens" not in c or "trace" not in c:
						failures.append(Failure(53, f"logits oracle case missing required keys: {oracle_path}"))
						break
					if include_mtp:
						mt = c.get("mtp_trace")
						if not isinstance(mt, list):
							failures.append(Failure(65, f"logits oracle include_mtp requires cases[].mtp_trace[] list: {oracle_path}"))
							break
						tr = c.get("trace")
						if isinstance(tr, list) and len(mt) != len(tr):
							failures.append(Failure(66, f"logits oracle cases[].mtp_trace must match cases[].trace length (got {len(mt)} vs {len(tr)}): {oracle_path}"))
							break
						if mt and ("argmax_id" not in mt[0] or "topk_ids" not in mt[0] or "topk_logits" not in mt[0]):
							failures.append(Failure(67, f"logits oracle cases[].mtp_trace entries missing required keys: {oracle_path}"))
							break

	if failures:
		for f in failures:
			print(f"ERROR[{f.code}]: {f.msg}")
		return 1

	print("OK: DeepSeek V4 Flash fixtures + tensor-key contract verified")
	return 0


if __name__ == "__main__":
	raise SystemExit(main())
