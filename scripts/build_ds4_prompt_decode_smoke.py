#!/usr/bin/env python3
"""Build and validate DS4 prompt-decode smoke artifacts."""

from __future__ import annotations

import argparse
import copy
import hashlib
import json
from pathlib import Path
from typing import Any

try:
	from scripts import compare_ds4_pp1_ppn_outputs as outputs
	from scripts import validate_ds4_pipeline_parity as parity
except ImportError:
	import compare_ds4_pp1_ppn_outputs as outputs
	import validate_ds4_pipeline_parity as parity


FORMAT = "ds4-prompt-decode-smoke-v1"


def canonical_bytes(obj: Any) -> bytes:
	return json.dumps(obj, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode("utf-8")


def sha256_obj(obj: Any) -> str:
	return "sha256:" + hashlib.sha256(canonical_bytes(obj)).hexdigest()


def artifact_sha256(obj: dict[str, Any]) -> str:
	tmp = copy.deepcopy(obj)
	tmp.pop("artifact_sha256", None)
	tmp.pop("artifact_hash", None)
	return sha256_obj(tmp)


def load_json(path: Path) -> dict[str, Any]:
	obj = json.loads(path.read_text(encoding="utf-8"))
	if not isinstance(obj, dict):
		raise ValueError(f"{path}: root must be an object")
	return obj


def write_json(path: Path, obj: dict[str, Any]) -> None:
	path.parent.mkdir(parents=True, exist_ok=True)
	path.write_text(json.dumps(obj, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def token_hash(token_ids: list[int]) -> str:
	return sha256_obj({"committed_token_ids": token_ids})


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
	token_ids = parse_token_ids(args.committed_token_ids)
	token_status = "committed" if token_ids else "blocked"
	blocker_kind = "none" if token_ids else "missing_argmax_token_commit_hook"
	blocker_detail = "" if token_ids else "The DS4 batch stack probe emitted finite logits/output-head hashes but no argmax or sampled committed token id."
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
		"comparison_kind": str(parity_obj.get("comparison_kind", "")),
		"final_output_finite": bool(stage.get("final_output_finite")) and bool(pp1.get("finite_output", True)),
		"output_head_hash": str(pp1.get("output_head_hash", "")),
		"token_commit_status": token_status,
		"committed_token_ids": token_ids,
		"token_hash": token_hash(token_ids) if token_ids else "",
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
	obj["artifact_sha256"] = artifact_sha256(obj)
	obj["artifact_hash"] = obj["artifact_sha256"]
	errors = validate_artifact(obj)
	if errors:
		raise ValueError("; ".join(errors))
	return obj


def validate_artifact(obj: dict[str, Any]) -> list[str]:
	errors: list[str] = []
	for key in ("format", "run_id", "model_id", "runtime_id", "quantization_id", "input_tokens_sha256", "pp1_final_logits_hash", "ppn_final_logits_hash", "parity_status", "comparison_kind", "token_commit_status", "blocker_kind", "artifact_sha256", "artifact_hash"):
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
	if obj.get("token_commit_status") == "committed":
		if not isinstance(obj.get("committed_token_ids"), list) or not obj.get("committed_token_ids"):
			errors.append("committed token smoke requires committed_token_ids")
		if not isinstance(obj.get("token_hash"), str) or not obj.get("token_hash", "").startswith("sha256:"):
			errors.append("committed token smoke requires token_hash")
		if obj.get("blocker_kind") != "none":
			errors.append("committed token smoke must use blocker_kind=none")
	else:
		if obj.get("token_hash") != "":
			errors.append("blocked token smoke must not invent token_hash")
		if obj.get("blocker_kind") == "none":
			errors.append("blocked token smoke requires a blocker_kind")
	if obj.get("production_generation_eligible") is True and (obj.get("parity_status") != "passed" or obj.get("token_commit_status") != "committed"):
		errors.append("production_generation_eligible requires passed parity and committed token ids")
	for key in ("batch_size", "microbatch_count"):
		if not isinstance(obj.get(key), int) or obj.get(key, 0) <= 0:
			errors.append(f"{key} must be a positive integer")
	for key in ("achieved_streaming_rows_per_s", "steady_state_pipeline_bound_rows_per_s"):
		if not isinstance(obj.get(key), (int, float)) or float(obj.get(key, 0.0)) <= 0.0:
			errors.append(f"{key} must be positive")
	if obj.get("final_output_finite") is not True:
		errors.append("final_output_finite must be true for the decode smoke")
	return errors


def main() -> int:
	ap = argparse.ArgumentParser()
	sub = ap.add_subparsers(dest="cmd", required=True)
	build = sub.add_parser("build")
	build.add_argument("--stage-handoff", required=True)
	build.add_argument("--pp1-export", required=True)
	build.add_argument("--ppn-export", required=True)
	build.add_argument("--parity-artifact", required=True)
	build.add_argument("--run-id", default="ds4-b512-slice-tile8-prompt-decode-smoke")
	build.add_argument("--committed-token-ids", default="")
	build.add_argument("--production-generation-eligible", action="store_true")
	build.add_argument("--out", required=True)
	validate = sub.add_parser("validate")
	validate.add_argument("paths", nargs="+")
	args = ap.parse_args()
	try:
		if args.cmd == "build":
			obj = build_artifact(args)
			write_json(Path(args.out), obj)
			print(json.dumps(obj, indent=2, sort_keys=True))
		else:
			failed = False
			for raw in args.paths:
				path = Path(raw)
				errors = validate_artifact(load_json(path))
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


if __name__ == "__main__":
	raise SystemExit(main())
