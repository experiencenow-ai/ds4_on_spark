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

def main() -> int:
	failures: list[Failure] = []

	cfg = load_json(FIX / "config.json")
	inf = load_json(FIX / "inference" / "config.json")
	idx = load_json(FIX / "model.safetensors.index.json")
	tok_cfg = load_json(FIX / "tokenizer_config.json")
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
					"DeepSeek_V4.pdf",
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
					try:
						cfg_bos_id = int(cfg.get("bos_token_id"))
						cfg_eos_id = int(cfg.get("eos_token_id"))
					except Exception:
						cfg_bos_id = None
						cfg_eos_id = None
					if cfg_bos_id is not None and tok.get("bos_token_id") != cfg_bos_id:
						failures.append(Failure(80, f"contract summary tokenizer.bos_token_id must match config.json bos_token_id={cfg_bos_id}: {contract_summary}"))
					if cfg_eos_id is not None and tok.get("eos_token_id") != cfg_eos_id:
						failures.append(Failure(81, f"contract summary tokenizer.eos_token_id must match config.json eos_token_id={cfg_eos_id}: {contract_summary}"))
					if tok.get("pad_token_is_eos") is not True:
						failures.append(Failure(82, f"contract summary tokenizer.pad_token_is_eos must be true (per tokenizer_config.json): {contract_summary}"))

					def _tok_cfg_content(x):
						if isinstance(x, dict):
							return x.get("content")
						if isinstance(x, str):
							return x
						return None

					tok_cfg_bos = _tok_cfg_content(tok_cfg.get("bos_token"))
					tok_cfg_eos = _tok_cfg_content(tok_cfg.get("eos_token"))
					tok_cfg_pad = _tok_cfg_content(tok_cfg.get("pad_token"))
					if tok_cfg_bos is not None and tok.get("bos_token") != tok_cfg_bos:
						failures.append(Failure(83, f"contract summary tokenizer.bos_token must match tokenizer_config.json bos_token.content: {contract_summary}"))
					if tok_cfg_eos is not None and tok.get("eos_token") != tok_cfg_eos:
						failures.append(Failure(84, f"contract summary tokenizer.eos_token must match tokenizer_config.json eos_token.content: {contract_summary}"))
					if tok_cfg_pad is not None and tok_cfg_eos is not None and tok_cfg_pad != tok_cfg_eos:
						failures.append(Failure(85, f"tokenizer_config.json pad_token.content must match eos_token.content (pad token is EOS): {contract_summary}"))
					if tok.get("add_bos_token") != bool(tok_cfg.get("add_bos_token", False)):
						failures.append(Failure(86, f"contract summary tokenizer.add_bos_token must match tokenizer_config.json add_bos_token: {contract_summary}"))
					if tok.get("add_eos_token") != bool(tok_cfg.get("add_eos_token", False)):
						failures.append(Failure(87, f"contract summary tokenizer.add_eos_token must match tokenizer_config.json add_eos_token: {contract_summary}"))
					if tok.get("model_max_length") != tok_cfg.get("model_max_length"):
						failures.append(Failure(88, f"contract summary tokenizer.model_max_length must match tokenizer_config.json model_max_length: {contract_summary}"))
					tok_js = tok.get("tokenizer_json_summary")
					if not isinstance(tok_js, dict):
						failures.append(Failure(40, f"contract summary missing tokenizer.tokenizer_json_summary (expected dict): {contract_summary}"))
					else:
						if tok_js.get("model_type") != "BPE":
							failures.append(Failure(41, f"contract summary tokenizer.tokenizer_json_summary.model_type must be BPE: {contract_summary}"))
						if tok_js.get("effective_vocab_size_matches_config") is not True:
							failures.append(Failure(42, f"contract summary tokenizer.tokenizer_json_summary.effective_vocab_size_matches_config must be true: {contract_summary}"))
						base_vocab_size = tok_js.get("base_vocab_size")
						effective_vocab_size = tok_js.get("effective_vocab_size")
						min_ge_base = tok_js.get("added_token_id_min_ge_base_vocab")
						max_ge_base = tok_js.get("added_token_id_max_ge_base_vocab")
						count_ge_base = tok_js.get("added_tokens_count_ge_base_vocab")
						if isinstance(base_vocab_size, int) and isinstance(effective_vocab_size, int):
							if not (isinstance(min_ge_base, int) and min_ge_base >= base_vocab_size):
								failures.append(Failure(46, f"contract summary tokenizer.tokenizer_json_summary.added_token_id_min_ge_base_vocab must be int >= base_vocab_size: {contract_summary}"))
							if not (isinstance(max_ge_base, int) and max_ge_base == (effective_vocab_size - 1)):
								failures.append(Failure(47, f"contract summary tokenizer.tokenizer_json_summary.added_token_id_max_ge_base_vocab must equal effective_vocab_size-1: {contract_summary}"))
							if not (isinstance(count_ge_base, int) and count_ge_base == (effective_vocab_size - base_vocab_size)):
								failures.append(Failure(48, f"contract summary tokenizer.tokenizer_json_summary.added_tokens_count_ge_base_vocab must equal effective_vocab_size-base_vocab_size: {contract_summary}"))
							if isinstance(min_ge_base, int) and min_ge_base != base_vocab_size:
								failures.append(Failure(49, f"contract summary tokenizer.tokenizer_json_summary.added_token_id_min_ge_base_vocab must equal base_vocab_size (contiguous added IDs): {contract_summary}"))
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

				ckpt = summary.get("checkpoint_index", {}) if isinstance(summary, dict) else {}
				if isinstance(ckpt, dict):
					expected_top_level_keys = sorted([k for k in weight_keys if not (k.startswith("layers.") or k.startswith("mtp."))])
					expected_top_level_sha = sha256_lines(expected_top_level_keys)
					if ckpt.get("weight_map_top_level_keys_sha256") != expected_top_level_sha:
						failures.append(Failure(90, f"contract summary checkpoint_index.weight_map_top_level_keys_sha256 mismatch (fixture drift?): {contract_summary}"))
					if ckpt.get("weight_map_top_level_tensor_key_count") != int(len(expected_top_level_keys)):
						failures.append(Failure(91, f"contract summary checkpoint_index.weight_map_top_level_tensor_key_count mismatch (fixture drift?): {contract_summary}"))
				else:
					failures.append(Failure(92, f"contract summary missing checkpoint_index (expected dict): {contract_summary}"))

				group_sizes = summary.get("quantization", {}).get("inference_model_constants", {}).get("kv_act_quant_group_sizes", [])
				if 64 not in list(group_sizes):
					failures.append(Failure(13, f"contract summary missing expected kv_act_quant_group_sizes=64: {contract_summary}"))
				mla = summary.get("mla", {})
				if mla.get("output_derotate_present") is not True:
					failures.append(Failure(15, f"contract summary missing MLA output de-rotation marker (mla.output_derotate_present=true): {contract_summary}"))
				if mla.get("q_extra_rms_norm_present") is not True:
					failures.append(Failure(16, f"contract summary missing MLA Q extra RMS normalization marker (mla.q_extra_rms_norm_present=true): {contract_summary}"))
				cache_obj = summary.get("cache", {})
				try:
					n_layers_cfg = int(cfg.get("num_hidden_layers", 0))
				except Exception:
					n_layers_cfg = 0
				cfg_cr = cfg.get("compress_ratios", None)
				if not isinstance(cfg_cr, list):
					cfg_cr = []
				layer_kinds = cache_obj.get("layer_cache_kind_by_layer_id")
				layer_ratios = cache_obj.get("layer_compress_ratio_by_layer_id")
				want_kinds = summary.get("attention_schedule", {}).get("main_layer_types")
				if not (isinstance(layer_kinds, list) and len(layer_kinds) == n_layers_cfg):
					failures.append(Failure(126, f"contract summary cache.layer_cache_kind_by_layer_id must be a list of length n_layers={n_layers_cfg}: {contract_summary}"))
				elif isinstance(want_kinds, list) and layer_kinds != want_kinds:
					failures.append(Failure(127, f"contract summary cache.layer_cache_kind_by_layer_id must match attention_schedule.main_layer_types: {contract_summary}"))
				want_ratios = [int(r) for r in cfg_cr[:n_layers_cfg]]
				if not (isinstance(layer_ratios, list) and layer_ratios == want_ratios):
					failures.append(Failure(128, f"contract summary cache.layer_compress_ratio_by_layer_id mismatch (expected config.json compress_ratios[:n_layers]): {contract_summary}"))
				try:
					n_mtp_layers_cfg = int(cfg.get("num_nextn_predict_layers", 0))
				except Exception:
					n_mtp_layers_cfg = 0
				if n_mtp_layers_cfg > 0:
					mtp_kinds = cache_obj.get("mtp_cache_kind_by_mtp_layer_id")
					mtp_ratios = cache_obj.get("mtp_compress_ratio_by_mtp_layer_id")
					want_mtp_ratios = [int(r) for r in cfg_cr[n_layers_cfg : n_layers_cfg + n_mtp_layers_cfg]]
					if not (isinstance(mtp_ratios, list) and mtp_ratios == want_mtp_ratios):
						failures.append(Failure(129, f"contract summary cache.mtp_compress_ratio_by_mtp_layer_id mismatch (expected config.json trailing compress_ratios): {contract_summary}"))
					if not (isinstance(mtp_kinds, list) and len(mtp_kinds) == n_mtp_layers_cfg):
						failures.append(Failure(130, f"contract summary cache.mtp_cache_kind_by_mtp_layer_id must be a list of length n_mtp_layers={n_mtp_layers_cfg}: {contract_summary}"))
					elif any(k != "sliding" for k in mtp_kinds):
						failures.append(Failure(131, f"contract summary cache.mtp_cache_kind_by_mtp_layer_id must be all 'sliding' (MTP is sliding-only): {contract_summary}"))
				cache_update = summary.get("cache", {}).get("update_semantics", {})
				ring_expr = cache_update.get("decode_sliding_ring_update_expr")
				if not (isinstance(ring_expr, str) and "start_pos % win" in ring_expr):
					failures.append(Failure(17, f"contract summary missing decode sliding-ring update expression containing 'start_pos % win': {contract_summary}"))
				prefill_wrap_expr = cache_update.get("prefill_sliding_wrap_expr")
				if not (isinstance(prefill_wrap_expr, str) and "cutoff = seqlen % win" in prefill_wrap_expr):
					failures.append(Failure(91, f"contract summary missing prefill sliding-window wrap expression containing 'cutoff = seqlen % win': {contract_summary}"))
				prefill_le_expr = cache_update.get("prefill_sliding_write_seqlen_le_win_expr")
				if not (isinstance(prefill_le_expr, str) and ":seqlen] = kv" in prefill_le_expr):
					failures.append(Failure(92, f"contract summary missing prefill sliding-window write expression for seqlen<=win containing ':seqlen] = kv': {contract_summary}"))
				prefill_gt_expr = cache_update.get("prefill_sliding_write_seqlen_gt_win_expr")
				if not (isinstance(prefill_gt_expr, str) and "kv[:, -win:].split" in prefill_gt_expr and "win - cutoff" in prefill_gt_expr):
					failures.append(Failure(93, f"contract summary missing prefill sliding-window wrap write expression for seqlen>win (expected kv[:, -win:].split([...])): {contract_summary}"))
				seg_view_expr = cache_update.get("compressed_segment_view_expr")
				if not (isinstance(seg_view_expr, str) and "self.compressor.kv_cache = self.kv_cache[:, win:]" in seg_view_expr):
					failures.append(Failure(94, f"contract summary missing compressor compressed-segment view expression 'self.compressor.kv_cache = self.kv_cache[:, win:]': {contract_summary}"))
				topk_offset_expr = cache_update.get("topk_offset_expr")
				if not (isinstance(topk_offset_expr, str) and "offset = kv.size(1) if start_pos == 0 else win" in topk_offset_expr):
					failures.append(Failure(95, f"contract summary missing top-k offset selection expression 'offset = kv.size(1) if start_pos == 0 else win': {contract_summary}"))
				compress_gate_prefill = cache_update.get("compressor_prefill_should_compress_expr")
				if not (isinstance(compress_gate_prefill, str) and "should_compress = seqlen >= ratio" in compress_gate_prefill):
					failures.append(Failure(19, f"contract summary missing compressor prefill gate expression 'should_compress = seqlen >= ratio': {contract_summary}"))
				compress_gate_decode = cache_update.get("compressor_decode_should_compress_expr")
				if not (isinstance(compress_gate_decode, str) and "% self.compress_ratio == 0" in compress_gate_decode):
					failures.append(Failure(20, f"contract summary missing compressor decode gate expression containing '% self.compress_ratio == 0': {contract_summary}"))
				compress_prefill_write = cache_update.get("compressor_prefill_write_expr")
				if not (isinstance(compress_prefill_write, str) and ":seqlen // ratio" in compress_prefill_write):
					failures.append(Failure(21, f"contract summary missing compressor prefill kv_cache write expression containing ':seqlen // ratio': {contract_summary}"))
				compress_decode_write = cache_update.get("compressor_decode_write_expr")
				if not (isinstance(compress_decode_write, str) and "start_pos // ratio" in compress_decode_write):
					failures.append(Failure(22, f"contract summary missing compressor decode kv_cache write expression containing 'start_pos // ratio': {contract_summary}"))
				compress_freqs_prefill = cache_update.get("compressor_freqs_cis_prefill_expr")
				if not (isinstance(compress_freqs_prefill, str) and "[:cutoff:ratio]" in compress_freqs_prefill):
					failures.append(Failure(23, f"contract summary missing compressor freqs_cis prefill expression containing '[:cutoff:ratio]': {contract_summary}"))
				compress_freqs_decode = cache_update.get("compressor_freqs_cis_decode_expr")
				if not (isinstance(compress_freqs_decode, str) and "start_pos + 1 - self.compress_ratio" in compress_freqs_decode):
					failures.append(Failure(24, f"contract summary missing compressor freqs_cis decode expression containing 'start_pos + 1 - self.compress_ratio': {contract_summary}"))
				comp = summary.get("cache", {}).get("compression_semantics", None)
				if not isinstance(comp, dict):
					failures.append(Failure(83, f"contract summary missing cache.compression_semantics object: {contract_summary}"))
				else:
					if comp.get("overlap_rule") != "overlap = (compress_ratio == 4)":
						failures.append(Failure(84, f"contract summary cache.compression_semantics.overlap_rule mismatch: {contract_summary}"))
					if comp.get("indexer_present_rule") != "indexer exists iff compress_ratio == 4 (CSA only)":
						failures.append(Failure(85, f"contract summary cache.compression_semantics.indexer_present_rule mismatch: {contract_summary}"))
					att = comp.get("attention_compressor", {})
					if not isinstance(att, dict) or att.get("rotate") is not False:
						failures.append(Failure(86, f"contract summary cache.compression_semantics.attention_compressor.rotate must be false: {contract_summary}"))
					else:
						rule = att.get("kv_quant_rule")
						if not (isinstance(rule, str) and "group=64" in rule and "rope" in rule.lower()):
							failures.append(Failure(87, f"contract summary cache.compression_semantics.attention_compressor.kv_quant_rule must mention group=64 and rope slice: {contract_summary}"))
					idxp = comp.get("indexer_scoring_path", {})
					if not isinstance(idxp, dict) or idxp.get("compressor_rotate") is not True:
						failures.append(Failure(88, f"contract summary cache.compression_semantics.indexer_scoring_path.compressor_rotate must be true: {contract_summary}"))
					else:
						kv_rule = idxp.get("kv_quant_rule")
						q_rule = idxp.get("q_quant_rule")
						if not (isinstance(kv_rule, str) and "fp4_block_size" in kv_rule):
							failures.append(Failure(89, f"contract summary cache.compression_semantics.indexer_scoring_path.kv_quant_rule must mention fp4_block_size: {contract_summary}"))
						if not (isinstance(q_rule, str) and "fp4_block_size" in q_rule):
							failures.append(Failure(90, f"contract summary cache.compression_semantics.indexer_scoring_path.q_quant_rule must mention fp4_block_size: {contract_summary}"))
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
				expected_prefix = build_weight_key_prefix_fingerprints(sorted(weight_keys))
				got_prefix = chk.get("weight_map_prefix_fingerprints", None)
				if not isinstance(got_prefix, dict):
					failures.append(Failure(91, f"contract summary checkpoint_index.weight_map_prefix_fingerprints must be an object: {contract_summary}"))
				elif got_prefix != expected_prefix:
					failures.append(Failure(92, f"contract summary checkpoint_index.weight_map_prefix_fingerprints mismatch (expected prefixes {sorted(expected_prefix.keys())}): {contract_summary}"))

				tk = summary.get("tensor_keys", {})
				try:
					n_layers = int(cfg.get("num_hidden_layers", 0))
				except Exception:
					n_layers = 0
				try:
					n_routed_experts = int(cfg.get("n_routed_experts", 0))
				except Exception:
					n_routed_experts = 0
				compress_ratios = cfg.get("compress_ratios", None)

				# Enforce that tensor_keys.required_* lists correspond to the official safetensors index.
				if isinstance(compress_ratios, list) and n_layers > 0:
					if len(compress_ratios) < int(n_layers):
						failures.append(Failure(116, f"config.json compress_ratios must include at least num_hidden_layers entries (got {len(compress_ratios)} need {n_layers}): {FIX / 'config.json'}"))
					req_top = tk.get("required_top_level", None)
					req_layer = tk.get("required_layer_suffixes", None)
					req_nonzero = tk.get("required_layer_suffixes_compress_ratio_nonzero", None)
					req_csa = tk.get("required_layer_suffixes_compress_ratio_4", None)
					expert_templates = tk.get("expert_tensor_key_templates", None)
					layer_gate = tk.get("layer_gate", {}) if isinstance(tk, dict) else {}
					hash_ids = layer_gate.get("tid2eid_layer_ids", []) if isinstance(layer_gate, dict) else []
					score_ids = layer_gate.get("gate_bias_layer_ids", []) if isinstance(layer_gate, dict) else []
					hash_gate_suffix = tk.get("hash_gate_tensor_key_suffix", "ffn.gate.tid2eid") if isinstance(tk, dict) else "ffn.gate.tid2eid"
					score_gate_suffix = tk.get("score_gate_tensor_key_suffix", "ffn.gate.bias") if isinstance(tk, dict) else "ffn.gate.bias"

					if not (isinstance(req_top, list) and isinstance(req_layer, list) and isinstance(req_nonzero, list) and isinstance(req_csa, list)):
						failures.append(Failure(112, f"contract summary missing tensor_keys.required_* lists required for tensor-key verification: {contract_summary}"))
					else:
						missing_required: set[str] = set()
						hash_set = {int(i) for i in hash_ids if isinstance(i, int) or (isinstance(i, str) and i.isdigit())}
						score_set = {int(i) for i in score_ids if isinstance(i, int) or (isinstance(i, str) and i.isdigit())}
						if hash_set & score_set:
							failures.append(Failure(117, f"tensor_keys.layer_gate lists must be disjoint (overlap={sorted(hash_set & score_set)[:10]}): {contract_summary}"))
						all_gate_layers = sorted(hash_set | score_set)
						if len(all_gate_layers) != int(n_layers):
							failures.append(Failure(118, f"tensor_keys.layer_gate lists must cover all layers 0..{n_layers-1} (got {len(all_gate_layers)}): {contract_summary}"))

						for suf in req_top:
							need = str(suf)
							if need not in weight_keys:
								missing_required.add(need)

						for i in range(int(n_layers)):
							prefix = f"layers.{i}."
							for suf in req_layer:
								need = prefix + str(suf)
								if need not in weight_keys:
									missing_required.add(need)

							try:
								ratio = int(compress_ratios[i])
							except Exception:
								ratio = 0

							if ratio != 0:
								for suf in req_nonzero:
									need = prefix + str(suf)
									if need not in weight_keys:
										missing_required.add(need)
							if ratio == 4:
								for suf in req_csa:
									need = prefix + str(suf)
									if need not in weight_keys:
										missing_required.add(need)

							hash_gate = prefix + str(hash_gate_suffix)
							score_gate = prefix + str(score_gate_suffix)
							if i in hash_set:
								if hash_gate not in weight_keys:
									missing_required.add(hash_gate)
								if score_gate in weight_keys:
									failures.append(Failure(113, f"unexpected score-gate key present in hash-routed layer {i}: {score_gate}"))
							if i in score_set:
								if score_gate not in weight_keys:
									missing_required.add(score_gate)
								if hash_gate in weight_keys:
									failures.append(Failure(114, f"unexpected hash-gate key present in score-routed layer {i}: {hash_gate}"))

							if isinstance(expert_templates, list) and n_routed_experts > 0:
								for eid in range(int(n_routed_experts)):
									for tmpl in expert_templates:
										try:
											suf = str(tmpl).format(eid=eid)
										except Exception:
											continue
										need = prefix + suf
										if need not in weight_keys:
											missing_required.add(need)

						if missing_required:
							failures.append(Failure(115, f"official checkpoint missing tensor keys implied by tensor_keys.required_* lists (sample={sorted(missing_required)[:20]}): {contract_summary}"))
						else:
							# Enforce machine-readable per-layer suffix + count helpers for DS4 implementers.
							layer_req = tk.get("layer_required_nonexpert_suffixes_by_layer_id", None)
							layer_expected = tk.get("layer_expected_tensor_key_count_by_layer_id", None)
							layer_counts = tk.get("layer_tensor_key_count_by_layer_id", None)
							layer_ok = tk.get("layer_expected_tensor_key_count_by_layer_id_ok", None)
							if not (isinstance(layer_req, dict) and isinstance(layer_expected, dict) and isinstance(layer_counts, dict) and isinstance(layer_ok, dict)):
								failures.append(Failure(121, f"contract summary missing tensor_keys.layer_* per-layer helpers (required_nonexpert_suffixes / expected_counts / counts / ok): {contract_summary}"))
							else:
								try:
									n_hash_layers_cfg = int(cfg.get("num_hash_layers", 0))
								except Exception:
									n_hash_layers_cfg = 0

								for i in range(int(n_layers)):
									key = str(i)
									try:
										ratio = int(compress_ratios[i])
									except Exception:
										ratio = 0
									exp = list(req_layer)
									if ratio != 0:
										exp += list(req_nonzero)
									if ratio == 4:
										exp += list(req_csa)
									exp.append(str(hash_gate_suffix if i < n_hash_layers_cfg else score_gate_suffix))

									got_req = layer_req.get(key)
									if got_req != exp:
										failures.append(Failure(122, f"contract summary tensor_keys.layer_required_nonexpert_suffixes_by_layer_id[{i}] mismatch (got_len={len(got_req) if isinstance(got_req, list) else 'n/a'} expected_len={len(exp)}): {contract_summary}"))
										break

									got_count = layer_counts.get(key)
									want_count = sum(1 for k in weight_keys if k.startswith(f"layers.{i}.")) if isinstance(weight_keys, set) else None
									if got_count != want_count:
										failures.append(Failure(123, f"contract summary tensor_keys.layer_tensor_key_count_by_layer_id[{i}] mismatch (got {got_count!r} expected {want_count}): {contract_summary}"))
										break

									got_expected_total = layer_expected.get(key)
									want_expected_total = int(tk.get("expected_expert_key_count_per_layer", 0)) + len(exp)
									if got_expected_total != want_expected_total:
										failures.append(Failure(124, f"contract summary tensor_keys.layer_expected_tensor_key_count_by_layer_id[{i}] mismatch (got {got_expected_total!r} expected {want_expected_total}): {contract_summary}"))
										break

									if layer_ok.get(key) is not True:
										failures.append(Failure(125, f"contract summary tensor_keys.layer_expected_tensor_key_count_by_layer_id_ok[{i}] must be true: {contract_summary}"))
										break
				if tk.get("mtp_embed_present") is not False:
					failures.append(Failure(28, f"contract summary expects no mtp.*.embed.* keys in official checkpoint (tensor_keys.mtp_embed_present=false): {contract_summary}"))
				if tk.get("mtp_head_present") is not False:
					failures.append(Failure(29, f"contract summary expects no mtp.*.head.* keys in official checkpoint (tensor_keys.mtp_head_present=false): {contract_summary}"))
				mtp_add = tk.get("required_mtp_additional_suffixes", None)
				if not isinstance(mtp_add, list) or "e_proj.weight" not in mtp_add or "hc_head_fn" not in mtp_add:
					failures.append(Failure(31, f"contract summary missing MTP tensor-key contract list (tensor_keys.required_mtp_additional_suffixes): {contract_summary}"))
				else:
					mtp_expected = tk.get("mtp_expected_tensor_key_count_per_layer", None)
					try:
						exp_experts = int(tk.get("expected_expert_key_count_per_layer"))
						exp_layersuf = int(len(tk.get("required_layer_suffixes", [])))
						exp_mtpadd = int(len(mtp_add))
						exp_total = int(exp_experts + exp_layersuf + exp_mtpadd + 1)
					except Exception:
						exp_total = None
					if exp_total is not None and mtp_expected != exp_total:
						failures.append(Failure(106, f"contract summary tensor_keys.mtp_expected_tensor_key_count_per_layer mismatch (got {mtp_expected!r} expected {exp_total}): {contract_summary}"))

					mtp_counts = tk.get("mtp_tensor_key_count_by_layer_id", None)
					mtp_ok = tk.get("mtp_expected_tensor_key_count_by_layer_id_ok", None)
					if not isinstance(mtp_counts, dict) or not isinstance(mtp_ok, dict):
						failures.append(Failure(107, f"contract summary missing tensor_keys mtp per-layer count objects (mtp_tensor_key_count_by_layer_id / mtp_expected_tensor_key_count_by_layer_id_ok): {contract_summary}"))
					else:
						mtp_layer_ids = find_mtp_layer_ids(weight_keys)
						for mtp_id in mtp_layer_ids:
							prefix = f"mtp.{mtp_id}."
							want = sum(1 for k in weight_keys if k.startswith(prefix))
							got = mtp_counts.get(str(mtp_id))
							ok = mtp_ok.get(str(mtp_id))
							if got != want:
								failures.append(Failure(108, f"contract summary tensor_keys.mtp_tensor_key_count_by_layer_id[{mtp_id}] mismatch (got {got!r} expected {want}): {contract_summary}"))
								break
							if ok is not True:
								failures.append(Failure(109, f"contract summary tensor_keys.mtp_expected_tensor_key_count_by_layer_id_ok[{mtp_id}] must be true: {contract_summary}"))
								break

						# Enforce MTP tensor-key semantics for the official checkpoint: no compressor/indexer, no tid2eid, and full key coverage.
						req_layer = tk.get("required_layer_suffixes", None)
						mtp_gate_suffix = tk.get("mtp_score_gate_tensor_key_suffix", tk.get("score_gate_tensor_key_suffix", "ffn.gate.bias"))
						forbidden_suffixes = tk.get("mtp_forbidden_key_suffixes", None)
						expert_templates = tk.get("expert_tensor_key_templates", None)
						if isinstance(req_layer, list) and isinstance(forbidden_suffixes, list) and n_routed_experts > 0:
							missing_mtp: set[str] = set()
							forbidden_mtp: set[str] = set()
							for mtp_id in mtp_layer_ids:
								prefix = f"mtp.{mtp_id}."
								for bad in forbidden_suffixes:
									bad_s = str(bad)
									if bad_s.endswith("."):
										if any(k.startswith(prefix + bad_s) for k in weight_keys):
											forbidden_mtp.add(prefix + bad_s)
									else:
										if (prefix + bad_s) in weight_keys:
											forbidden_mtp.add(prefix + bad_s)

								for suf in req_layer:
									need = prefix + str(suf)
									if need not in weight_keys:
										missing_mtp.add(need)

								need_gate = prefix + str(mtp_gate_suffix)
								if need_gate not in weight_keys:
									missing_mtp.add(need_gate)

								for eid in range(int(n_routed_experts)):
									for tmpl in expert_templates if isinstance(expert_templates, list) else []:
										try:
											suf = str(tmpl).format(eid=eid)
										except Exception:
											continue
										need = prefix + suf
										if need not in weight_keys:
											missing_mtp.add(need)

								for suf in mtp_add:
									need = prefix + str(suf)
									if need not in weight_keys:
										missing_mtp.add(need)

							if forbidden_mtp:
								failures.append(Failure(119, f"official checkpoint contains forbidden MTP tensor keys (sample={sorted(forbidden_mtp)[:20]}): {contract_summary}"))
							if missing_mtp:
								failures.append(Failure(120, f"official checkpoint missing required MTP tensor keys (sample={sorted(missing_mtp)[:20]}): {contract_summary}"))

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

				if isinstance(mtp, dict):
					try:
						want_layers = int(cfg.get("num_nextn_predict_layers", 0))
					except Exception:
						want_layers = 0
					got_layers = mtp.get("n_mtp_layers", None)
					if got_layers != want_layers:
						failures.append(Failure(110, f"contract summary mtp.n_mtp_layers mismatch (got {got_layers!r} expected {want_layers}): {contract_summary}"))
					got_alias = mtp.get("num_nextn_predict_layers", None)
					if got_alias != want_layers:
						failures.append(Failure(111, f"contract summary mtp.num_nextn_predict_layers mismatch (got {got_alias!r} expected {want_layers}): {contract_summary}"))

				mtp_sem = mtp.get("semantics", {}) if isinstance(mtp, dict) else {}
				if not isinstance(mtp_sem, dict):
					failures.append(Failure(70, f"contract summary mtp.semantics must be an object: {contract_summary}"))
				else:
					combine = mtp_sem.get("combine_e_and_h_expr")
					if not (isinstance(combine, str) and "self.e_proj(e).unsqueeze(2)" in combine and "+ self.h_proj(x)" in combine):
						failures.append(Failure(71, f"contract summary mtp.semantics.combine_e_and_h_expr missing or unexpected: {contract_summary}"))
					head = mtp_sem.get("head_logits_expr")
					if not (isinstance(head, str) and head.startswith("logits = self.head(")):
						failures.append(Failure(72, f"contract summary mtp.semantics.head_logits_expr missing or unexpected: {contract_summary}"))

				compat = summary.get("compat", {})
				bt = compat.get("by_transformers_key", {}) if isinstance(compat, dict) else {}
				if not isinstance(bt, dict):
					failures.append(Failure(60, f"contract summary compat.by_transformers_key must be an object: {contract_summary}"))
				else:
					expected = {
						"num_nextn_predict_layers": "mtp.n_mtp_layers",
						"layer_types": "attention_schedule.transformers_main_layer_types",
						"compress_rates": "attention_schedule.transformers_compress_rates",
						"compress_rate_csa": "attention_schedule.transformers_compress_rates.compressed_sparse_attention",
						"compress_rate_hca": "attention_schedule.transformers_compress_rates.heavily_compressed_attention",
						"mlp_layer_types": "moe.transformers_mlp_layer_types",
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

				q = summary.get("quantization", {}) if isinstance(summary, dict) else {}
				q_inf = q.get("inference_config", {}) if isinstance(q, dict) else {}
				if not (isinstance(q_inf, dict) and q_inf.get("scale_dtype") == "fp8"):
					failures.append(Failure(70, f"contract summary quantization.inference_config.scale_dtype must be 'fp8' (derived from inference/model.py ModelArgs default): {contract_summary}"))
				else:
					want = inf.get("dtype")
					if not (isinstance(want, str) and q_inf.get("dtype") == want):
						failures.append(Failure(73, f"contract summary quantization.inference_config.dtype mismatch (expected inference/config.json dtype={want!r}): {contract_summary}"))
					want = inf.get("expert_dtype")
					if not (isinstance(want, str) and q_inf.get("expert_dtype") == want):
						failures.append(Failure(74, f"contract summary quantization.inference_config.expert_dtype mismatch (expected inference/config.json expert_dtype={want!r}): {contract_summary}"))
					want = inf.get("scale_fmt")
					if not (isinstance(want, str) and q_inf.get("scale_fmt") == want):
						failures.append(Failure(75, f"contract summary quantization.inference_config.scale_fmt mismatch (expected inference/config.json scale_fmt={want!r}): {contract_summary}"))
					want = cfg.get("expert_dtype")
					if isinstance(want, str) and q_inf.get("expert_dtype") != want:
						failures.append(Failure(76, f"fixtures/config.json expert_dtype mismatch between config.json and inference/config.json (config.json expert_dtype={want!r}, inference/config.json expert_dtype={q_inf.get('expert_dtype')!r}): {contract_summary}"))

				q_cfg = q.get("config_quantization_config", None) if isinstance(q, dict) else None
				want_cfg = cfg.get("quantization_config", None)
				if want_cfg is not None and q_cfg != want_cfg:
					failures.append(Failure(77, f"contract summary quantization.config_quantization_config mismatch (expected config.json quantization_config): {contract_summary}"))

				oracle = summary.get("oracle", {})
				if not isinstance(oracle, dict):
					failures.append(Failure(90, f"contract summary oracle must be an object: {contract_summary}"))
				else:
					enc_oracle = oracle.get("encoding_oracle", {})
					log_oracle = oracle.get("logits_oracle", {})
					mtp_oracle = oracle.get("mtp", {})
					if not (isinstance(enc_oracle, dict) and enc_oracle.get("required") is True and isinstance(enc_oracle.get("fixtures_glob"), str)):
						failures.append(Failure(91, f"contract summary oracle.encoding_oracle must declare required=true and fixtures_glob: {contract_summary}"))
					if not (isinstance(log_oracle, dict) and log_oracle.get("weights_required") is True and isinstance(log_oracle.get("generator"), str)):
						failures.append(Failure(92, f"contract summary oracle.logits_oracle must declare weights_required=true and generator: {contract_summary}"))
					if not (isinstance(mtp_oracle, dict) and mtp_oracle.get("weights_required") is True and isinstance(mtp_oracle.get("generator_hint"), str)):
						failures.append(Failure(93, f"contract summary oracle.mtp must declare weights_required=true and generator_hint: {contract_summary}"))

				ts = summary.get("tensor_shapes", {})
				if not isinstance(ts, dict):
					failures.append(Failure(94, f"contract summary tensor_shapes must be an object: {contract_summary}"))
				else:
					tl = ts.get("top_level", {})
					if not (isinstance(tl, dict) and tl.get("hc_head_scale") == [1]):
						failures.append(Failure(95, f"contract summary tensor_shapes.top_level.hc_head_scale must be [1]: {contract_summary}"))
					phc = ts.get("per_layer", {}).get("hyper_connections", {})
					if not isinstance(phc, dict):
						failures.append(Failure(96, f"contract summary tensor_shapes.per_layer.hyper_connections must be an object: {contract_summary}"))
					else:
						try:
							hc_mult = int(inf.get("hc_mult"))
							mix_hc = (2 + hc_mult) * hc_mult
						except Exception:
							hc_mult = None
							mix_hc = None
						if mix_hc is not None and phc.get("mix_hc") != mix_hc:
							failures.append(Failure(97, f"contract summary tensor_shapes.per_layer.hyper_connections.mix_hc mismatch (expected {mix_hc}): {contract_summary}"))
						if phc.get("hc_attn_scale") != [3] or phc.get("hc_ffn_scale") != [3]:
							failures.append(Failure(98, f"contract summary tensor_shapes.per_layer.hyper_connections hc_*_scale must be [3]: {contract_summary}"))

					# Quantized linear scale tensors: shapes are part of the execution contract.
					try:
						dim = int(cfg.get("hidden_size"))
						vocab_size = int(cfg.get("vocab_size"))
						n_heads = int(cfg.get("num_attention_heads"))
						head_dim = int(cfg.get("head_dim"))
						q_lora_rank = int(cfg.get("q_lora_rank"))
						o_groups = int(cfg.get("o_groups"))
						o_lora_rank = int(cfg.get("o_lora_rank"))
						moe_inter_dim = int(cfg.get("moe_intermediate_size"))
					except Exception:
						dim = None
						vocab_size = None
						n_heads = None
						head_dim = None
						q_lora_rank = None
						o_groups = None
						o_lora_rank = None
						moe_inter_dim = None

					lt = summary.get("quantization", {}).get("linear_tensor_contract", {}) if isinstance(summary, dict) else {}
					fp8 = lt.get("fp8", {}) if isinstance(lt, dict) else {}
					fp4 = lt.get("fp4", {}) if isinstance(lt, dict) else {}
					block_size = fp8.get("block_size") if isinstance(fp8, dict) else None
					fp4_block_size = fp4.get("fp4_block_size") if isinstance(fp4, dict) else None

					def fp8_scale_shape(out_features: int, in_features: int) -> list[int]:
						return [
							(int(out_features) + int(block_size) - 1) // int(block_size),
							(int(in_features) + int(block_size) - 1) // int(block_size),
						]

					def fp4_scale_shape(out_features: int, in_features: int) -> list[int]:
						return [int(out_features), int(in_features) // int(fp4_block_size)]

					attn = ts.get("per_layer", {}).get("attn", {})
					if isinstance(attn, dict) and isinstance(block_size, int) and dim is not None and q_lora_rank is not None and n_heads is not None and head_dim is not None and o_groups is not None and o_lora_rank is not None:
						want = fp8_scale_shape(q_lora_rank, dim)
						if attn.get("wq_a.scale") != want:
							failures.append(Failure(101, f"contract summary tensor_shapes.per_layer.attn wq_a.scale mismatch (got {attn.get('wq_a.scale')!r} expected {want!r}): {contract_summary}"))
						want = fp8_scale_shape(n_heads * head_dim, q_lora_rank)
						if attn.get("wq_b.scale") != want:
							failures.append(Failure(102, f"contract summary tensor_shapes.per_layer.attn wq_b.scale mismatch (got {attn.get('wq_b.scale')!r} expected {want!r}): {contract_summary}"))
						want = fp8_scale_shape(head_dim, dim)
						if attn.get("wkv.scale") != want:
							failures.append(Failure(103, f"contract summary tensor_shapes.per_layer.attn wkv.scale mismatch (got {attn.get('wkv.scale')!r} expected {want!r}): {contract_summary}"))
						want = fp8_scale_shape(o_groups * o_lora_rank, (n_heads * head_dim) // o_groups)
						if attn.get("wo_a.scale") != want:
							failures.append(Failure(104, f"contract summary tensor_shapes.per_layer.attn wo_a.scale mismatch (got {attn.get('wo_a.scale')!r} expected {want!r}): {contract_summary}"))
						want = fp8_scale_shape(dim, o_groups * o_lora_rank)
						if attn.get("wo_b.scale") != want:
							failures.append(Failure(105, f"contract summary tensor_shapes.per_layer.attn wo_b.scale mismatch (got {attn.get('wo_b.scale')!r} expected {want!r}): {contract_summary}"))

					moe = ts.get("per_layer", {}).get("moe", {})
					if isinstance(moe, dict) and isinstance(fp4_block_size, int) and dim is not None and moe_inter_dim is not None:
						want = fp4_scale_shape(moe_inter_dim, dim)
						if moe.get("experts.{eid}.w1.scale") != want:
							failures.append(Failure(106, f"contract summary tensor_shapes.per_layer.moe experts.w1.scale mismatch (got {moe.get('experts.{eid}.w1.scale')!r} expected {want!r}): {contract_summary}"))
						want = fp4_scale_shape(dim, moe_inter_dim)
						if moe.get("experts.{eid}.w2.scale") != want:
							failures.append(Failure(107, f"contract summary tensor_shapes.per_layer.moe experts.w2.scale mismatch (got {moe.get('experts.{eid}.w2.scale')!r} expected {want!r}): {contract_summary}"))
						want = fp4_scale_shape(moe_inter_dim, dim)
						if moe.get("experts.{eid}.w3.scale") != want:
							failures.append(Failure(108, f"contract summary tensor_shapes.per_layer.moe experts.w3.scale mismatch (got {moe.get('experts.{eid}.w3.scale')!r} expected {want!r}): {contract_summary}"))
						want = fp4_scale_shape(moe_inter_dim, dim)
						if moe.get("shared_experts.w1.scale") != want:
							failures.append(Failure(109, f"contract summary tensor_shapes.per_layer.moe shared_experts.w1.scale mismatch (got {moe.get('shared_experts.w1.scale')!r} expected {want!r}): {contract_summary}"))
						want = fp4_scale_shape(dim, moe_inter_dim)
						if moe.get("shared_experts.w2.scale") != want:
							failures.append(Failure(110, f"contract summary tensor_shapes.per_layer.moe shared_experts.w2.scale mismatch (got {moe.get('shared_experts.w2.scale')!r} expected {want!r}): {contract_summary}"))
						want = fp4_scale_shape(moe_inter_dim, dim)
						if moe.get("shared_experts.w3.scale") != want:
							failures.append(Failure(111, f"contract summary tensor_shapes.per_layer.moe shared_experts.w3.scale mismatch (got {moe.get('shared_experts.w3.scale')!r} expected {want!r}): {contract_summary}"))

					mtp = ts.get("mtp", {})
					if isinstance(mtp, dict) and isinstance(block_size, int) and dim is not None:
						want = fp8_scale_shape(dim, dim)
						if mtp.get("e_proj.scale") != want:
							failures.append(Failure(112, f"contract summary tensor_shapes.mtp e_proj.scale mismatch (got {mtp.get('e_proj.scale')!r} expected {want!r}): {contract_summary}"))
						if mtp.get("h_proj.scale") != want:
							failures.append(Failure(113, f"contract summary tensor_shapes.mtp h_proj.scale mismatch (got {mtp.get('h_proj.scale')!r} expected {want!r}): {contract_summary}"))

				top = summary.get("topology", {})
				if isinstance(top, dict):
					expected_top = {
						"vocab_size": int(cfg.get("vocab_size")),
						"hidden_size": int(cfg.get("hidden_size")),
						"num_hidden_layers": int(cfg.get("num_hidden_layers")),
						"num_attention_heads": int(cfg.get("num_attention_heads")),
						"num_key_value_heads": int(cfg.get("num_key_value_heads")),
						"head_dim": int(cfg.get("head_dim")),
						"rope_head_dim": int(cfg.get("qk_rope_head_dim")),
						"q_lora_rank": int(cfg.get("q_lora_rank")),
						"o_groups": int(cfg.get("o_groups")),
						"o_lora_rank": int(cfg.get("o_lora_rank")),
						"sliding_window": int(cfg.get("sliding_window")),
					}
					for kk, want in expected_top.items():
						got = top.get(kk)
						if got != want:
							failures.append(Failure(99, f"contract summary topology.{kk} mismatch (got {got!r} expected {want!r}): {contract_summary}"))
							break
					want_nope = int(cfg.get("head_dim")) - int(cfg.get("qk_rope_head_dim"))
					if top.get("nope_head_dim") != want_nope:
						failures.append(Failure(100, f"contract summary topology.nope_head_dim mismatch (got {top.get('nope_head_dim')!r} expected {want_nope!r}): {contract_summary}"))
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

	# Contract summary must include a Transformers-compatible per-layer schedule derived from compress_ratios.
	try:
		attn = summary.get("attention_schedule", {}) if isinstance(summary, dict) else {}
		if isinstance(attn, dict):
			tf_types = attn.get("transformers_main_layer_types", None)
			if not isinstance(tf_types, list) or len(tf_types) != n_layers:
				failures.append(Failure(101, f"contract summary attention_schedule.transformers_main_layer_types must be a list of length n_layers={n_layers}: {contract_summary}"))
			else:
				for i, r in enumerate(compress_ratios[:n_layers]):
					r = int(r)
					want = "sliding_attention" if r == 0 else ("compressed_sparse_attention" if r == 4 else "heavily_compressed_attention")
					if tf_types[i] != want:
						failures.append(Failure(102, f"contract summary transformers_main_layer_types[{i}] mismatch (got {tf_types[i]!r} expected {want!r}): {contract_summary}"))
						break

			tf_rates = attn.get("transformers_compress_rates", None)
			want_rates = {"compressed_sparse_attention": 4, "heavily_compressed_attention": 128, "sliding_attention": 0}
			if tf_rates != want_rates:
				failures.append(Failure(103, f"contract summary attention_schedule.transformers_compress_rates mismatch (got {tf_rates!r} expected {want_rates!r}): {contract_summary}"))

			tf_mtp = attn.get("transformers_mtp_layer_types", None)
			if n_mtp_layers > 0:
				if not isinstance(tf_mtp, list) or len(tf_mtp) != n_mtp_layers:
					failures.append(Failure(104, f"contract summary attention_schedule.transformers_mtp_layer_types must be a list of length n_mtp_layers={n_mtp_layers}: {contract_summary}"))
				else:
					for j, r in enumerate(compress_ratios[n_layers : n_layers + n_mtp_layers]):
						r = int(r)
						want = "sliding_attention" if r == 0 else ("compressed_sparse_attention" if r == 4 else "heavily_compressed_attention")
						if tf_mtp[j] != want:
							failures.append(Failure(105, f"contract summary transformers_mtp_layer_types[{j}] mismatch (got {tf_mtp[j]!r} expected {want!r}): {contract_summary}"))
							break

			moe = summary.get("moe", {}) if isinstance(summary, dict) else {}
			if isinstance(moe, dict):
				tf_mlp = moe.get("transformers_mlp_layer_types", None)
				if not isinstance(tf_mlp, list) or len(tf_mlp) != n_layers:
					failures.append(Failure(106, f"contract summary moe.transformers_mlp_layer_types must be a list of length n_layers={n_layers}: {contract_summary}"))
				else:
					for i in range(n_layers):
						want = "hash_moe" if i < n_hash_layers else "moe"
						if tf_mlp[i] != want:
							failures.append(Failure(107, f"contract summary moe.transformers_mlp_layer_types[{i}] mismatch (got {tf_mlp[i]!r} expected {want!r}): {contract_summary}"))
							break
	except Exception:
		# If the contract summary is missing, other checks will flag it earlier.
		pass

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

		# Pinned GGUF metadata-only inspections should have a stable summary fixture for MTP/quant gating.
		pinned_summary = FIX / "pinned_gguf_inspects_summary.json"
		pinned_summary_script = ROOT / "scripts" / "model_contract_summarize_v4flash_pinned_gguf_inspects.py"
		if pinned_summary.exists():
			r = subprocess.run([sys.executable, str(pinned_summary_script), "--check"], cwd=str(ROOT))
			if r.returncode != 0:
				failures.append(Failure(18, f"pinned GGUF inspect summary fixture is stale: {pinned_summary} (re-run scripts/model_contract_refresh_v4flash_gguf_inspects.sh)"))

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
