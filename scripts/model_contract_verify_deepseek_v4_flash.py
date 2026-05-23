#!/usr/bin/env python3

import ast
import json
import re
import subprocess
import sys
from dataclasses import dataclass
from hashlib import sha256
from pathlib import Path

try:
	from scripts._lib.source_probe import sha256_file
except ImportError:
	from _lib.source_probe import sha256_file


ROOT = Path(__file__).resolve().parents[1]
FIX = ROOT / "fixtures" / "model_contract" / "deepseek_v4_flash"
MTP_SIDECAR_PROBE_PY = ROOT / "scripts" / "model_contract_probe_mtp_sidecar.py"
MTP_SIDECAR_REFERENCE_JSON = ROOT / "docs" / "mtp-sidecar-probe-antirez-3274cdc-payload64.json"


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

def repo_relpath(path: Path) -> str:
	try:
		return path.relative_to(ROOT).as_posix()
	except ValueError:
		return str(path)

def parse_tokenizer_added_token_ids(tokenizer_json: Path):
	if not tokenizer_json.exists():
		return None
	try:
		tok = load_json(tokenizer_json)
	except Exception:
		return None
	added_tokens = tok.get("added_tokens") if isinstance(tok, dict) else None
	if not isinstance(added_tokens, list):
		return None
	out: dict[str, int] = {}
	for t in added_tokens:
		if not isinstance(t, dict):
			continue
		content = t.get("content", None)
		tid = t.get("id", None)
		if not isinstance(content, str) or not isinstance(tid, int):
			continue
		out[content] = int(tid)
	return out


def build_weight_key_prefix_fingerprints(weight_keys: list[str], sample_n: int = 5) -> dict:
	prefix_to_keys: dict[str, list[str]] = {}
	for k in weight_keys:
		prefix = k.split(".", 1)[0]
		prefix_to_keys.setdefault(prefix, []).append(k)

	out: dict[str, dict] = {}
	for prefix in sorted(prefix_to_keys.keys()):
		keys = sorted(prefix_to_keys[prefix])
		first_sample = None
		last_sample = None
		try:
			n = int(sample_n)
		except Exception:
			n = 0
		if n > 0 and len(keys) > 0:
			first_sample = list(keys[:n])
			last_sample = list(keys[-n:])
		out[prefix] = {
			"count": int(len(keys)),
			"keys_sha256": sha256_lines(keys),
			"first_keys_sample": first_sample,
			"last_keys_sample": last_sample,
		}
	return out



def parse_ds4_mtp_sidecar_expected_tensor_names(probe_py: Path):
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


def payload_samples_fingerprint_lines(reference_doc: dict) -> list[str]:
	samples = reference_doc.get("payload_samples", None) if isinstance(reference_doc, dict) else None
	lines: list[str] = []
	if not isinstance(samples, dict):
		return lines
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
	return lines

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
				cfg_summary = summary.get("config_summary", None) if isinstance(summary, dict) else None
				if not isinstance(cfg_summary, dict):
					failures.append(Failure(30, f"contract summary missing config_summary (expected object): {contract_summary}"))
				else:
					want_cfg_summary = {
						"attention_bias": bool(cfg.get("attention_bias", False)),
						"attention_dropout": float(cfg.get("attention_dropout", 0.0)),
						"hidden_act": str(cfg.get("hidden_act", "")),
						"initializer_range": float(cfg.get("initializer_range", 0.0)),
						"max_position_embeddings": int(cfg.get("max_position_embeddings", 0)),
						"rms_norm_eps": float(cfg.get("rms_norm_eps", 0.0)),
						"tie_word_embeddings": bool(cfg.get("tie_word_embeddings", False)),
						"torch_dtype": str(cfg.get("torch_dtype", "")),
						"transformers_version": str(cfg.get("transformers_version", "")),
						"use_cache": bool(cfg.get("use_cache", True)),
					}
					if cfg_summary != want_cfg_summary:
						failures.append(Failure(31, f"contract summary config_summary mismatch (expected pinned fixtures/config.json semantics): {contract_summary}"))

					up = summary.get("upstream", {}) if isinstance(summary, dict) else {}
					fixture_sha = up.get("fixtures_sha256", {}) if isinstance(up, dict) else {}
					if not isinstance(fixture_sha, dict):
						fixture_sha = {}

					expected_sha_keys = [
						"DeepSeek_V4.pdf",
						"checkpoint_keys.txt",
						"encoding/tests/test_input_1.json",
						"encoding/tests/test_output_1.txt",
						"encoding/tests/test_input_4.json",
						"encoding/tests/test_output_4.txt",
						"mtp_checkpoint_keys.txt",
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
					encoding_token_ids = tok.get("encoding_token_ids")
					added_ids = parse_tokenizer_added_token_ids(FIX / "tokenizer.json")
					if not isinstance(added_ids, dict) or not added_ids:
						failures.append(Failure(89, f"fixtures tokenizer.json must include added_tokens with stable ids: {FIX / 'tokenizer.json'}"))
					elif not isinstance(encoding_token_ids, dict):
						failures.append(Failure(93, f"contract summary tokenizer.encoding_token_ids missing or invalid (expected dict): {contract_summary}"))
					else:
						want_ref = f"{repo_relpath(FIX / 'tokenizer.json')}:added_tokens"
						if encoding_token_ids.get("reference_source") != want_ref:
							failures.append(Failure(94, f"contract summary tokenizer.encoding_token_ids.reference_source mismatch (expected {want_ref!r}): {contract_summary}"))

						def _want_id(token: object):
							if not isinstance(token, str):
								return None
							return added_ids.get(token)

						for k in (
							"bos_token",
							"eos_token",
							"user_sp_token",
							"assistant_sp_token",
							"latest_reminder_sp_token",
							"thinking_start_token",
							"thinking_end_token",
							"dsml_token",
						):
							want_id = _want_id(enc.get(k))
							if not isinstance(want_id, int):
								failures.append(Failure(95, f"fixtures tokenizer.json missing expected token {k}={enc.get(k)!r}: {FIX / 'tokenizer.json'}"))
								break
							if encoding_token_ids.get(k) != int(want_id):
								failures.append(Failure(96, f"contract summary tokenizer.encoding_token_ids.{k} mismatch (expected {int(want_id)}): {contract_summary}"))
								break
						got_task = encoding_token_ids.get("ds_task_sp_tokens")
						if isinstance(task_tokens, dict):
							want_task: dict[str, int] = {}
							for name in sorted(task_tokens.keys()):
								tok_val = task_tokens.get(name)
								tid = _want_id(tok_val)
								if isinstance(tid, int):
									want_task[str(name)] = int(tid)
							if not isinstance(got_task, dict):
								failures.append(Failure(97, f"contract summary tokenizer.encoding_token_ids.ds_task_sp_tokens missing or invalid (expected dict): {contract_summary}"))
							else:
								if got_task != want_task:
									failures.append(Failure(98, f"contract summary tokenizer.encoding_token_ids.ds_task_sp_tokens mismatch (expected {want_task}): {contract_summary}"))
				if upstream_commit and up.get("x_repo_commit") != upstream_commit:
					failures.append(Failure(36, f"contract summary upstream.x_repo_commit must match fixtures upstream_commit.txt ({upstream_commit}): {contract_summary}"))
				if upstream_commit:
					want_pinned = upstream_commit
					got_rev = up.get("hf_revision")
					got_pinned = up.get("hf_revision_pinned")
					got_requested = up.get("hf_revision_requested")
					if got_requested not in (None, "main"):
						failures.append(Failure(400, f"contract summary upstream.hf_revision_requested must be 'main' (or null), got {got_requested!r}: {contract_summary}"))
					if got_pinned != want_pinned:
						failures.append(Failure(401, f"contract summary upstream.hf_revision_pinned must match upstream_commit.txt ({want_pinned}), got {got_pinned!r}: {contract_summary}"))
					if got_rev != want_pinned:
						failures.append(Failure(402, f"contract summary upstream.hf_revision must be pinned to upstream_commit.txt ({want_pinned}), got {got_rev!r}: {contract_summary}"))

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
				mla_src = mla.get("source_helpers", None) if isinstance(mla, dict) else None
				if not isinstance(mla_src, dict):
					failures.append(Failure(177, f"contract summary mla.source_helpers missing or invalid (expected dict): {contract_summary}"))
				else:
					ref = mla_src.get("reference_source", None)
					if not (isinstance(ref, str) and ref):
						failures.append(Failure(178, f"contract summary mla.source_helpers.reference_source missing or invalid: {contract_summary}"))
					for name, markers, mismatch_id, marker_id in [
						(
							"precompute_freqs_cis",
							["torch.polar", "original_seq_len > 0", "freqs = freqs / factor"],
							181,
							182,
						),
						(
							"apply_rotary_emb",
							["torch.view_as_complex", "freqs_cis.conj", "torch.view_as_real", "y.copy_"],
							184,
							185,
						),
					]:
						obj = mla_src.get(name, None)
						if not isinstance(obj, dict):
							failures.append(Failure(179, f"contract summary mla.source_helpers.{name} missing or invalid (expected dict): {contract_summary}"))
							continue
						lines = obj.get("source_lines", None)
						if not (isinstance(lines, list) and lines and all(isinstance(x, str) for x in lines)):
							failures.append(Failure(180, f"contract summary mla.source_helpers.{name}.source_lines missing or invalid: {contract_summary}"))
							continue
						want_sha = sha256_lines(lines)
						if obj.get("source_lines_sha256") != want_sha:
							failures.append(Failure(mismatch_id, f"contract summary mla.source_helpers.{name}.source_lines_sha256 mismatch: {contract_summary}"))
						joined = "\n".join(lines)
						if any(m not in joined for m in markers):
							failures.append(Failure(marker_id, f"contract summary mla.source_helpers.{name} source missing required markers: {contract_summary}"))
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
				mtp_sidecar = summary.get("mtp_sidecar", {}) if isinstance(summary, dict) else {}
				if not isinstance(mtp_sidecar, dict):
					failures.append(Failure(140, f"contract summary missing mtp_sidecar (expected dict): {contract_summary}"))
				else:
					want_arch = "deepseek4_mtp_support"
					if mtp_sidecar.get("general_architecture") != want_arch:
						failures.append(Failure(141, f"contract summary mtp_sidecar.general_architecture must be {want_arch!r}: {contract_summary}"))
					want_names = parse_ds4_mtp_sidecar_expected_tensor_names(MTP_SIDECAR_PROBE_PY)
					got_names = mtp_sidecar.get("expected_tensor_names", None)
					if want_names is None:
						failures.append(Failure(142, f"unable to parse expected_names from {MTP_SIDECAR_PROBE_PY}"))
					elif got_names != want_names:
						failures.append(Failure(143, f"contract summary mtp_sidecar.expected_tensor_names mismatch vs {MTP_SIDECAR_PROBE_PY}: {contract_summary}"))
					else:
						if mtp_sidecar.get("expected_tensor_count") != int(len(want_names)):
							failures.append(Failure(144, f"contract summary mtp_sidecar.expected_tensor_count mismatch (expected {len(want_names)}): {contract_summary}"))
						if mtp_sidecar.get("expected_tensor_names_sha256") != sha256_lines(want_names):
							failures.append(Failure(145, f"contract summary mtp_sidecar.expected_tensor_names_sha256 mismatch: {contract_summary}"))

					ref = mtp_sidecar.get("reference_payload_samples", {})
					if not isinstance(ref, dict):
						failures.append(Failure(146, f"contract summary mtp_sidecar.reference_payload_samples must be a dict: {contract_summary}"))
					else:
						want_ref_json = repo_relpath(MTP_SIDECAR_REFERENCE_JSON)
						got_ref_json = ref.get("reference_json")
						if got_ref_json != want_ref_json:
							failures.append(Failure(151, f"contract summary mtp_sidecar.reference_payload_samples.reference_json must be repo-relative {want_ref_json!r} (got {got_ref_json!r}): {contract_summary}"))
						if isinstance(got_ref_json, str) and got_ref_json.startswith("/"):
							failures.append(Failure(152, f"contract summary mtp_sidecar.reference_payload_samples.reference_json must not be absolute: {contract_summary}"))
						if ref.get("reference_sha256") != sha256_file(MTP_SIDECAR_REFERENCE_JSON):
							failures.append(Failure(147, f"contract summary mtp_sidecar.reference_payload_samples.reference_sha256 mismatch: {contract_summary}"))
						ref_doc = load_json(MTP_SIDECAR_REFERENCE_JSON)
						ref_lines = payload_samples_fingerprint_lines(ref_doc)
						if ref.get("payload_sample_bytes") != ref_doc.get("payload_sample_bytes", None):
							failures.append(Failure(148, f"contract summary mtp_sidecar.reference_payload_samples.payload_sample_bytes mismatch vs {MTP_SIDECAR_REFERENCE_JSON}: {contract_summary}"))
						if ref.get("payload_samples_count") != int(len(ref_lines)):
							failures.append(Failure(149, f"contract summary mtp_sidecar.reference_payload_samples.payload_samples_count mismatch (expected {len(ref_lines)}): {contract_summary}"))
						if ref.get("payload_samples_sha256") != sha256_lines(ref_lines):
							failures.append(Failure(150, f"contract summary mtp_sidecar.reference_payload_samples.payload_samples_sha256 mismatch: {contract_summary}"))

				mtp_keys_path = FIX / "mtp_checkpoint_keys.txt"
				if not mtp_keys_path.exists():
					failures.append(Failure(153, f"missing derived fixture listing official mtp.* tensor keys: {mtp_keys_path}"))
				else:
					want_mtp_keys = sorted([k for k in weight_keys if k.startswith("mtp.")])
					got_mtp_keys = mtp_keys_path.read_text(encoding="utf-8").splitlines()
					if got_mtp_keys != want_mtp_keys:
						failures.append(Failure(154, f"mtp checkpoint key fixture is stale vs model.safetensors.index.json (expected_len={len(want_mtp_keys)} got_len={len(got_mtp_keys)}): {mtp_keys_path}"))
					else:
						want_sha = sha256_lines(want_mtp_keys)
						got_sha = sha256_file(mtp_keys_path)
						if got_sha != want_sha:
							failures.append(Failure(155, f"mtp checkpoint key fixture sha256 mismatch (got={got_sha} expected={want_sha}): {mtp_keys_path}"))
						mtp_obj = summary.get("mtp", {}) if isinstance(summary, dict) else {}
						ck = (mtp_obj.get("checkpoint_key_fingerprint", {}) if isinstance(mtp_obj, dict) else {}) if isinstance(mtp_obj, dict) else {}
						expected_mtp_sha = ck.get("keys_sha256", None) if isinstance(ck, dict) else None
						if expected_mtp_sha is not None and expected_mtp_sha != want_sha:
							failures.append(Failure(156, f"contract summary mtp.checkpoint_key_fingerprint.keys_sha256 mismatch vs fixtures (got={expected_mtp_sha} expected={want_sha}): {contract_summary}"))

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
				topk_helpers = cache_obj.get("topk_index_helpers", None)
				if not isinstance(topk_helpers, dict):
					failures.append(Failure(132, f"contract summary cache.topk_index_helpers must be an object: {contract_summary}"))
				else:
					if topk_helpers.get("sentinel_index") != -1:
						failures.append(Failure(133, f"contract summary cache.topk_index_helpers.sentinel_index must be -1: {contract_summary}"))
					ref = topk_helpers.get("reference_source")
					if not (isinstance(ref, str) and ref):
						failures.append(Failure(134, f"contract summary cache.topk_index_helpers.reference_source must be a non-empty string: {contract_summary}"))
					win_obj = topk_helpers.get("get_window_topk_idxs", None)
					win_lines = win_obj.get("source_lines") if isinstance(win_obj, dict) else None
					if not (isinstance(win_lines, list) and all(isinstance(x, str) for x in win_lines) and win_lines):
						failures.append(Failure(135, f"contract summary cache.topk_index_helpers.get_window_topk_idxs.source_lines missing or invalid: {contract_summary}"))
					else:
						if win_obj.get("source_lines_sha256") != sha256_lines(win_lines):
							failures.append(Failure(136, f"contract summary cache.topk_index_helpers.get_window_topk_idxs.source_lines_sha256 mismatch: {contract_summary}"))
						src = "\n".join(win_lines)
						need = [
							"def get_window_topk_idxs",
							"start_pos %= window_size",
							"value=-1",
							"torch.where(matrix > base, -1, matrix)",
							"return matrix.unsqueeze(0).expand(bsz, -1, -1)",
						]
						if any(n not in src for n in need):
							failures.append(Failure(137, f"contract summary cache.topk_index_helpers.get_window_topk_idxs source missing required markers: {contract_summary}"))
					comp_obj = topk_helpers.get("get_compress_topk_idxs", None)
					comp_lines = comp_obj.get("source_lines") if isinstance(comp_obj, dict) else None
					if not (isinstance(comp_lines, list) and all(isinstance(x, str) for x in comp_lines) and comp_lines):
						failures.append(Failure(138, f"contract summary cache.topk_index_helpers.get_compress_topk_idxs.source_lines missing or invalid: {contract_summary}"))
					else:
						if comp_obj.get("source_lines_sha256") != sha256_lines(comp_lines):
							failures.append(Failure(139, f"contract summary cache.topk_index_helpers.get_compress_topk_idxs.source_lines_sha256 mismatch: {contract_summary}"))
						src = "\n".join(comp_lines)
						need = [
							"def get_compress_topk_idxs",
							"matrix = torch.arange(0, (start_pos + 1) // ratio) + offset",
							"mask = matrix >= torch.arange(1, seqlen + 1).unsqueeze(1) // ratio",
							"torch.where(mask, -1, matrix + offset)",
							"return matrix.unsqueeze(0).expand(bsz, -1, -1)",
						]
						if any(n not in src for n in need):
							failures.append(Failure(140, f"contract summary cache.topk_index_helpers.get_compress_topk_idxs source missing required markers: {contract_summary}"))

				if cache_obj.get("topk_mask_value") != -1:
					failures.append(Failure(5200, f"contract summary cache.topk_mask_value must be -1: {contract_summary}"))
				sparse_rule = cache_obj.get("sparse_attn_mask_rule", None)
				if not (isinstance(sparse_rule, str) and "idx == -1" in sparse_rule and "score=-inf" in sparse_rule and "kv=0" in sparse_rule):
					failures.append(Failure(5201, f"contract summary cache.sparse_attn_mask_rule must be a string describing idx==-1 masking (score=-inf, kv=0): {contract_summary}"))
				sparse_mask = cache_obj.get("sparse_attn_mask", None)
				if not isinstance(sparse_mask, dict):
					failures.append(Failure(5202, f"contract summary cache.sparse_attn_mask must be an object: {contract_summary}"))
				else:
					ref = sparse_mask.get("reference_source")
					if not (isinstance(ref, str) and ref):
						failures.append(Failure(5203, f"contract summary cache.sparse_attn_mask.reference_source must be a non-empty string: {contract_summary}"))
					elif ref.startswith("/"):
						failures.append(Failure(5204, f"contract summary cache.sparse_attn_mask.reference_source must not be absolute: {contract_summary}"))
					if sparse_mask.get("sentinel_index") != -1:
						failures.append(Failure(5205, f"contract summary cache.sparse_attn_mask.sentinel_index must be -1: {contract_summary}"))
					if sparse_mask.get("masked_kv_fill_value") != 0:
						failures.append(Failure(5206, f"contract summary cache.sparse_attn_mask.masked_kv_fill_value must be 0: {contract_summary}"))
					if sparse_mask.get("masked_score_fill_value") != "-inf":
						failures.append(Failure(5207, f"contract summary cache.sparse_attn_mask.masked_score_fill_value must be '-inf': {contract_summary}"))

				cache_sem = cache_obj.get("semantics", None)
				if not isinstance(cache_sem, dict):
					failures.append(Failure(165, f"contract summary cache.semantics must be an object: {contract_summary}"))
				else:
					ref = cache_sem.get("reference_source")
					if not (isinstance(ref, str) and ref):
						failures.append(Failure(177, f"contract summary cache.semantics.reference_source must be a non-empty string: {contract_summary}"))
					kv_layout = cache_sem.get("kv_layout")
					if not (isinstance(kv_layout, str) and kv_layout):
						failures.append(Failure(178, f"contract summary cache.semantics.kv_layout must be a non-empty string: {contract_summary}"))
					topk_rule = cache_sem.get("sparse_topk_rule")
					if not (isinstance(topk_rule, str) and topk_rule):
						failures.append(Failure(179, f"contract summary cache.semantics.sparse_topk_rule must be a non-empty string: {contract_summary}"))
					sliding_summary = cache_sem.get("sliding_summary")
					if not (isinstance(sliding_summary, str) and sliding_summary):
						failures.append(Failure(180, f"contract summary cache.semantics.sliding_summary must be a non-empty string: {contract_summary}"))
					csa_summary = cache_sem.get("csa_summary")
					if not (isinstance(csa_summary, str) and csa_summary):
						failures.append(Failure(181, f"contract summary cache.semantics.csa_summary must be a non-empty string: {contract_summary}"))
					hca_summary = cache_sem.get("hca_summary")
					if not (isinstance(hca_summary, str) and hca_summary):
						failures.append(Failure(182, f"contract summary cache.semantics.hca_summary must be a non-empty string: {contract_summary}"))
					helpers = cache_sem.get("source_helpers", None)
					if not isinstance(helpers, dict):
						failures.append(Failure(166, f"contract summary cache.semantics.source_helpers must be an object: {contract_summary}"))
					else:
						ref = helpers.get("reference_source")
						if not (isinstance(ref, str) and ref):
							failures.append(Failure(167, f"contract summary cache.semantics.source_helpers.reference_source must be a non-empty string: {contract_summary}"))

						comp_obj = helpers.get("compressor_forward", None)
						comp_lines = comp_obj.get("source_lines") if isinstance(comp_obj, dict) else None
						if not (isinstance(comp_lines, list) and all(isinstance(x, str) for x in comp_lines) and comp_lines):
							failures.append(Failure(168, f"contract summary cache.semantics.source_helpers.compressor_forward.source_lines missing or invalid: {contract_summary}"))
						else:
							if comp_obj.get("source_lines_sha256") != sha256_lines(comp_lines):
								failures.append(Failure(169, f"contract summary cache.semantics.source_helpers.compressor_forward.source_lines_sha256 mismatch: {contract_summary}"))
							src = "\n".join(comp_lines)
							need = [
								"def forward(",
								"if start_pos == 0:",
								"should_compress = seqlen >= ratio",
								"should_compress = (start_pos + 1) % self.compress_ratio == 0",
								"self.kv_cache[:bsz, :seqlen // ratio] = kv",
								"self.kv_cache[:bsz, start_pos // ratio] = kv.squeeze(1)",
								"return kv",
							]
							if any(n not in src for n in need):
								failures.append(Failure(170, f"contract summary cache.semantics.source_helpers.compressor_forward source missing required markers: {contract_summary}"))

						idx_obj = helpers.get("indexer_forward", None)
						idx_lines = idx_obj.get("source_lines") if isinstance(idx_obj, dict) else None
						if not (isinstance(idx_lines, list) and all(isinstance(x, str) for x in idx_lines) and idx_lines):
							failures.append(Failure(171, f"contract summary cache.semantics.source_helpers.indexer_forward.source_lines missing or invalid: {contract_summary}"))
						else:
							if idx_obj.get("source_lines_sha256") != sha256_lines(idx_lines):
								failures.append(Failure(172, f"contract summary cache.semantics.source_helpers.indexer_forward.source_lines_sha256 mismatch: {contract_summary}"))
							src = "\n".join(idx_lines)
							need = [
								"def forward(",
								"q = rotate_activation(q)",
								"fp4_act_quant(q, fp4_block_size, True)",
								"self.compressor(x, start_pos)",
								"index_score = torch.einsum(",
								"if world_size > 1:",
								"dist.all_reduce(index_score)",
								"topk_idxs = index_score.topk",
								"return topk_idxs",
							]
							if any(n not in src for n in need):
								failures.append(Failure(173, f"contract summary cache.semantics.source_helpers.indexer_forward source missing required markers: {contract_summary}"))

						att_obj = helpers.get("attention_forward", None)
						att_lines = att_obj.get("source_lines") if isinstance(att_obj, dict) else None
						if not (isinstance(att_lines, list) and all(isinstance(x, str) for x in att_lines) and att_lines):
							failures.append(Failure(174, f"contract summary cache.semantics.source_helpers.attention_forward.source_lines missing or invalid: {contract_summary}"))
						else:
							if att_obj.get("source_lines_sha256") != sha256_lines(att_lines):
								failures.append(Failure(175, f"contract summary cache.semantics.source_helpers.attention_forward.source_lines_sha256 mismatch: {contract_summary}"))
							src = "\n".join(att_lines)
							need = [
								"def forward(",
								"topk_idxs = get_window_topk_idxs",
								"topk_idxs = torch.cat([topk_idxs, compress_topk_idxs], dim=-1)",
								"self.kv_cache[:bsz, start_pos % win] = kv.squeeze(1)",
								"o = sparse_attn(",
								"return x",
							]
							if any(n not in src for n in need):
								failures.append(Failure(176, f"contract summary cache.semantics.source_helpers.attention_forward source missing required markers: {contract_summary}"))
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
				helpers = moe_sem.get("source_helpers", None)
				if not isinstance(helpers, dict):
					failures.append(Failure(151, f"contract summary moe.semantics.source_helpers must be an object: {contract_summary}"))
				else:
					ref = helpers.get("reference_source")
					if not (isinstance(ref, str) and ref):
						failures.append(Failure(152, f"contract summary moe.semantics.source_helpers.reference_source must be a non-empty string: {contract_summary}"))
					gate_obj = helpers.get("gate_forward", None)
					gate_lines = gate_obj.get("source_lines") if isinstance(gate_obj, dict) else None
					if not (isinstance(gate_lines, list) and all(isinstance(x, str) for x in gate_lines) and gate_lines):
						failures.append(Failure(153, f"contract summary moe.semantics.source_helpers.gate_forward.source_lines missing or invalid: {contract_summary}"))
					else:
						if gate_obj.get("source_lines_sha256") != sha256_lines(gate_lines):
							failures.append(Failure(154, f"contract summary moe.semantics.source_helpers.gate_forward.source_lines_sha256 mismatch: {contract_summary}"))
						src = "\n".join(gate_lines)
						need = [
							"def forward(",
							"original_scores = scores",
							"Bias shifts scores for expert selection",
							"indices = self.tid2eid[input_ids]",
							"indices = scores.topk",
							"weights = original_scores.gather",
							"weights /= weights.sum",
							"weights *= self.route_scale",
							"return weights, indices",
						]
						if any(n not in src for n in need):
							failures.append(Failure(155, f"contract summary moe.semantics.source_helpers.gate_forward source missing required markers: {contract_summary}"))
					moe_obj = helpers.get("moe_forward", None)
					moe_lines = moe_obj.get("source_lines") if isinstance(moe_obj, dict) else None
					if not (isinstance(moe_lines, list) and all(isinstance(x, str) for x in moe_lines) and moe_lines):
						failures.append(Failure(156, f"contract summary moe.semantics.source_helpers.moe_forward.source_lines missing or invalid: {contract_summary}"))
					else:
						if moe_obj.get("source_lines_sha256") != sha256_lines(moe_lines):
							failures.append(Failure(157, f"contract summary moe.semantics.source_helpers.moe_forward.source_lines_sha256 mismatch: {contract_summary}"))
						src = "\n".join(moe_lines)
						need = [
							"def forward(",
							"x = x.view(-1, self.dim)",
							"weights, indices = self.gate(",
							"counts = torch.bincount",
							"for i in range(self.experts_start_idx, self.experts_end_idx):",
							"idx, top = torch.where(indices == i)",
							"if world_size > 1:",
							"dist.all_reduce",
							"y += self.shared_experts(x)",
							"return y.type_as(x).view(shape)",
						]
						if any(n not in src for n in need):
							failures.append(Failure(158, f"contract summary moe.semantics.source_helpers.moe_forward source missing required markers: {contract_summary}"))
				moe = summary.get("moe", {})
				if isinstance(moe, dict):
					swiglu = moe.get("swiglu_limit", None)
					try:
						want_inf = float(inf.get("swiglu_limit"))
					except Exception:
						want_inf = None
					try:
						want_cfg = float(cfg.get("swiglu_limit"))
					except Exception:
						want_cfg = None
					if not isinstance(swiglu, (int, float)):
						failures.append(Failure(140, f"contract summary moe.swiglu_limit must be a number: {contract_summary}"))
					else:
						if want_inf is not None and float(swiglu) != float(want_inf):
							failures.append(Failure(141, f"contract summary moe.swiglu_limit mismatch vs inference/config.json swiglu_limit={want_inf}: {contract_summary}"))
						if want_cfg is not None and float(swiglu) != float(want_cfg):
							failures.append(Failure(142, f"contract summary moe.swiglu_limit mismatch vs config.json swiglu_limit={want_cfg}: {contract_summary}"))
					need_clamp = {
						"swiglu_clamp_enabled_expr": "swiglu_limit > 0",
						"swiglu_clamp_up_expr": "torch.clamp(up",
						"swiglu_clamp_gate_expr": "torch.clamp(gate",
					}
					for k, needle in need_clamp.items():
						v = moe_sem.get(k)
						if not (isinstance(v, str) and needle in v):
							failures.append(Failure(143, f"contract summary missing expected moe.semantics.{k} containing {needle!r}: {contract_summary}"))
							break
					up_expr = moe_sem.get("swiglu_clamp_up_expr")
					if isinstance(up_expr, str):
						if "min=-self.swiglu_limit" not in up_expr or "max=self.swiglu_limit" not in up_expr:
							failures.append(Failure(144, f"contract summary moe.semantics.swiglu_clamp_up_expr must clamp to [-swiglu_limit,+swiglu_limit]: {contract_summary}"))
				moe_hash = moe.get("hash_routing", {}) if isinstance(moe, dict) else {}
				if isinstance(moe, dict):
					want_topk_method = cfg.get("topk_method", None)
					got_topk_method = moe.get("topk_method", None)
					if want_topk_method is not None and got_topk_method != want_topk_method:
						failures.append(Failure(145, f"contract summary moe.topk_method mismatch vs config.json topk_method={want_topk_method!r}: {contract_summary}"))

					want_norm_topk_prob = cfg.get("norm_topk_prob", None)
					got_norm_topk_prob = moe.get("norm_topk_prob", None)
					if want_norm_topk_prob is not None and got_norm_topk_prob != want_norm_topk_prob:
						failures.append(Failure(146, f"contract summary moe.norm_topk_prob mismatch vs config.json norm_topk_prob={want_norm_topk_prob!r}: {contract_summary}"))
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
				else:
					want_layers = int((expected_prefix.get("layers", {}) or {}).get("count", 0))
					want_mtp = int((expected_prefix.get("mtp", {}) or {}).get("count", 0))
					if chk.get("weight_map_layers_tensor_key_count") != want_layers:
						failures.append(Failure(28, f"contract summary checkpoint_index.weight_map_layers_tensor_key_count mismatch (expected {want_layers}): {contract_summary}"))
					if chk.get("weight_map_mtp_tensor_key_count") != want_mtp:
						failures.append(Failure(29, f"contract summary checkpoint_index.weight_map_mtp_tensor_key_count mismatch (expected {want_mtp}): {contract_summary}"))

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
							layer_req_keys = tk.get("layer_required_nonexpert_keys_by_layer_id", None)
							layer_expected = tk.get("layer_expected_tensor_key_count_by_layer_id", None)
							layer_counts = tk.get("layer_tensor_key_count_by_layer_id", None)
							layer_ok = tk.get("layer_expected_tensor_key_count_by_layer_id_ok", None)
							if not (isinstance(layer_req, dict) and isinstance(layer_req_keys, dict) and isinstance(layer_expected, dict) and isinstance(layer_counts, dict) and isinstance(layer_ok, dict)):
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

									exp_keys = [f"layers.{i}.{s}" for s in exp]
									got_req_keys = layer_req_keys.get(key)
									if got_req_keys != exp_keys:
										failures.append(Failure(126, f"contract summary tensor_keys.layer_required_nonexpert_keys_by_layer_id[{i}] mismatch (got_len={len(got_req_keys) if isinstance(got_req_keys, list) else 'n/a'} expected_len={len(exp_keys)}): {contract_summary}"))
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
					mtp_req_keys_by_layer = tk.get("mtp_required_nonexpert_keys_by_layer_id", None)
					mtp_req_suffixes = tk.get("mtp_required_nonexpert_suffixes", None)
					mtp0 = tk.get("mtp0", None)
					if not isinstance(mtp_counts, dict) or not isinstance(mtp_ok, dict) or not isinstance(mtp_req_keys_by_layer, dict) or not isinstance(mtp_req_suffixes, list) or not isinstance(mtp0, dict):
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

							exp_mtp_keys = [prefix + str(s) for s in mtp_req_suffixes]
							got_mtp_keys = mtp_req_keys_by_layer.get(str(mtp_id))
							if got_mtp_keys != exp_mtp_keys:
								failures.append(Failure(127, f"contract summary tensor_keys.mtp_required_nonexpert_keys_by_layer_id[{mtp_id}] mismatch (got_len={len(got_mtp_keys) if isinstance(got_mtp_keys, list) else 'n/a'} expected_len={len(exp_mtp_keys)}): {contract_summary}"))
								break

						if mtp0.get("present") is True:
							got0 = mtp0.get("required_nonexpert_keys", None)
							want0 = mtp_req_keys_by_layer.get("0")
							if got0 != want0:
								failures.append(Failure(128, f"contract summary tensor_keys.mtp0.required_nonexpert_keys must match mtp_required_nonexpert_keys_by_layer_id[0]: {contract_summary}"))

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
						"artifact_requires_mtp_keys_sha256_match_official": True,
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
					attn_obj = summary.get("attention_schedule", {})
					want_ratios = attn_obj.get("mtp_compress_ratios", None) if isinstance(attn_obj, dict) else None
					got_ratios = mtp.get("compress_ratios", None)
					if not (isinstance(want_ratios, list) and isinstance(got_ratios, list) and got_ratios == want_ratios):
						failures.append(Failure(153, f"contract summary mtp.compress_ratios mismatch (expected attention_schedule.mtp_compress_ratios): {contract_summary}"))
					ex = mtp.get("checkpoint_key_examples", None)
					if want_layers > 0:
						expected_layer_ids = list(range(int(want_layers)))
						if not isinstance(ex, dict):
							failures.append(Failure(185, f"contract summary mtp.checkpoint_key_examples must be an object when num_nextn_predict_layers>0: {contract_summary}"))
						else:
							if ex.get("layer_ids") != expected_layer_ids:
								failures.append(Failure(186, f"contract summary mtp.checkpoint_key_examples.layer_ids mismatch (got {ex.get('layer_ids')!r} expected {expected_layer_ids}): {contract_summary}"))
							want_prefixes = [f"mtp.{i}." for i in expected_layer_ids]
							if ex.get("prefixes") != want_prefixes:
								failures.append(Failure(187, f"contract summary mtp.checkpoint_key_examples.prefixes mismatch (got {ex.get('prefixes')!r} expected {want_prefixes}): {contract_summary}"))
							for k in ("first_keys_sample", "last_keys_sample"):
								v = ex.get(k, None)
								if v is None:
									continue
								if not (isinstance(v, list) and all(isinstance(x, str) and x.startswith("mtp.") for x in v)):
									failures.append(Failure(188, f"contract summary mtp.checkpoint_key_examples.{k} must be a list of mtp.* strings or null: {contract_summary}"))
									break
						ns = mtp.get("namespace", None)
						if not isinstance(ns, dict):
							failures.append(Failure(189, f"contract summary mtp.namespace must be an object when num_nextn_predict_layers>0: {contract_summary}"))
						else:
							want_prefixes = [f"mtp.{i}." for i in expected_layer_ids]
							if ns.get("expected_layer_ids") != expected_layer_ids:
								failures.append(Failure(190, f"contract summary mtp.namespace.expected_layer_ids mismatch (got {ns.get('expected_layer_ids')!r} expected {expected_layer_ids}): {contract_summary}"))
							elif ns.get("expected_prefixes") != want_prefixes:
								failures.append(Failure(191, f"contract summary mtp.namespace.expected_prefixes mismatch (got {ns.get('expected_prefixes')!r} expected {want_prefixes}): {contract_summary}"))
							elif ns.get("official_present_layer_ids") != expected_layer_ids:
								failures.append(Failure(192, f"contract summary mtp.namespace.official_present_layer_ids mismatch (got {ns.get('official_present_layer_ids')!r} expected {expected_layer_ids}): {contract_summary}"))
							elif ns.get("official_present_prefixes") != want_prefixes:
								failures.append(Failure(193, f"contract summary mtp.namespace.official_present_prefixes mismatch (got {ns.get('official_present_prefixes')!r} expected {want_prefixes}): {contract_summary}"))
							elif ns.get("official_complete") is not True:
								failures.append(Failure(194, f"contract summary mtp.namespace.official_complete must be true when num_nextn_predict_layers>0: {contract_summary}"))

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
					src = mtp_sem.get("source_helpers", None)
					if not isinstance(src, dict):
						failures.append(Failure(159, f"contract summary mtp.semantics.source_helpers missing or invalid: {contract_summary}"))
					else:
						ref = src.get("reference_source", None)
						if not (isinstance(ref, str) and "MTPBlock.forward" in ref):
							failures.append(Failure(160, f"contract summary mtp.semantics.source_helpers.reference_source missing or unexpected: {contract_summary}"))
						else:
							mb = src.get("mtp_block_forward", None)
							if not isinstance(mb, dict):
								failures.append(Failure(161, f"contract summary mtp.semantics.source_helpers.mtp_block_forward missing or invalid: {contract_summary}"))
							else:
								lines = mb.get("source_lines", None)
								digest = mb.get("source_lines_sha256", None)
								if not (isinstance(lines, list) and lines and all(isinstance(x, str) for x in lines) and isinstance(digest, str)):
									failures.append(Failure(162, f"contract summary mtp.semantics.source_helpers.mtp_block_forward.source_lines missing or invalid: {contract_summary}"))
								else:
									if digest != sha256_lines(lines):
										failures.append(Failure(163, f"contract summary mtp.semantics.source_helpers.mtp_block_forward.source_lines_sha256 mismatch: {contract_summary}"))
									else:
										markers = (
											"def forward(",
											"self.embed(",
											"self.e_proj(",
											"self.h_proj(",
											"super().forward",
											"logits = self.head(",
										)
										joined = "\n".join(lines)
										if not all(m in joined for m in markers):
											failures.append(Failure(164, f"contract summary mtp.semantics.source_helpers.mtp_block_forward source missing required markers: {contract_summary}"))

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
						"topk_method": "moe.topk_method",
						"norm_topk_prob": "moe.norm_topk_prob",
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

				gc = q.get("gguf_compat", {}) if isinstance(q, dict) else {}
				if not isinstance(gc, dict):
					failures.append(Failure(78, f"contract summary quantization.gguf_compat must be an object: {contract_summary}"))
				else:
					want_prefixes = ["F8_"]
					want_cats = ["attn", "ffn_other", "shared_expert_packed", "shared_experts", "top_level"]
					want_fp4_types = ["MXFP4"]
					if gc.get("dense_fp8_like_type_prefixes") != want_prefixes:
						failures.append(Failure(79, f"contract summary quantization.gguf_compat.dense_fp8_like_type_prefixes mismatch (got {gc.get('dense_fp8_like_type_prefixes')!r} expected {want_prefixes!r}): {contract_summary}"))
					if gc.get("dense_fp8_like_evidence_categories") != want_cats:
						failures.append(Failure(80, f"contract summary quantization.gguf_compat.dense_fp8_like_evidence_categories mismatch (got {gc.get('dense_fp8_like_evidence_categories')!r} expected {want_cats!r}): {contract_summary}"))
					if gc.get("expert_fp4_like_types") != want_fp4_types:
						failures.append(Failure(81, f"contract summary quantization.gguf_compat.expert_fp4_like_types mismatch (got {gc.get('expert_fp4_like_types')!r} expected {want_fp4_types!r}): {contract_summary}"))
					if not (isinstance(gc.get("note"), str) and gc.get("note")):
						failures.append(Failure(82, f"contract summary quantization.gguf_compat.note must be a non-empty string: {contract_summary}"))

				oracle = summary.get("oracle", {})
				if not isinstance(oracle, dict):
					failures.append(Failure(90, f"contract summary oracle must be an object: {contract_summary}"))
				else:
					prompts_default_topk = None
					prompts_path = FIX / "oracle" / "prompts.json"
					try:
						prompts = load_json(prompts_path)
						if isinstance(prompts, dict) and isinstance(prompts.get("default_topk"), int):
							prompts_default_topk = int(prompts.get("default_topk"))
					except Exception:
						prompts_default_topk = None

					enc_oracle = oracle.get("encoding_oracle", {})
					log_oracle = oracle.get("logits_oracle", {})
					mtp_oracle = oracle.get("mtp", {})
					if not (isinstance(enc_oracle, dict) and enc_oracle.get("required") is True and isinstance(enc_oracle.get("fixtures_glob"), str)):
						failures.append(Failure(91, f"contract summary oracle.encoding_oracle must declare required=true and fixtures_glob: {contract_summary}"))
					if not (isinstance(log_oracle, dict) and log_oracle.get("weights_required") is True and isinstance(log_oracle.get("generator"), str)):
						failures.append(Failure(92, f"contract summary oracle.logits_oracle must declare weights_required=true and generator: {contract_summary}"))
					if not (isinstance(mtp_oracle, dict) and mtp_oracle.get("weights_required") is True and isinstance(mtp_oracle.get("generator_hint"), str)):
						failures.append(Failure(93, f"contract summary oracle.mtp must declare weights_required=true and generator_hint: {contract_summary}"))
					if isinstance(log_oracle, dict):
						acc = log_oracle.get("acceptance", {})
						if not (isinstance(acc, dict) and isinstance(acc.get("topk_k"), int)):
							failures.append(Failure(181, f"contract summary oracle.logits_oracle.acceptance.topk_k must be an integer: {contract_summary}"))
						elif prompts_default_topk is not None and int(acc.get("topk_k")) != int(prompts_default_topk):
							failures.append(Failure(182, f"contract summary oracle.logits_oracle.acceptance.topk_k mismatch (got {acc.get('topk_k')!r} expected prompts default_topk={prompts_default_topk}): {contract_summary}"))
					if isinstance(mtp_oracle, dict):
						acc = mtp_oracle.get("acceptance", {})
						if not (isinstance(acc, dict) and isinstance(acc.get("topk_k"), int)):
							failures.append(Failure(183, f"contract summary oracle.mtp.acceptance.topk_k must be an integer: {contract_summary}"))
						elif prompts_default_topk is not None and int(acc.get("topk_k")) != int(prompts_default_topk):
							failures.append(Failure(184, f"contract summary oracle.mtp.acceptance.topk_k mismatch (got {acc.get('topk_k')!r} expected prompts default_topk={prompts_default_topk}): {contract_summary}"))

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

			def ratio_kind(r: int) -> str:
				if r == 0:
					return("sliding")
				if r == 4:
					return("csa")
				if r == 128:
					return("hca")
				return("unknown")

			main_kind_map = attn.get("main_layer_type_by_layer_id", None)
			if not isinstance(main_kind_map, dict) or len(main_kind_map) != n_layers:
				failures.append(Failure(154, f"contract summary attention_schedule.main_layer_type_by_layer_id must be an object with n_layers={n_layers} entries: {contract_summary}"))
			else:
				for i, r in enumerate(compress_ratios[:n_layers]):
					want = ratio_kind(int(r))
					if want == "unknown":
						failures.append(Failure(155, f"unexpected trunk compress_ratio {r!r} at layer {i}: {contract_summary}"))
						break
					got = main_kind_map.get(str(i))
					if got != want:
						failures.append(Failure(156, f"contract summary attention_schedule.main_layer_type_by_layer_id[{i}] mismatch (got {got!r} expected {want!r}): {contract_summary}"))
						break

			main_ratio_map = attn.get("main_compress_ratio_by_layer_id", None)
			if not isinstance(main_ratio_map, dict) or len(main_ratio_map) != n_layers:
				failures.append(Failure(157, f"contract summary attention_schedule.main_compress_ratio_by_layer_id must be an object with n_layers={n_layers} entries: {contract_summary}"))
			else:
				for i, r in enumerate(compress_ratios[:n_layers]):
					got = main_ratio_map.get(str(i))
					if got != int(r):
						failures.append(Failure(158, f"contract summary attention_schedule.main_compress_ratio_by_layer_id[{i}] mismatch (got {got!r} expected {int(r)!r}): {contract_summary}"))
						break

			full_kind_map = attn.get("layer_type_by_layer_id", None)
			full_ratio_map = attn.get("compress_ratio_by_layer_id", None)
			want_total = int(n_layers + n_mtp_layers)
			if not isinstance(full_kind_map, dict) or len(full_kind_map) != want_total:
				failures.append(Failure(159, f"contract summary attention_schedule.layer_type_by_layer_id must be an object with n_layers+n_mtp_layers={want_total} entries: {contract_summary}"))
			elif not isinstance(full_ratio_map, dict) or len(full_ratio_map) != want_total:
				failures.append(Failure(160, f"contract summary attention_schedule.compress_ratio_by_layer_id must be an object with n_layers+n_mtp_layers={want_total} entries: {contract_summary}"))
			else:
				for i, r in enumerate(compress_ratios[:want_total]):
					got_kind = full_kind_map.get(str(i))
					got_ratio = full_ratio_map.get(str(i))
					want_kind = ratio_kind(int(r))
					if want_kind == "unknown":
						failures.append(Failure(161, f"unexpected compress_ratio {r!r} at layer_id {i}: {contract_summary}"))
						break
					if got_kind != want_kind:
						failures.append(Failure(162, f"contract summary attention_schedule.layer_type_by_layer_id[{i}] mismatch (got {got_kind!r} expected {want_kind!r}): {contract_summary}"))
						break
					if got_ratio != int(r):
						failures.append(Failure(163, f"contract summary attention_schedule.compress_ratio_by_layer_id[{i}] mismatch (got {got_ratio!r} expected {int(r)!r}): {contract_summary}"))
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
