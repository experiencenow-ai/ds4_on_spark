#!/usr/bin/env python3

import json
import re
import subprocess
import sys
from dataclasses import dataclass
from hashlib import sha256
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

def sha256_lines(lines: list[str]) -> str:
	h = sha256()
	for line in lines:
		h.update(line.encode("utf-8"))
		h.update(b"\n")
	return h.hexdigest()

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
				up = summary.get("upstream", {}) if isinstance(summary, dict) else {}
				fixture_sha = up.get("fixtures_sha256", {}) if isinstance(up, dict) else {}
				if not isinstance(fixture_sha, dict):
					fixture_sha = {}
				expected_sha_keys = [
					"encoding/tests/test_input_1.json",
					"encoding/tests/test_output_1.txt",
					"encoding/tests/test_input_4.json",
					"encoding/tests/test_output_4.txt",
					"oracle/prompts.json",
					"upstream_commit.txt",
				]
				for k in expected_sha_keys:
					if fixture_sha.get(k) is None:
						failures.append(Failure(32, f"contract summary missing upstream.fixtures_sha256 entry for {k}: {contract_summary}"))
						break
				enc_test_keys = [k for k in fixture_sha.keys() if isinstance(k, str) and k.startswith("encoding/tests/")]
				if len(enc_test_keys) < 8:
					failures.append(Failure(33, f"contract summary must record sha256 for encoding oracle vectors under encoding/tests/* (expected >=8, got {len(enc_test_keys)}): {contract_summary}"))

				enc = summary.get("encoding_constants", {}) if isinstance(summary, dict) else {}
				tok = summary.get("tokenizer", {}) if isinstance(summary, dict) else {}
				if isinstance(enc, dict) and isinstance(tok, dict):
					if enc.get("bos_token") != tok.get("bos_token"):
						failures.append(Failure(34, f"contract summary encoding_constants.bos_token must match tokenizer.bos_token: {contract_summary}"))
					if enc.get("eos_token") != tok.get("eos_token"):
						failures.append(Failure(35, f"contract summary encoding_constants.eos_token must match tokenizer.eos_token: {contract_summary}"))
					tok_js = tok.get("tokenizer_json_summary")
					if not isinstance(tok_js, dict):
						failures.append(Failure(40, f"contract summary missing tokenizer.tokenizer_json_summary (expected dict): {contract_summary}"))
					else:
						if tok_js.get("model_type") != "BPE":
							failures.append(Failure(41, f"contract summary tokenizer.tokenizer_json_summary.model_type must be BPE: {contract_summary}"))
						if tok_js.get("effective_vocab_size_matches_config") is not True:
							failures.append(Failure(42, f"contract summary tokenizer.tokenizer_json_summary.effective_vocab_size_matches_config must be true: {contract_summary}"))
						pre = tok_js.get("pre_tokenizer")
						post = tok_js.get("post_processor")
						dec = tok_js.get("decoder")
						if not (isinstance(pre, dict) and pre.get("type") == "Sequence"):
							failures.append(Failure(43, f"contract summary tokenizer.tokenizer_json_summary.pre_tokenizer must be a Sequence: {contract_summary}"))
						if not (isinstance(post, dict) and post.get("type") == "ByteLevel"):
							failures.append(Failure(44, f"contract summary tokenizer.tokenizer_json_summary.post_processor must be ByteLevel: {contract_summary}"))
						if not (isinstance(dec, dict) and dec.get("type") == "ByteLevel"):
							failures.append(Failure(45, f"contract summary tokenizer.tokenizer_json_summary.decoder must be ByteLevel: {contract_summary}"))
					required_enc_fields = [
						"system_msg_template",
						"user_msg_template",
						"assistant_msg_template",
						"assistant_msg_wo_eos_template",
						"thinking_template",
						"tool_call_template",
						"tool_calls_template",
					]
					for f in required_enc_fields:
						v = enc.get(f)
						if not (isinstance(v, str) and v):
							failures.append(Failure(37, f"contract summary missing encoding_constants.{f} (expected non-empty string): {contract_summary}"))
							break
					task_tokens = enc.get("ds_task_sp_tokens")
					if not isinstance(task_tokens, dict):
						failures.append(Failure(38, f"contract summary missing encoding_constants.ds_task_sp_tokens (expected dict): {contract_summary}"))
					else:
						expected_task_keys = {"action", "query", "authority", "domain", "title", "read_url"}
						if set(task_tokens.keys()) != expected_task_keys:
							failures.append(Failure(39, f"contract summary encoding_constants.ds_task_sp_tokens keys mismatch (expected {sorted(expected_task_keys)}): {contract_summary}"))
				if upstream_commit and up.get("x_repo_commit") != upstream_commit:
					failures.append(Failure(36, f"contract summary upstream.x_repo_commit must match fixtures upstream_commit.txt ({upstream_commit}): {contract_summary}"))

				group_sizes = summary.get("quantization", {}).get("inference_model_constants", {}).get("kv_act_quant_group_sizes", [])
				if 64 not in list(group_sizes):
					failures.append(Failure(13, f"contract summary missing expected kv_act_quant_group_sizes=64: {contract_summary}"))
				mla = summary.get("mla", {})
				if mla.get("output_derotate_present") is not True:
					failures.append(Failure(15, f"contract summary missing MLA output de-rotation marker (mla.output_derotate_present=true): {contract_summary}"))
				if mla.get("q_extra_rms_norm_present") is not True:
					failures.append(Failure(16, f"contract summary missing MLA Q extra RMS normalization marker (mla.q_extra_rms_norm_present=true): {contract_summary}"))
				cache_update = summary.get("cache", {}).get("update_semantics", {})
				ring_expr = cache_update.get("decode_sliding_ring_update_expr")
				if not (isinstance(ring_expr, str) and "start_pos % win" in ring_expr):
					failures.append(Failure(17, f"contract summary missing decode sliding-ring update expression containing 'start_pos % win': {contract_summary}"))
				moe_sem = summary.get("moe", {}).get("semantics", {})
				if moe_sem.get("bias_affects_selection_only_comment") is None:
					failures.append(Failure(18, f"contract summary missing MoE bias selection-only note (moe.semantics.bias_affects_selection_only_comment): {contract_summary}"))
				moe = summary.get("moe", {})
				moe_hash = moe.get("hash_routing", {}) if isinstance(moe, dict) else {}
				try:
					n_hash = int(moe.get("n_hash_layers", 0)) if isinstance(moe, dict) else 0
				except Exception:
					n_hash = 0
					if n_hash > 0:
						if not isinstance(moe_hash, dict):
							failures.append(Failure(40, f"contract summary missing moe.hash_routing dict (hash routing is enabled with n_hash_layers={n_hash}): {contract_summary}"))
						else:
							expected_ids = list(range(n_hash))
							if moe_hash.get("hash_layer_ids") != expected_ids:
								failures.append(Failure(41, f"contract summary moe.hash_routing.hash_layer_ids mismatch (expected {expected_ids}): {contract_summary}"))
							if moe_hash.get("tid2eid_dtype") != "int32":
								failures.append(Failure(42, f"contract summary moe.hash_routing.tid2eid_dtype must be 'int32': {contract_summary}"))
							try:
								expected_shape = [int(summary.get("topology", {}).get("vocab_size")), int(moe.get("n_activated_experts"))]
							except Exception:
								expected_shape = None
							if expected_shape is not None and moe_hash.get("tid2eid_shape") != expected_shape:
								failures.append(Failure(43, f"contract summary moe.hash_routing.tid2eid_shape mismatch (expected {expected_shape}): {contract_summary}"))
							need_exprs = ["hash_enabled_expr", "hash_indices_expr"]
							for k in need_exprs:
								v = moe_hash.get(k)
								if not (isinstance(v, str) and v):
									failures.append(Failure(44, f"contract summary moe.hash_routing missing {k} expression string: {contract_summary}"))
									break

				chk = summary.get("checkpoint_index", {})
				expected_key_sha = sha256_lines(sorted(weight_keys))
				if chk.get("weight_map_num_tensors") != int(len(weight_keys)):
					failures.append(Failure(19, f"contract summary checkpoint_index.weight_map_num_tensors mismatch (expected {len(weight_keys)}): {contract_summary}"))
				if chk.get("weight_map_keys_sha256") != expected_key_sha:
					failures.append(Failure(27, f"contract summary checkpoint_index.weight_map_keys_sha256 mismatch (expected {expected_key_sha}): {contract_summary}"))

				tk = summary.get("tensor_keys", {})
				if tk.get("mtp_embed_present") is not False:
					failures.append(Failure(28, f"contract summary expects no mtp.*.embed.* keys in official checkpoint (tensor_keys.mtp_embed_present=false): {contract_summary}"))
				if tk.get("mtp_head_present") is not False:
					failures.append(Failure(29, f"contract summary expects no mtp.*.head.* keys in official checkpoint (tensor_keys.mtp_head_present=false): {contract_summary}"))
				mtp_add = tk.get("required_mtp_additional_suffixes", None)
				if not isinstance(mtp_add, list) or "e_proj.weight" not in mtp_add or "hc_head_fn" not in mtp_add:
					failures.append(Failure(31, f"contract summary missing MTP tensor-key contract list (tensor_keys.required_mtp_additional_suffixes): {contract_summary}"))

				mtp = summary.get("mtp", {})
				trust = mtp.get("trust_gates", {}) if isinstance(mtp, dict) else {}
				if not isinstance(trust, dict):
					failures.append(Failure(68, f"contract summary mtp.trust_gates must be an object: {contract_summary}"))
				else:
					expected = {
						"artifact_requires_mtp_contract_complete": True,
						"artifact_requires_namespace_prefix": "mtp.{j}.",
						"oracle_requires_include_mtp": True,
						"oracle_requires_mtp_trace": True,
						"oracle_generator_hint": "scripts/model_contract_generate_deepseek_v4_flash_oracle.py --include-mtp",
						"acceptance_requires_prefill_and_decode": True,
						"acceptance_topk_ids_exact": True,
					}
					for k, want in expected.items():
						got = trust.get(k)
						if got != want:
							failures.append(Failure(69, f"contract summary mtp.trust_gates[{k!r}] mismatch (got {got!r} expected {want!r}): {contract_summary}"))
							break

				compat = summary.get("compat", {})
				bt = compat.get("by_transformers_key", {}) if isinstance(compat, dict) else {}
				if not isinstance(bt, dict):
					failures.append(Failure(60, f"contract summary compat.by_transformers_key must be an object: {contract_summary}"))
				else:
					expected = {
						"num_nextn_predict_layers": "mtp.n_mtp_layers",
						"expert_dtype": "quantization.inference_config.expert_dtype",
						"quantization_config.quant_method": "quantization.config_quantization_config.quant_method",
						"quantization_config.fmt": "quantization.config_quantization_config.fmt",
						"quantization_config.activation_scheme": "quantization.config_quantization_config.activation_scheme",
						"quantization_config.scale_fmt": "quantization.config_quantization_config.scale_fmt",
						"quantization_config.weight_block_size": "quantization.config_quantization_config.weight_block_size",
					}
					for k, want in expected.items():
						got = bt.get(k)
						if got != want:
							failures.append(Failure(61, f"contract summary compat.by_transformers_key[{k!r}] mismatch (got {got!r} expected {want!r}): {contract_summary}"))
							break
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

		if any(k.startswith(base + bad) for bad in ("attn.compressor.", "attn.indexer.")):
			failures.append(Failure(32, f"unexpected {base}attn.compressor.* or {base}attn.indexer.* keys for MTP layer (must be sliding-only)"))
		if (base + "ffn.gate.tid2eid") in weight_keys:
			failures.append(Failure(33, f"unexpected {base}ffn.gate.tid2eid in MTP layer (must be score-routed)"))
		for bad in ("embed.weight", "head.weight"):
			if (base + bad) in weight_keys:
				failures.append(Failure(34, f"unexpected {base}{bad} key (MTP shares top-level embed/head)"))

		# Core attention + norms (same as a sliding score-routed trunk layer).
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
			req_mtp(suffix)

		# MoE gate + experts (score-routed).
		for suffix in ("ffn.gate.weight", "ffn.gate.bias"):
			req_mtp(suffix)
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
			req_mtp(suffix)

		# Experts: require 0..n_routed_experts-1 and the expected tensor key count.
		mtp_expert_id_seen: set[int] = set()
		mtp_expert_key_count = 0
		for k in weight_keys:
			if not k.startswith(base + "ffn.experts."):
				continue
			parts = k.split(".")
			if len(parts) < 5:
				continue
			try:
				eid = int(parts[4])
			except ValueError:
				continue
			mtp_expert_id_seen.add(eid)
			mtp_expert_key_count += 1

		if mtp_expert_id_seen != set(range(n_routed_experts)):
			failures.append(Failure(35, f"mtp layer {mtp_id} expert id set mismatch: expected 0..{n_routed_experts-1} got {sorted(mtp_expert_id_seen)[:8]}... ({len(mtp_expert_id_seen)} total)"))
		expected_expert_key_count = n_routed_experts * 6
		if mtp_expert_key_count != expected_expert_key_count:
			failures.append(Failure(36, f"mtp layer {mtp_id} expert tensor key count mismatch: expected {expected_expert_key_count} got {mtp_expert_key_count}"))

		# MTPBlock-specific projections + norms + HC head.
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
