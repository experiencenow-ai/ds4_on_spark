#!/usr/bin/env python3

import json
import sys
from argparse import ArgumentParser
from pathlib import Path
from typing import Any, Optional


def die_json(errors: list[str], warnings: list[str]) -> int:
	out = {
		"ok": (len(errors) == 0),
		"errors": errors,
		"warnings": warnings,
	}
	print(json.dumps(out, indent=2, sort_keys=True))
	return 0 if out["ok"] else 1


def load_json(path: Path) -> Any:
	with path.open("r", encoding="utf-8") as f:
		return json.load(f)


def get_required(obj: dict[str, Any], key: str, errors: list[str]) -> Any:
	if key not in obj:
		errors.append(f"missing key: {key}")
		return None
	return obj[key]


def expect_type(key: str, val: Any, want: type, errors: list[str]) -> None:
	if val is None:
		return
	if not isinstance(val, want):
		errors.append(f"key {key} has type {type(val).__name__}, expected {want.__name__}")


def expect_number(key: str, val: Any, errors: list[str]) -> None:
	if val is None:
		return
	if not isinstance(val, (int, float)):
		errors.append(f"key {key} has type {type(val).__name__}, expected number")


def expect_int(key: str, val: Any, errors: list[str]) -> None:
	if val is None:
		return
	if not isinstance(val, int):
		errors.append(f"key {key} has type {type(val).__name__}, expected int")


def expect_bool(key: str, val: Any, errors: list[str]) -> None:
	if val is None:
		return
	if not isinstance(val, bool):
		errors.append(f"key {key} has type {type(val).__name__}, expected bool")


def expect_list(key: str, val: Any, errors: list[str]) -> None:
	if val is None:
		return
	if not isinstance(val, list):
		errors.append(f"key {key} has type {type(val).__name__}, expected list")


def get_dict(key: str, val: Any, errors: list[str]) -> Optional[dict[str, Any]]:
	if val is None:
		return None
	if not isinstance(val, dict):
		errors.append(f"key {key} has type {type(val).__name__}, expected object")
		return None
	return val


REQUIRED_MTP_PARAMS = [
	"n_embd",
	"n_head",
	"n_head_dim",
	"n_hc",
	"n_lora_q",
	"n_out_group",
	"n_lora_o",
	"n_expert",
	"n_ff_exp",
]


def main() -> int:
	parser = ArgumentParser()
	parser.add_argument("--probe-json", type=str, required=True, help="Path to one-token draft probe JSON output.")
	parser.add_argument(
		"--sidecar-probe-json",
		type=str,
		default=None,
		help="Optional path to scripts/model_contract_probe_mtp_sidecar.py --json output for cross-checking mtp_params.",
	)
	parser.add_argument("--json", action="store_true", help="Emit machine-readable JSON output.")
	args = parser.parse_args()

	errors: list[str] = []
	warnings: list[str] = []

	probe_path = Path(args.probe_json)
	probe = load_json(probe_path)
	if not isinstance(probe, dict):
		errors.append("probe-json top-level is not an object")
		if args.json:
			return die_json(errors, warnings)
		for e in errors:
			print(f"error: {e}")
		return 1

	for k in ("runtime_repo", "runtime_commit", "trunk_gguf_path", "mtp_sidecar_path"):
		expect_type(k, get_required(probe, k, errors), str, errors)

	if ("prompt" not in probe) and ("prompt_sha256" not in probe):
		errors.append("missing key: prompt (or prompt_sha256)")
	else:
		if "prompt" in probe:
			expect_type("prompt", probe.get("prompt", None), str, errors)
		if "prompt_sha256" in probe:
			expect_type("prompt_sha256", probe.get("prompt_sha256", None), str, errors)

	for k in ("seed", "verify_step_idx", "base_next_token_id", "mtp_draft_token_id"):
		expect_int(k, get_required(probe, k, errors), errors)
	expect_number("temperature", get_required(probe, "temperature", errors), errors)
	expect_int("top_k", get_required(probe, "top_k", errors), errors)
	expect_number("top_p", get_required(probe, "top_p", errors), errors)

	expect_type("base_next_token", probe.get("base_next_token", ""), str, errors)
	expect_type("mtp_draft_token", probe.get("mtp_draft_token", ""), str, errors)

	verify_step_idx = probe.get("verify_step_idx", None)
	if isinstance(verify_step_idx, int) and verify_step_idx != 0:
		errors.append(f"verify_step_idx is {verify_step_idx}, expected 0 for this probe")

	mtp_params = get_dict("mtp_params", get_required(probe, "mtp_params", errors), errors)
	if mtp_params is not None:
		for k in REQUIRED_MTP_PARAMS:
			expect_int(f"mtp_params.{k}", mtp_params.get(k, None), errors)
		extra = sorted(set(mtp_params.keys()) - set(REQUIRED_MTP_PARAMS))
		if extra:
			warnings.append(f"mtp_params contains extra keys: {extra}")

	expect_bool("ok", get_required(probe, "ok", errors), errors)
	err_list = get_required(probe, "errors", errors)
	expect_list("errors", err_list, errors)
	if isinstance(err_list, list):
		for i, v in enumerate(err_list[:256]):
			if not isinstance(v, str):
				errors.append(f"errors[{i}] has type {type(v).__name__}, expected str")

	if probe.get("temperature", None) not in (None, 0.0):
		warnings.append("temperature is not 0.0 (probe is intended to be deterministic)")
	top_k = probe.get("top_k", None)
	if isinstance(top_k, int) and top_k != 1:
		warnings.append(f"top_k is {top_k}, expected 1 for deterministic probe")
	top_p = probe.get("top_p", None)
	if isinstance(top_p, (int, float)) and float(top_p) != 1.0:
		warnings.append(f"top_p is {top_p}, expected 1.0 for deterministic probe")

	if args.sidecar_probe_json is not None and mtp_params is not None:
		sidecar = load_json(Path(args.sidecar_probe_json))
		if not isinstance(sidecar, dict):
			errors.append("sidecar-probe-json top-level is not an object")
		else:
			derived = sidecar.get("derived_params", None)
			if not isinstance(derived, dict):
				errors.append("sidecar-probe-json missing derived_params object")
			else:
				for k in REQUIRED_MTP_PARAMS:
					want = derived.get(k, None)
					got = mtp_params.get(k, None)
					if isinstance(want, int) and isinstance(got, int) and want != got:
						errors.append(f"mtp_params.{k}={got} does not match sidecar derived_params.{k}={want}")

	if args.json:
		return die_json(errors, warnings)

	for w in warnings[:64]:
		print(f"warning: {w}")
	for e in errors[:64]:
		print(f"error: {e}")
	print(f"ok: {str(len(errors) == 0).lower()}")
	return 0 if len(errors) == 0 else 1


if __name__ == "__main__":
	sys.exit(main())
