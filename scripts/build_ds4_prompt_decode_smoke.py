#!/usr/bin/env python3
"""Build and validate DS4 prompt-decode smoke artifacts."""

from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
from typing import Any

try:
	from scripts import compare_ds4_pp1_ppn_outputs as outputs
	from scripts import validate_ds4_pipeline_parity as parity
	from scripts._lib.json_utils import artifact_sha256
	from scripts._lib.json_utils import load_json
except ImportError:
	import compare_ds4_pp1_ppn_outputs as outputs
	import validate_ds4_pipeline_parity as parity
	from _lib.json_utils import artifact_sha256
	from _lib.json_utils import load_json


FORMAT = "ds4-prompt-decode-smoke-v1"
TOKEN_COMMIT_FORMAT = "ds4-token-commit-export-v1"
ELIGIBLE_PARITY_SCOPES = {"cross_spark_ppn", "parity_passed_prefill_decode"}


def canonical_bytes(obj: Any) -> bytes:
	return json.dumps(obj, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode("utf-8")


def sha256_obj(obj: Any) -> str:
	return "sha256:" + hashlib.sha256(canonical_bytes(obj)).hexdigest()


def write_json(path: Path, obj: dict[str, Any]) -> None:
	path.parent.mkdir(parents=True, exist_ok=True)
	path.write_text(json.dumps(obj, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def token_hash(token_ids: list[int]) -> str:
	return sha256_obj({"committed_token_ids": token_ids})


def is_nonempty_sha256(value: Any) -> bool:
	return isinstance(value, str) and value.startswith("sha256:") and len(value) == 71


def build_token_commit_export(args: argparse.Namespace) -> dict[str, Any]:
	pp1 = load_json(Path(args.pp1_export))
	errors = outputs.validate_export(pp1)
	if errors:
		raise ValueError("pp1 export invalid: " + "; ".join(errors))
	token_ids = parse_token_ids(args.committed_token_ids)
	if not token_ids:
		raise ValueError("--committed-token-ids is required for token commit export")
	if args.commit_policy == "sampling":
		sampling_params = json.loads(args.sampling_params)
		if not isinstance(sampling_params, dict):
			raise ValueError("--sampling-params must be a JSON object")
	else:
		sampling_params = {}
	command_hash = outputs.sha256_obj({
		"script": "build_ds4_prompt_decode_smoke.py",
		"cmd": "token-commit-export",
		"commit_policy": args.commit_policy,
		"committed_token_ids": token_ids,
		"source_command": args.source_command,
	})
	obj = {
		"format": TOKEN_COMMIT_FORMAT,
		"run_id": args.run_id,
		"model_id": str(pp1.get("model_id", "")),
		"runtime_id": str(pp1.get("runtime_id", "")),
		"quantization_id": str(pp1.get("quantization_id", "")),
		"input_tokens_sha256": str(pp1.get("input_tokens_sha256", "")),
		"batch_size": int(args.batch_size),
		"row_count": int(args.row_count),
		"optimized_kernel_flags": dict(pp1.get("optimized_kernel_flags", {})),
		"final_logits_hash": str(pp1.get("final_logits_hash", "")),
		"output_head_hash": str(pp1.get("output_head_hash", "")),
		"commit_policy": args.commit_policy,
		"sampling_params": sampling_params,
		"committed_token_ids": token_ids,
		"token_hash": token_hash(token_ids),
		"command_hash": command_hash,
		"source_command": args.source_command,
		"source_artifact": args.pp1_export,
		"source_artifact_sha256": str(pp1.get("artifact_sha256", "")),
	}
	obj["artifact_sha256"] = artifact_sha256(obj)
	obj["artifact_hash"] = obj["artifact_sha256"]
	errors = validate_token_commit_export(obj)
	if errors:
		raise ValueError("; ".join(errors))
	return obj


def validate_token_commit_export(obj: dict[str, Any]) -> list[str]:
	errors: list[str] = []
	for key in ("format", "run_id", "model_id", "runtime_id", "quantization_id", "input_tokens_sha256", "final_logits_hash", "output_head_hash", "commit_policy", "token_hash", "command_hash", "artifact_sha256", "artifact_hash"):
		if not isinstance(obj.get(key), str) or obj.get(key, "").strip() == "":
			errors.append(f"{key} must be a non-empty string")
	if obj.get("format") != TOKEN_COMMIT_FORMAT:
		errors.append(f"format must be {TOKEN_COMMIT_FORMAT}")
	if obj.get("commit_policy") not in ("argmax", "sampling"):
		errors.append("commit_policy must be argmax or sampling")
	if obj.get("commit_policy") == "sampling" and not isinstance(obj.get("sampling_params"), dict):
		errors.append("sampling commit requires sampling_params object")
	if obj.get("commit_policy") == "argmax" and obj.get("sampling_params") != {}:
		errors.append("argmax commit must use empty sampling_params")
	if not isinstance(obj.get("committed_token_ids"), list) or not obj.get("committed_token_ids"):
		errors.append("committed_token_ids must be a non-empty list")
	elif not all(isinstance(v, int) and v >= 0 for v in obj["committed_token_ids"]):
		errors.append("committed_token_ids must contain non-negative integers")
	if obj.get("token_hash") != token_hash(obj.get("committed_token_ids", [])):
		errors.append("token_hash does not match committed_token_ids")
	if not isinstance(obj.get("optimized_kernel_flags"), dict) or not obj.get("optimized_kernel_flags"):
		errors.append("optimized_kernel_flags must be a non-empty object")
	for key in ("batch_size", "row_count"):
		if not isinstance(obj.get(key), int) or obj.get(key, 0) <= 0:
			errors.append(f"{key} must be a positive integer")
	if obj.get("artifact_sha256") != artifact_sha256(obj):
		errors.append("artifact_sha256 does not match canonical token commit body")
	if obj.get("artifact_hash") != obj.get("artifact_sha256"):
		errors.append("artifact_hash must match artifact_sha256")
	return errors


def parse_token_ids(text: str) -> list[int]:
	if text.strip() == "":
		return []
	raw = json.loads(text)
	if not isinstance(raw, list) or not all(isinstance(v, int) and v >= 0 for v in raw):
		raise ValueError("--committed-token-ids must be a JSON list of non-negative integers")
	return raw


def build_artifact(args: argparse.Namespace) -> dict[str, Any]:
	stage = load_json(Path(args.stage_handoff))
	pp1 = load_json(Path(args.pp1_export))
	ppn = load_json(Path(args.ppn_export))
	parity_obj = load_json(Path(args.parity_artifact))
	for name, obj in (("pp1", pp1), ("ppn", ppn)):
		errors = outputs.validate_export(obj)
		if errors:
			raise ValueError(f"{name} export invalid: {'; '.join(errors)}")
	parity_errors = parity.validate_artifact(parity_obj)
	if parity_errors:
		raise ValueError("parity artifact invalid: " + "; ".join(parity_errors))
	token_commit = None
	token_commit_errors: list[str] = []
	if args.token_commit_export:
		token_commit = load_json(Path(args.token_commit_export))
		token_commit_errors = validate_token_commit_export(token_commit)
		if token_commit_errors:
			raise ValueError("token commit export invalid: " + "; ".join(token_commit_errors))
	token_ids = list(token_commit.get("committed_token_ids", [])) if token_commit is not None else parse_token_ids(args.committed_token_ids)
	token_status = "committed" if token_ids else "blocked"
	blocker_kind = "none" if token_ids else "missing_argmax_token_commit_hook"
	blocker_detail = "" if token_ids else "The DS4 batch stack probe emitted finite logits/output-head hashes but no argmax or sampled committed token id."
	if token_commit is not None:
		blocker_detail = ""
		if token_commit.get("optimized_kernel_flags") != parity_obj.get("optimized_kernel_flags"):
			blocker_kind = "token_commit_kernel_flags_mismatch"
			blocker_detail = "Token commit optimized kernel flags do not match the parity artifact."
		elif token_commit.get("input_tokens_sha256") != parity_obj.get("input_tokens_sha256"):
			blocker_kind = "token_commit_input_mismatch"
			blocker_detail = "Token commit input_tokens_sha256 does not match the parity artifact."
		elif token_commit.get("final_logits_hash") != pp1.get("final_logits_hash"):
			blocker_kind = "token_commit_logits_mismatch"
			blocker_detail = "Token commit final_logits_hash does not match the PP=1 final-output export."
	obj = {
		"format": FORMAT,
		"run_id": args.run_id,
		"model_id": str(ppn.get("model_id", "")),
		"runtime_id": str(ppn.get("runtime_id", "")),
		"quantization_id": str(ppn.get("quantization_id", "")),
		"input_tokens_sha256": str(ppn.get("input_tokens_sha256", ppn.get("input_sha256", ""))),
		"batch_size": int(stage.get("batch_size", 0)),
		"microbatch_count": int(stage.get("microbatch_count", 0)),
		"optimized_kernel_flags": dict(ppn.get("optimized_kernel_flags", {})),
		"pp1_final_logits_hash": str(pp1.get("final_logits_hash", pp1.get("output_hash", ""))),
		"ppn_final_logits_hash": str(ppn.get("final_logits_hash", ppn.get("output_hash", ""))),
		"pp1_output_sha256": str(pp1.get("output_sha256", "")),
		"ppn_output_sha256": str(ppn.get("output_sha256", "")),
		"parity_artifact": args.parity_artifact,
		"parity_artifact_sha256": str(parity_obj.get("artifact_sha256", "")),
		"parity_status": str(parity_obj.get("parity_status", "")),
		"parity_scope": str(parity_obj.get("parity_scope", "")),
		"comparison_kind": str(parity_obj.get("comparison_kind", "")),
		"parity_optimized_kernel_flags": dict(parity_obj.get("optimized_kernel_flags", {})),
		"synthetic_evidence": bool(parity_obj.get("comparison_kind") == "synthetic_integrity"),
		"final_output_finite": bool(stage.get("final_output_finite")) and bool(pp1.get("finite_output", True)),
		"output_head_hash": str(pp1.get("output_head_hash", "")),
		"token_commit_status": token_status,
		"token_commit_artifact": args.token_commit_export,
		"token_commit_artifact_sha256": "" if token_commit is None else str(token_commit.get("artifact_sha256", "")),
		"commit_policy": "" if token_commit is None else str(token_commit.get("commit_policy", "")),
		"sampling_params": {} if token_commit is None else dict(token_commit.get("sampling_params", {})),
		"committed_token_ids": token_ids,
		"token_hash": str(token_commit.get("token_hash", "")) if token_commit is not None else (token_hash(token_ids) if token_ids else ""),
		"achieved_streaming_rows_per_s": float(stage.get("achieved_streaming_rows_per_s", 0.0)),
		"steady_state_pipeline_bound_rows_per_s": float(stage.get("steady_state_pipeline_bound_rows_per_s", 0.0)),
		"production_generation_eligible": bool(args.production_generation_eligible),
		"blocker_kind": blocker_kind,
		"blocker_detail": blocker_detail,
		"artifact_refs": [
			{"name": "stage_handoff", "path": args.stage_handoff},
			{"name": "pp1_final_output_export", "path": args.pp1_export, "sha256": str(pp1.get("artifact_sha256", ""))},
			{"name": "ppn_final_output_export", "path": args.ppn_export, "sha256": str(ppn.get("artifact_sha256", ""))},
			{"name": "parity_artifact", "path": args.parity_artifact, "sha256": str(parity_obj.get("artifact_sha256", ""))},
		],
		"command_hash": outputs.sha256_obj({"script": "build_ds4_prompt_decode_smoke.py", "run_id": args.run_id}),
	}
	if token_commit is not None:
		obj["artifact_refs"].append({"name": "token_commit_export", "path": args.token_commit_export, "sha256": str(token_commit.get("artifact_sha256", ""))})
	obj["artifact_sha256"] = artifact_sha256(obj)
	obj["artifact_hash"] = obj["artifact_sha256"]
	errors = validate_artifact(obj)
	if errors:
		raise ValueError("; ".join(errors))
	return obj


def validate_artifact(obj: dict[str, Any]) -> list[str]:
	errors: list[str] = []
	for key in ("format", "run_id", "model_id", "runtime_id", "quantization_id", "input_tokens_sha256", "pp1_final_logits_hash", "ppn_final_logits_hash", "parity_status", "parity_scope", "comparison_kind", "token_commit_status", "blocker_kind", "artifact_sha256", "artifact_hash"):
		if not isinstance(obj.get(key), str) or obj.get(key, "").strip() == "":
			errors.append(f"{key} must be a non-empty string")
	if obj.get("format") != FORMAT:
		errors.append(f"format must be {FORMAT}")
	if obj.get("artifact_sha256") != artifact_sha256(obj):
		errors.append("artifact_sha256 does not match canonical smoke body")
	if obj.get("artifact_hash") != obj.get("artifact_sha256"):
		errors.append("artifact_hash must match artifact_sha256")
	if obj.get("comparison_kind") not in parity.QUALITY_COMPARISON_KINDS:
		errors.append("comparison_kind must be logits, tokens, or hidden_state")
	eligible_errors = eligibility_errors(obj)
	if obj.get("token_commit_status") == "committed":
		if not isinstance(obj.get("committed_token_ids"), list) or not obj.get("committed_token_ids"):
			errors.append("committed token smoke requires committed_token_ids")
		if not is_nonempty_sha256(obj.get("token_hash")):
			errors.append("committed token smoke requires token_hash")
		if obj.get("token_hash") != token_hash(obj.get("committed_token_ids", [])):
			errors.append("token_hash does not match committed_token_ids")
		if obj.get("blocker_kind") != "none" and obj.get("production_generation_eligible") is True:
			errors.append("committed token smoke must use blocker_kind=none")
	else:
		if obj.get("token_hash") != "":
			errors.append("blocked token smoke must not invent token_hash")
		if obj.get("blocker_kind") == "none":
			errors.append("blocked token smoke requires a blocker_kind")
	if obj.get("production_generation_eligible") is True and eligible_errors:
		errors.extend("production_generation_eligible: " + item for item in eligible_errors)
	for key in ("batch_size", "microbatch_count"):
		if not isinstance(obj.get(key), int) or obj.get(key, 0) <= 0:
			errors.append(f"{key} must be a positive integer")
	for key in ("achieved_streaming_rows_per_s", "steady_state_pipeline_bound_rows_per_s"):
		if not isinstance(obj.get(key), (int, float)) or float(obj.get(key, 0.0)) <= 0.0:
			errors.append(f"{key} must be positive")
	if obj.get("final_output_finite") is not True:
		errors.append("final_output_finite must be true for the decode smoke")
	return errors


def eligibility_errors(obj: dict[str, Any]) -> list[str]:
	errors: list[str] = []
	if obj.get("parity_status") != "passed":
		errors.append("parity_status must be passed")
	if obj.get("parity_scope") not in ELIGIBLE_PARITY_SCOPES:
		errors.append("parity_scope must be cross_spark_ppn or parity_passed_prefill_decode")
	if obj.get("comparison_kind") not in ("logits", "tokens", "hidden_state"):
		errors.append("comparison_kind must be logits, tokens, or hidden_state")
	if obj.get("synthetic_evidence") is True:
		errors.append("synthetic-only evidence is not eligible")
	if not isinstance(obj.get("optimized_kernel_flags"), dict) or not obj.get("optimized_kernel_flags"):
		errors.append("optimized_kernel_flags must be recorded")
	if obj.get("token_commit_status") != "committed":
		errors.append("token_commit_status must be committed")
	if not isinstance(obj.get("committed_token_ids"), list) or not obj.get("committed_token_ids"):
		errors.append("committed_token_ids must be present")
	if not is_nonempty_sha256(obj.get("token_hash")):
		errors.append("token_hash must be present")
	elif obj.get("token_hash") != token_hash(obj.get("committed_token_ids", [])):
		errors.append("token_hash must match committed_token_ids")
	if obj.get("commit_policy") not in ("argmax", "sampling"):
		errors.append("commit_policy must be argmax or sampling")
	if not is_nonempty_sha256(obj.get("token_commit_artifact_sha256")):
		errors.append("token_commit_artifact_sha256 must be present")
	if obj.get("blocker_kind") != "none":
		errors.append("blocker_kind must be none")
	if obj.get("final_output_finite") is not True:
		errors.append("final_output_finite must be true")
	if obj.get("parity_optimized_kernel_flags") != obj.get("optimized_kernel_flags"):
		errors.append("optimized kernel flags must match parity artifact")
	return errors


def main(argv: list[str] | None = None) -> int:
	ap = argparse.ArgumentParser()
	sub = ap.add_subparsers(dest="cmd", required=True)
	build = sub.add_parser("build")
	build.add_argument("--stage-handoff", required=True)
	build.add_argument("--pp1-export", required=True)
	build.add_argument("--ppn-export", required=True)
	build.add_argument("--parity-artifact", required=True)
	build.add_argument("--run-id", default="ds4-b512-slice-tile8-prompt-decode-smoke")
	build.add_argument("--committed-token-ids", default="")
	build.add_argument("--token-commit-export", default="")
	build.add_argument("--production-generation-eligible", action="store_true")
	build.add_argument("--out", required=True)
	token = sub.add_parser("token-commit-export")
	token.add_argument("--pp1-export", required=True)
	token.add_argument("--run-id", default="ds4-token-commit-export")
	token.add_argument("--committed-token-ids", required=True)
	token.add_argument("--commit-policy", choices=("argmax", "sampling"), default="argmax")
	token.add_argument("--sampling-params", default="{}")
	token.add_argument("--batch-size", type=int, required=True)
	token.add_argument("--row-count", type=int, required=True)
	token.add_argument("--source-command", default="")
	token.add_argument("--out", required=True)
	validate = sub.add_parser("validate")
	validate.add_argument("paths", nargs="+")
	validate_token = sub.add_parser("validate-token-commit")
	validate_token.add_argument("paths", nargs="+")
	args = ap.parse_args(argv)
	try:
		if args.cmd == "build":
			obj = build_artifact(args)
			write_json(Path(args.out), obj)
			print(json.dumps(obj, indent=2, sort_keys=True))
		elif args.cmd == "token-commit-export":
			obj = build_token_commit_export(args)
			write_json(Path(args.out), obj)
			print(json.dumps(obj, indent=2, sort_keys=True))
		else:
			failed = False
			for raw in args.paths:
				path = Path(raw)
				errors = validate_token_commit_export(load_json(path)) if args.cmd == "validate-token-commit" else validate_artifact(load_json(path))
				if errors:
					failed = True
					for error in errors:
						print(f"error: {path}: {error}")
				else:
					print(f"ok: {path}")
			if failed:
				return 2
	except (OSError, ValueError, json.JSONDecodeError) as exc:
		print(str(exc))
		return 1
	return 0


def main_args_for_test(argv: list[str]) -> int:
	return main(argv)


if __name__ == "__main__":
	raise SystemExit(main())
