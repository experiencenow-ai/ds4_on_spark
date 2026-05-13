#!/usr/bin/env python3
"""Validate a batch wrapper emitted by llama-ds4-mtp-one-token-draft-probe --prompt-file."""

from __future__ import annotations

import json
from argparse import ArgumentParser
from pathlib import Path
from typing import Any

REQUIRED_MTP_PARAMS = ["n_embd", "n_head", "n_head_dim", "n_hc", "n_lora_q", "n_out_group", "n_lora_o", "n_expert", "n_ff_exp"]


def load_json(path: Path) -> Any:
	with path.open("r", encoding="utf-8") as f:
		return json.load(f)


def add_type_error(errors: list[str], key: str, val: Any, want: str) -> None:
	errors.append(f"key {key} has type {type(val).__name__}, expected {want}")


def expect_type(errors: list[str], obj: dict[str, Any], key: str, typ: type, prefix: str = "") -> None:
	full = f"{prefix}{key}"
	if key not in obj:
		errors.append(f"missing key: {full}")
		return
	if not isinstance(obj[key], typ):
		add_type_error(errors, full, obj[key], typ.__name__)


def expect_number(errors: list[str], obj: dict[str, Any], key: str, prefix: str = "") -> None:
	full = f"{prefix}{key}"
	if key not in obj:
		errors.append(f"missing key: {full}")
		return
	if not isinstance(obj[key], (int, float)):
		add_type_error(errors, full, obj[key], "number")


def validate_one_probe(obj: Any, prefix: str) -> tuple[list[str], list[str]]:
	errors: list[str] = []
	warnings: list[str] = []
	if not isinstance(obj, dict):
		return [f"{prefix} is not an object"], warnings
	for key in ("runtime_repo", "runtime_commit", "trunk_gguf_path", "mtp_sidecar_path"):
		expect_type(errors, obj, key, str, prefix)
	if "prompt" not in obj and "prompt_sha256" not in obj:
		errors.append(f"missing key: {prefix}prompt (or prompt_sha256)")
	else:
		if "prompt" in obj and not isinstance(obj.get("prompt"), str):
			add_type_error(errors, f"{prefix}prompt", obj.get("prompt"), "str")
		if "prompt_sha256" in obj and not isinstance(obj.get("prompt_sha256"), str):
			add_type_error(errors, f"{prefix}prompt_sha256", obj.get("prompt_sha256"), "str")
	for key in ("seed", "verify_step_idx", "base_next_token_id", "mtp_draft_token_id", "top_k"):
		expect_type(errors, obj, key, int, prefix)
	expect_number(errors, obj, "temperature", prefix)
	expect_number(errors, obj, "top_p", prefix)
	for key in ("base_next_token", "mtp_draft_token"):
		if key in obj and not isinstance(obj[key], str):
			add_type_error(errors, f"{prefix}{key}", obj[key], "str")
	mtp_params = obj.get("mtp_params")
	if not isinstance(mtp_params, dict):
		errors.append(f"key {prefix}mtp_params has type {type(mtp_params).__name__}, expected object")
	else:
		for key in REQUIRED_MTP_PARAMS:
			if not isinstance(mtp_params.get(key), int):
				errors.append(f"key {prefix}mtp_params.{key} has type {type(mtp_params.get(key)).__name__}, expected int")
	expect_type(errors, obj, "ok", bool, prefix)
	err_list = obj.get("errors")
	if not isinstance(err_list, list):
		errors.append(f"key {prefix}errors has type {type(err_list).__name__}, expected list")
	else:
		for i, val in enumerate(err_list[:256]):
			if not isinstance(val, str):
				errors.append(f"key {prefix}errors[{i}] has type {type(val).__name__}, expected str")
	if isinstance(obj.get("verify_step_idx"), int) and obj.get("verify_step_idx") != 0:
		errors.append(f"{prefix}verify_step_idx is {obj.get('verify_step_idx')}, expected 0")
	if isinstance(obj.get("temperature"), (int, float)) and float(obj.get("temperature")) != 0.0:
		warnings.append(f"{prefix}temperature is not 0.0")
	if isinstance(obj.get("top_k"), int) and int(obj.get("top_k")) != 1:
		warnings.append(f"{prefix}top_k is not 1")
	if isinstance(obj.get("top_p"), (int, float)) and float(obj.get("top_p")) != 1.0:
		warnings.append(f"{prefix}top_p is not 1.0")
	return errors, warnings


def validate_batch(obj: Any) -> dict[str, Any]:
	errors: list[str] = []
	warnings: list[str] = []
	if not isinstance(obj, dict):
		return {"ok": False, "errors": ["batch-json top-level is not an object"], "warnings": []}
	for key in ("runtime_repo", "runtime_commit", "trunk_gguf_path", "mtp_sidecar_path", "prompt_file_path"):
		expect_type(errors, obj, key, str)
	expect_type(errors, obj, "seed", int)
	expect_type(errors, obj, "result_count", int)
	expect_type(errors, obj, "ok", bool)
	if not isinstance(obj.get("errors"), list):
		errors.append(f"key errors has type {type(obj.get('errors')).__name__}, expected list")
	results = obj.get("results")
	if not isinstance(results, list):
		errors.append(f"key results has type {type(results).__name__}, expected list")
	else:
		if isinstance(obj.get("result_count"), int) and obj.get("result_count") != len(results):
			errors.append(f"result_count={obj.get('result_count')} does not match len(results)={len(results)}")
		for i, item in enumerate(results):
			e, w = validate_one_probe(item, f"results[{i}].")
			errors.extend(e)
			warnings.extend(w)
	return {"ok": len(errors) == 0, "errors": errors, "warnings": warnings}


def main(argv: list[str] | None = None) -> int:
	ap = ArgumentParser()
	ap.add_argument("--batch-json", required=True, help="Batch probe JSON wrapper.")
	ap.add_argument("--json", action="store_true", help="Emit machine-readable JSON.")
	args = ap.parse_args(argv)
	result = validate_batch(load_json(Path(args.batch_json)))
	if args.json:
		print(json.dumps(result, indent=2, sort_keys=True))
	else:
		for w in result["warnings"][:64]:
			print(f"warning: {w}")
		for e in result["errors"][:64]:
			print(f"error: {e}")
		print(f"ok: {str(bool(result['ok'])).lower()}")
	return 0 if result["ok"] else 1


if __name__ == "__main__":
	raise SystemExit(main())
