#!/usr/bin/env python3
"""Build ds4-mtp-benchmark-integrity-v1 from comparable DS4 MTP runs."""

from __future__ import annotations

import hashlib
import json
import sys
from argparse import ArgumentParser
from pathlib import Path
from typing import Any, Iterable, Optional

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from scripts import extract_antirez_ds4_mtp_conf_log as mtp_extract


FORMAT = "ds4-mtp-benchmark-integrity-v1"


def _iter_lines(paths: list[Path]) -> Iterable[str]:
	for path in paths:
		with path.open("r", encoding="utf-8", errors="replace") as f:
			for line in f:
				yield line.rstrip("\n")


def _float(raw: Any) -> Optional[float]:
	if raw is None:
		return None
	if isinstance(raw, (int, float)):
		return float(raw)
	try:
		return float(str(raw).strip())
	except (TypeError, ValueError):
		return None


def _int(raw: Any) -> Optional[int]:
	if raw is None:
		return None
	if isinstance(raw, int):
		return int(raw)
	if isinstance(raw, float) and float(int(raw)) == float(raw):
		return int(raw)
	try:
		return int(str(raw).strip(), 10)
	except (TypeError, ValueError):
		return None


def _prompt_hash(prompt: str, explicit_hash: str) -> str:
	if explicit_hash.strip() != "":
		return explicit_hash.strip()
	return hashlib.sha256(prompt.encode("utf-8")).hexdigest()


def _bench_value(obj: dict[str, Any], key: str) -> Any:
	for ev in reversed((((obj.get("benchmark") or {}).get("events")) or [])):
		if key in ev:
			return ev.get(key)
	return None


def _phase_report(paths: list[Path]) -> dict[str, Any]:
	obj = mtp_extract.extract_events(list(_iter_lines(paths)))
	speed = obj.get("speed") or {}
	totals = obj.get("totals") or {}
	return {
		"generation_tps": _float(speed.get("generation_tps")),
		"prefill_tps": _float(speed.get("prefill_tps")),
		"external_wall_s": _float(_bench_value(obj, "external_wall_s")),
		"exit_code": _int(_bench_value(obj, "exit_code")),
		"phase": _bench_value(obj, "phase"),
		"command_sha256": _bench_value(obj, "command_sha256"),
		"perf_env_sha256": _bench_value(obj, "perf_env_sha256"),
		"perf_env_keys": _bench_value(obj, "perf_env_keys"),
		"prompt_sha256": _bench_value(obj, "prompt_sha256"),
		"n_predict": _int(_bench_value(obj, "n_predict")),
		"mtp_draft": _int(_bench_value(obj, "mtp_draft")),
		"ctx": _int(_bench_value(obj, "ctx")),
		"seed": _int(_bench_value(obj, "seed")),
		"spec_disabled": _int(_bench_value(obj, "spec_disabled")),
		"accepted_draft_tokens": _int(totals.get("draft_tokens_accepted_est")) or 0,
		"attempted_draft_tokens": _int(totals.get("draft_tokens_attempted_est")) or 0,
	}


def build_report(
	baseline_paths: list[Path],
	mtp_paths: list[Path],
	*,
	run_id: str,
	model_id: str,
	runtime_id: str,
	prompt: str,
	prompt_hash: str,
	prior_argmax_baseline_tps: Optional[float],
) -> dict[str, Any]:
	base = _phase_report(baseline_paths)
	mtp = _phase_report(mtp_paths)
	same_prompt = base.get("prompt_sha256") is not None and base.get("prompt_sha256") == mtp.get("prompt_sha256")
	same_ctx = base.get("ctx") is not None and base.get("ctx") == mtp.get("ctx")
	same_seed = base.get("seed") is not None and base.get("seed") == mtp.get("seed")
	same_n_predict = base.get("n_predict") is not None and base.get("n_predict") == mtp.get("n_predict")
	same_mtp_draft = base.get("mtp_draft") is not None and base.get("mtp_draft") == mtp.get("mtp_draft")
	same_command_shape = base.get("command_sha256") is not None and base.get("command_sha256") == mtp.get("command_sha256")
	same_perf_env = base.get("perf_env_sha256") is not None and base.get("perf_env_sha256") == mtp.get("perf_env_sha256")
	baseline_spec_disabled = base.get("spec_disabled") == 1
	mtp_spec_enabled = mtp.get("spec_disabled") == 0
	same_cli_path = bool(same_prompt and same_ctx and same_seed and same_n_predict and same_mtp_draft and same_command_shape)
	base_tps = _float(base.get("generation_tps"))
	mtp_tps = _float(mtp.get("generation_tps"))
	speedup = (mtp_tps / base_tps) if base_tps is not None and mtp_tps is not None and base_tps > 0.0 else None
	prior_speedup = (
		(mtp_tps / prior_argmax_baseline_tps)
		if mtp_tps is not None and prior_argmax_baseline_tps is not None and prior_argmax_baseline_tps > 0.0
		else None
	)
	status = "comparable"
	blocker = ""
	if not baseline_spec_disabled:
		status = "blocked"
		blocker = "baseline control must run with DS4_MTP_SPEC_DISABLE=1 while still loading --mtp"
	elif not mtp_spec_enabled:
		status = "blocked"
		blocker = "MTP phase must run with speculation enabled"
	elif not same_cli_path:
		status = "blocked"
		blocker = "baseline and MTP phases must share prompt/context/seed/n_predict/mtp_draft/command shape"
	elif not same_perf_env:
		status = "blocked"
		blocker = "baseline and MTP phases must share performance-affecting environment shape"
	elif base_tps is None or mtp_tps is None:
		status = "blocked"
		blocker = "both phases must emit ds4 reported generation t/s"
	return {
		"format": FORMAT,
		"run_id": run_id,
		"model_id": model_id,
		"runtime_id": runtime_id,
		"prompt_hash": _prompt_hash(prompt, prompt_hash),
		"benchmark_status": status,
		"blocker_detail": blocker,
		"same_cli_path": same_cli_path,
		"same_prompt": same_prompt,
		"same_ctx": same_ctx,
		"same_seed": same_seed,
		"same_n_predict": same_n_predict,
		"same_mtp_draft": same_mtp_draft,
		"same_command_shape": same_command_shape,
		"same_perf_env": same_perf_env,
		"baseline_phase": base.get("phase"),
		"mtp_phase": mtp.get("phase"),
		"baseline_perf_env_sha256": base.get("perf_env_sha256"),
		"mtp_perf_env_sha256": mtp.get("perf_env_sha256"),
		"perf_env_keys": base.get("perf_env_keys") or mtp.get("perf_env_keys"),
		"baseline_spec_disabled": baseline_spec_disabled,
		"mtp_spec_enabled": mtp_spec_enabled,
		"baseline_reported_generation_tps": base_tps,
		"mtp_reported_generation_tps": mtp_tps,
		"speedup_vs_session_baseline": speedup,
		"prior_argmax_baseline_tps": prior_argmax_baseline_tps,
		"speedup_vs_prior_argmax_baseline": prior_speedup,
		"baseline_external_process_wall_s": base.get("external_wall_s"),
		"mtp_external_process_wall_s": mtp.get("external_wall_s"),
		"baseline_exit_code": base.get("exit_code"),
		"mtp_exit_code": mtp.get("exit_code"),
		"baseline_accepted_draft_tokens": base.get("accepted_draft_tokens"),
		"baseline_attempted_draft_tokens": base.get("attempted_draft_tokens"),
		"mtp_accepted_draft_tokens": mtp.get("accepted_draft_tokens"),
		"mtp_attempted_draft_tokens": mtp.get("attempted_draft_tokens"),
	}


def main(argv: Optional[list[str]] = None) -> int:
	ap = ArgumentParser()
	ap.add_argument("--baseline-log", action="append", default=[], required=True)
	ap.add_argument("--mtp-log", action="append", default=[], required=True)
	ap.add_argument("--run-id", required=True)
	ap.add_argument("--model-id", default="DeepSeek-V4-Flash-IQ2XXS-chat-v2")
	ap.add_argument("--runtime-id", default="antirez/ds4@3630e64+cuda-mtp")
	ap.add_argument("--prompt", default="")
	ap.add_argument("--prompt-hash", default="")
	ap.add_argument("--prior-argmax-baseline-tps", type=float, default=None)
	ap.add_argument("--out-json", default="")
	args = ap.parse_args(argv)
	report = build_report(
		[Path(p) for p in args.baseline_log],
		[Path(p) for p in args.mtp_log],
		run_id=str(args.run_id),
		model_id=str(args.model_id),
		runtime_id=str(args.runtime_id),
		prompt=str(args.prompt),
		prompt_hash=str(args.prompt_hash),
		prior_argmax_baseline_tps=args.prior_argmax_baseline_tps,
	)
	text = json.dumps(report, indent=2, sort_keys=True) + "\n"
	if str(args.out_json).strip() != "":
		Path(str(args.out_json)).write_text(text, encoding="utf-8")
	print(text, end="")
	return 0


if __name__ == "__main__":
	raise SystemExit(main())
