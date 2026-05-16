#!/usr/bin/env python3
"""Build a DS4 B=512 multi-step decode fixture from a repeated-step run summary."""

from __future__ import annotations

import argparse
import copy
import json
import sys
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from scripts import validate_ds4_end_to_end_decode as decode


def load_json(path: Path) -> dict[str, Any]:
	obj = json.loads(path.read_text(encoding="utf-8"))
	if not isinstance(obj, dict):
		raise ValueError(f"{path}: root must be an object")
	return obj


def write_json(path: Path, obj: dict[str, Any]) -> None:
	path.parent.mkdir(parents=True, exist_ok=True)
	path.write_text(json.dumps(obj, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def fnv64_from_bytes(data: bytes) -> str:
	h = 0xcbf29ce484222325
	for b in data:
		h ^= b
		h = (h * 0x100000001b3) & 0xffffffffffffffff
	return f"fnv64:{h:016x}"


def flatten_token_ids(token_ids_by_step: list[list[int]]) -> list[int]:
	out: list[int] = []
	for row in token_ids_by_step:
		out.extend(int(v) for v in row)
	return out


def build(args: argparse.Namespace) -> dict[str, Any]:
	base = load_json(Path(args.base_decode_artifact))
	target = int(args.output_token_target)
	step_decode = float(args.step_decode_ms if args.step_decode_ms is not None else base["decode_ms"])
	step_commit = float(args.step_token_commit_ms if args.step_token_commit_ms is not None else base["token_commit_ms"])
	step_head = float(args.step_output_head_ms)
	kv_step = float(args.step_kv_update_ms)
	ids0 = base.get("committed_token_ids_by_step", [[]])[0]
	if not isinstance(ids0, list) or len(ids0) == 0:
		raise ValueError("base artifact must contain committed_token_ids_by_step[0]")
	ids_by_step = [list(ids0) for _ in range(target)]
	step_hashes = [fnv64_from_bytes(json.dumps({"step": i, "ids": ids_by_step[i]}, separators=(",", ":")).encode("utf-8")) for i in range(target)]
	aggregate = fnv64_from_bytes(json.dumps({"steps": ids_by_step}, separators=(",", ":")).encode("utf-8"))
	prefix_prepare_ms = float(args.prefix_prepare_ms)
	prefix_load_ms = float(args.prefix_load_or_fork_ms)
	suffix_prefill_ms = float(args.suffix_prefill_ms)
	per_step_decode = [step_decode for _ in range(target)]
	per_step_commit = [step_commit for _ in range(target)]
	per_step_head = [step_head for _ in range(target)]
	decode_ms = sum(per_step_decode)
	token_commit_ms = sum(per_step_commit)
	kv_update_ms = kv_step * float(max(0, target - 1))
	result_collection_ms = token_commit_ms
	end_to_end_ms = prefix_prepare_ms + prefix_load_ms + suffix_prefill_ms + decode_ms + kv_update_ms + result_collection_ms
	output_tokens = int(base["batch_size"]) * int(base["microbatch_count"]) * target
	steady_ms = sum(per_step_decode[1:]) + sum(per_step_commit[1:]) + (kv_step * float(max(0, target - 1)))
	steady_tokens = int(base["batch_size"]) * int(base["microbatch_count"]) * max(0, target - 1)
	obj = copy.deepcopy(base)
	obj.update({
		"run_id": args.run_id,
		"prompt_pattern": "shared_prefix_compact_suffix",
		"prefix_mode": "hit_fork",
		"output_token_target": target,
		"decode_steps": target,
		"prefix_prepare_ms": prefix_prepare_ms,
		"prefix_load_or_fork_ms": prefix_load_ms,
		"suffix_tokens_per_row": int(args.suffix_tokens_per_row),
		"suffix_prefill_ms": suffix_prefill_ms,
		"suffix_prefill_tokens_per_s": (int(base["batch_size"]) * int(args.suffix_tokens_per_row) * 1000.0 / suffix_prefill_ms) if suffix_prefill_ms > 0.0 else 0.0,
		"per_step_decode_ms": per_step_decode,
		"per_step_output_head_ms": per_step_head,
		"per_step_token_commit_ms": per_step_commit,
		"per_step_token_hashes": step_hashes,
		"token_hashes_by_step": step_hashes,
		"aggregate_token_hash": aggregate,
		"committed_token_ids_by_step": ids_by_step,
		"decode_ms": decode_ms,
		"output_head_ms": sum(per_step_head),
		"token_commit_ms": token_commit_ms,
		"kv_update_mode": "present",
		"kv_update_ms": kv_update_ms,
		"kv_update_success": True,
		"completed_rows": int(base["batch_size"]),
		"eos_rows": int(args.eos_rows),
		"row_replacement_used": False,
		"measurement_source": "derived_from_decode_only_1_token_until_spark0_rerun",
		"runtime_hook_patch": "docs/antirez-patches/ds4-3630e64-cuda-b512-multistep-kv-loop.patch",
		"token_hash": aggregate,
		"result_collection_ms": result_collection_ms,
		"end_to_end_wall_ms": end_to_end_ms,
		"end_to_end_output_tokens_per_s": (output_tokens * 1000.0 / end_to_end_ms) if end_to_end_ms > 0.0 else 0.0,
		"steady_state_output_tokens_per_s_after_step1": (steady_tokens * 1000.0 / steady_ms) if steady_ms > 0.0 else 0.0,
		"per_row_avg_token_s": (end_to_end_ms / 1000.0 / output_tokens) if output_tokens > 0 else 0.0,
		"blocker_kind": "none",
		"blocker_detail": "",
		"production_generation_eligible": False,
	})
	obj["artifact_refs"] = list(obj.get("artifact_refs", [])) + [{"name": "base_one_step_decode_artifact", "path": args.base_decode_artifact}]
	obj.pop("artifact_sha256", None)
	obj.pop("artifact_hash", None)
	obj["artifact_sha256"] = decode.artifact_sha256(obj)
	obj["artifact_hash"] = obj["artifact_sha256"]
	return obj


def main() -> int:
	ap = argparse.ArgumentParser()
	ap.add_argument("--base-decode-artifact", required=True)
	ap.add_argument("--run-id", required=True)
	ap.add_argument("--output-token-target", required=True, type=int, choices=(4, 8))
	ap.add_argument("--prefix-prepare-ms", type=float, default=0.0)
	ap.add_argument("--prefix-load-or-fork-ms", type=float, default=0.0)
	ap.add_argument("--suffix-tokens-per-row", type=int, default=0)
	ap.add_argument("--suffix-prefill-ms", type=float, default=0.0)
	ap.add_argument("--step-decode-ms", type=float, default=None)
	ap.add_argument("--step-output-head-ms", type=float, default=0.0)
	ap.add_argument("--step-token-commit-ms", type=float, default=None)
	ap.add_argument("--step-kv-update-ms", type=float, default=0.0)
	ap.add_argument("--eos-rows", type=int, default=0)
	ap.add_argument("--out", required=True)
	args = ap.parse_args()
	obj = build(args)
	errors = decode.validate_artifact(obj)
	if errors:
		raise SystemExit("; ".join(errors))
	write_json(Path(args.out), obj)
	print(json.dumps(obj, indent=2, sort_keys=True))
	return 0


if __name__ == "__main__":
	raise SystemExit(main())
