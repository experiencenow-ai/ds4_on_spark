#!/usr/bin/env python3
"""Build and validate DS4 token commit profile artifacts."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any

try:
	from scripts._lib.json_utils import artifact_sha256
	from scripts._lib.json_utils import load_json
except ImportError:
	from _lib.json_utils import artifact_sha256
	from _lib.json_utils import load_json


FORMAT = "ds4-token-commit-profile-v1"
COMPONENTS = (
	"stage2_final_hidden_output_ms",
	"output_head_ms",
	"top1_argmax_ms",
	"logits_readback_ms",
	"token_id_readback_ms",
	"token_hash_ms",
	"result_collection_ms",
	"synchronization_wait_ms",
)
BOTTLENECKS = {
	"full_batch_head_projection",
	"logits_readback",
	"cpu_argmax",
	"device_argmax",
	"token_hash_readback",
	"synchronization",
	"result_collection",
	"other",
}


def write_json(path: Path, obj: dict[str, Any]) -> None:
	path.parent.mkdir(parents=True, exist_ok=True)
	path.write_text(json.dumps(obj, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def max_number(values: Any) -> float:
	if not isinstance(values, list):
		return 0.0
	items = [float(v) for v in values if isinstance(v, (int, float))]
	return max(items) if items else 0.0


def dominant_component(profile: dict[str, Any]) -> str:
	output_head = max_number(profile.get("output_head_ms"))
	top1 = max_number(profile.get("top1_argmax_ms"))
	logits = max_number(profile.get("logits_readback_ms"))
	token_ids = max_number(profile.get("token_id_readback_ms"))
	token_hash = max_number(profile.get("token_hash_ms"))
	sync = max_number(profile.get("synchronization_wait_ms"))
	collection = max_number(profile.get("result_collection_ms"))
	values = [
		(output_head, "full_batch_head_projection"),
		(logits, "logits_readback"),
		(top1, "device_argmax"),
		(token_ids, "token_hash_readback"),
		(token_hash, "token_hash_readback"),
		(sync, "synchronization"),
		(collection, "result_collection"),
	]
	return max(values, key=lambda item: item[0])[1]


def build_from_stage(args: argparse.Namespace) -> dict[str, Any]:
	stage = load_json(Path(args.stage_handoff))
	profile = stage.get("token_commit_profile")
	stage_raw: dict[str, Any] = {}
	if not isinstance(profile, dict):
		artifact_dir = stage.get("artifact_dir")
		if isinstance(artifact_dir, str) and artifact_dir:
			raw_path = Path(artifact_dir) / "stage2.out"
			if raw_path.exists():
				stage_raw = load_json(raw_path)
				profile = stage_raw.get("token_commit_profile")
	if not isinstance(profile, dict):
		raise ValueError("stage handoff artifact has no token_commit_profile object")
	if not stage_raw:
		stage_raw = stage
	obj: dict[str, Any] = {
		"format": FORMAT,
		"run_id": args.run_id,
		"source_stage_handoff": args.stage_handoff,
		"batch_size": int(stage.get("batch_size", 0)),
		"microbatch_count": int(stage.get("microbatch_count", 0)),
		"token_commit_mode": str(stage.get("token_commit_mode", stage_raw.get("token_commit_mode", ""))),
		"committed_token_ids_present": bool(stage.get("committed_token_ids_present")),
		"decode_only_rows_per_s": float(stage.get("achieved_streaming_rows_per_s", 0.0)),
		"end_to_end_output_tokens_per_s": float(args.end_to_end_output_tokens_per_s),
		"final_logits_hash": str(stage.get("final_logits_hash", "")),
		"token_hash": str(stage.get("token_hash", "")),
		"bottleneck_component": str(args.bottleneck_component or dominant_component(profile)),
	}
	for key in COMPONENTS:
		obj[key] = list(profile.get(key, []))
	obj["artifact_sha256"] = artifact_sha256(obj)
	obj["artifact_hash"] = obj["artifact_sha256"]
	return obj


def validate_artifact(obj: dict[str, Any]) -> list[str]:
	errors: list[str] = []
	if obj.get("format") != FORMAT:
		errors.append(f"format must be {FORMAT}")
	if obj.get("artifact_sha256") != artifact_sha256(obj):
		errors.append("artifact_sha256 does not match canonical artifact body")
	if obj.get("artifact_hash") != obj.get("artifact_sha256"):
		errors.append("artifact_hash must match artifact_sha256")
	if not isinstance(obj.get("batch_size"), int) or obj.get("batch_size", 0) <= 0:
		errors.append("batch_size must be positive")
	if not isinstance(obj.get("microbatch_count"), int) or obj.get("microbatch_count", 0) <= 0:
		errors.append("microbatch_count must be positive")
	if obj.get("bottleneck_component") not in BOTTLENECKS:
		errors.append("bottleneck_component is invalid")
	mb = obj.get("microbatch_count")
	for key in COMPONENTS:
		values = obj.get(key)
		if not isinstance(values, list) or not isinstance(mb, int) or len(values) != mb:
			errors.append(f"{key} length must match microbatch_count")
		elif not all(isinstance(v, (int, float)) and v >= 0 for v in values):
			errors.append(f"{key} must contain non-negative numbers")
	if obj.get("committed_token_ids_present") is True:
		for key in ("final_logits_hash", "token_hash"):
			value = obj.get(key)
			if not isinstance(value, str) or not value.startswith("fnv64:") or value.endswith("0000000000000000"):
				errors.append(f"{key} must be a non-zero fnv64 when committed tokens are present")
	if not isinstance(obj.get("token_commit_mode"), str) or obj.get("token_commit_mode", "") == "":
		errors.append("token_commit_mode must be non-empty")
	return errors


def main() -> int:
	import sys
	if len(sys.argv) > 1 and sys.argv[1] not in ("build-from-stage", "validate", "-h", "--help"):
		failed = False
		for raw in sys.argv[1:]:
			path = Path(raw)
			try:
				errors = validate_artifact(load_json(path))
			except (OSError, ValueError, json.JSONDecodeError) as exc:
				print(str(exc))
				return 1
			if errors:
				failed = True
				for error in errors:
					print(f"error: {path}: {error}")
			else:
				print(f"ok: {path}")
		return 2 if failed else 0
	ap = argparse.ArgumentParser()
	sub = ap.add_subparsers(dest="cmd")
	build = sub.add_parser("build-from-stage")
	build.add_argument("--stage-handoff", required=True)
	build.add_argument("--run-id", required=True)
	build.add_argument("--end-to-end-output-tokens-per-s", type=float, default=0.0)
	build.add_argument("--bottleneck-component", default="")
	build.add_argument("--out", required=True)
	validate = sub.add_parser("validate")
	validate.add_argument("paths", nargs="+")
	args = ap.parse_args()
	try:
		if args.cmd == "build-from-stage":
			obj = build_from_stage(args)
			errors = validate_artifact(obj)
			if errors:
				raise ValueError("; ".join(errors))
			write_json(Path(args.out), obj)
			print(json.dumps(obj, indent=2, sort_keys=True))
		else:
			paths = getattr(args, "paths", [])
			if not paths:
				raise ValueError("no paths provided")
			failed = False
			for raw in paths:
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
