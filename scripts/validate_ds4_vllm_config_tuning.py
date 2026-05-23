#!/usr/bin/env python3
"""Validate DS4 vLLM config tuning artifacts."""

from __future__ import annotations

import argparse
import hashlib
import json
import sys
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from scripts._lib.json_utils import canonical_hash, load_json, make_validate_paths


FORMAT = "ds4-vllm-config-tuning-v1"


def default_paths() -> list[Path]:
	root = Path(__file__).resolve().parents[1]
	return(sorted((root / "fixtures" / "vllm_config_tuning").glob("*.example.json")))


def err(path: Path, msg: str) -> str:
	return(f"{path}: {msg}")


def load(path: Path) -> dict[str, Any]:
	return(load_json(path, "root JSON"))


def attempt_best_tps(attempt: dict[str, Any]) -> float:
	if attempt.get("safety_status") not in (None, "passed"):
		return(0.0)
	if attempt.get("startup_status") not in (None, "passed"):
		return(0.0)
	by_c = attempt.get("tokens_per_second_by_concurrency")
	if not isinstance(by_c, dict):
		return(0.0)
	vals = [float(v) for v in by_c.values() if isinstance(v, (int, float)) and not isinstance(v, bool)]
	return(max(vals) if vals else 0.0)


def selected_config_tps(selected: dict[str, Any], path: Path, errors: list[str]) -> float:
	c512 = selected.get("tokens_per_second_at_c512")
	if isinstance(c512, (int, float)) and not isinstance(c512, bool):
		return(float(c512))
	max_num_seqs = selected.get("max_num_seqs")
	c256 = selected.get("tokens_per_second_at_c256")
	if isinstance(max_num_seqs, int) and max_num_seqs < 512 and isinstance(c256, (int, float)) and not isinstance(c256, bool):
		return(float(c256))
	errors.append(err(path, "selected_config.tokens_per_second_at_c512 must be numeric unless max_num_seqs < 512 and tokens_per_second_at_c256 is numeric"))
	return(0.0)


def check_raw_artifact(root: Path, attempt: dict[str, Any], path: Path, errors: list[str]) -> None:
	raw = attempt.get("raw_artifact")
	expected = attempt.get("raw_artifact_sha256")
	if raw is None and expected is None:
		return
	if not isinstance(raw, str) or not isinstance(expected, str):
		errors.append(err(path, "raw_artifact and raw_artifact_sha256 must be strings when present"))
		return
	raw_path = root / raw
	if not raw_path.exists():
		errors.append(err(path, f"raw artifact missing: {raw}"))
		return
	actual = hashlib.sha256(raw_path.read_bytes()).hexdigest()
	if actual != expected:
		errors.append(err(path, f"raw artifact hash mismatch: {raw}"))


def validate(obj: dict[str, Any], path: Path) -> list[str]:
	errors: list[str] = []
	root = Path(__file__).resolve().parents[1]
	if obj.get("format") != FORMAT:
		errors.append(err(path, f"format must be {FORMAT}"))
	if obj.get("artifact_sha256") != canonical_hash(obj):
		errors.append(err(path, "artifact_sha256 does not match canonical hash"))
	attempts = obj.get("attempts")
	if not isinstance(attempts, list) or len(attempts) == 0:
		errors.append(err(path, "attempts must be a non-empty list"))
		attempts = []
	selected = obj.get("selected_config")
	conclusion = obj.get("conclusion")
	if not isinstance(selected, dict):
		errors.append(err(path, "selected_config must be an object"))
		selected = {}
	if not isinstance(conclusion, dict):
		errors.append(err(path, "conclusion must be an object"))
		conclusion = {}
	best_selected = selected_config_tps(selected,path,errors)
	attempt_best = 0.0
	for attempt in attempts:
		if not isinstance(attempt, dict):
			errors.append(err(path, "each attempt must be an object"))
			continue
		check_raw_artifact(root, attempt, path, errors)
		attempt_best = max(attempt_best, attempt_best_tps(attempt))
	if conclusion.get("improved_vllm_performance") is True and float(best_selected) < attempt_best:
		errors.append(err(path, "improved_vllm_performance requires selected speed at least matching the best measured attempt"))
	if conclusion.get("improved_vllm_performance") is False and float(best_selected) < attempt_best:
		errors.append(err(path, "selected config must not be slower than a rejected attempt"))
	return(errors)


validate_paths = make_validate_paths(validate, load)


def main() -> int:
	p = argparse.ArgumentParser(description=__doc__)
	p.add_argument("paths", nargs="*", type=Path)
	args = p.parse_args()
	paths = args.paths if args.paths else default_paths()
	result = validate_paths(paths)
	print(json.dumps(result, indent=2, sort_keys=True))
	return(0 if result["ok"] else 1)


if __name__ == "__main__":
	raise SystemExit(main())
