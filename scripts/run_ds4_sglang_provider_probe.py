#!/usr/bin/env python3
"""Build a DS4 SGLang provider probe artifact from the local environment."""

from __future__ import annotations

import argparse
import importlib.metadata
import json
import platform
import subprocess
import sys
import time
from pathlib import Path
from typing import Any

try:
    from validate_ds4_sglang_provider_probe import artifact_sha256
    from validate_ds4_sglang_provider_probe import validate_probe
except ModuleNotFoundError:
    from scripts.validate_ds4_sglang_provider_probe import artifact_sha256
    from scripts.validate_ds4_sglang_provider_probe import validate_probe


FORMAT = "ds4-sglang-provider-probe-v1"
CASE_DEFS = (
    ("b1_full_vocab_chat", 1, "full_vocab", "balanced", False),
    ("b4_q_numbered_full_vocab_rows", 4, "full_vocab", "balanced", False),
    ("b16_full_vocab_rows", 16, "full_vocab", "balanced", False),
    ("b512_full_vocab_one_token", 512, "full_vocab", "max_throughput", False),
    ("b512_constrained_structured_output", 512, "constrained_structured", "max_throughput", False),
    ("mtp_low_latency", 1, "full_vocab", "low_latency", True),
    ("mtp_balanced", 4, "full_vocab", "balanced", True),
    ("max_throughput_mtp_disabled", 512, "full_vocab", "max_throughput", False),
)


def _sglang_version() -> tuple[str, str | None]:
    try:
        return importlib.metadata.version("sglang"), None
    except importlib.metadata.PackageNotFoundError:
        return "not_installed", "sglang_not_installed"


def _hardware() -> dict[str, Any]:
    hardware: dict[str, Any] = {
        "platform": platform.platform(),
        "machine": platform.machine(),
        "python": platform.python_version(),
        "gpus": [],
    }
    try:
        proc = subprocess.run(
            ["nvidia-smi", "--query-gpu=name,memory.total", "--format=csv,noheader,nounits"],
            check=False,
            text=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            timeout=3,
        )
    except (OSError, subprocess.TimeoutExpired):
        return hardware
    if proc.returncode == 0:
        for line in proc.stdout.splitlines():
            parts = [part.strip() for part in line.split(",", 1)]
            if len(parts) == 2:
                hardware["gpus"].append({"name": parts[0], "memory_total_mib": parts[1]})
    return hardware


def _launch_command(args: argparse.Namespace) -> list[str]:
    command = [
        sys.executable,
        "-m",
        "sglang.launch_server",
        "--model-path",
        args.model_path,
        "--served-model-name",
        args.model_id,
        "--tp-size",
        str(args.tp_size),
        "--pp-size",
        str(args.pp_size),
        "--dp-size",
        str(args.dp_size),
        "--max-running-requests",
        str(args.max_running_requests),
    ]
    if args.recipe == "low_latency":
        command.extend(["--schedule-policy", "lpm"])
    if args.mtp_enabled:
        command.append("--enable-mtp")
    return command


def _blocker(args: argparse.Namespace, version_blocker: str | None) -> tuple[str, str]:
    if version_blocker:
        return version_blocker, "Python package 'sglang' is not installed in this environment."
    if not Path(args.model_path).exists():
        return "model_checkpoint_missing", f"model path does not exist: {args.model_path}"
    if not args.allow_launch:
        return "launch_not_run_requires_explicit_allow_launch", "SGLang package and checkpoint are present, but launch was not attempted without --allow-launch."
    return "benchmark_not_run", "SGLang launch/benchmark execution is not implemented in this lightweight probe runner."


def _benchmark_results(blocker_kind: str, blocker_detail: str) -> list[dict[str, Any]]:
    rows = []
    for case_id, batch_size, output_mode, recipe, mtp_enabled in CASE_DEFS:
        constrained_scoring = "unknown" if output_mode == "constrained_structured" else "unsupported"
        case_blocker = blocker_kind
        case_detail = blocker_detail
        status = "blocked"
        if case_id == "b512_constrained_structured_output" and blocker_kind == "none":
            status = "unsupported"
            case_blocker = "unsupported_constrained_output"
            case_detail = "SGLang constrained/structured output scoring mode has not been proven candidate-only or equivalent."
        rows.append(
            {
                "case_id": case_id,
                "batch_size": batch_size,
                "output_mode": output_mode,
                "recipe": recipe,
                "mtp_enabled": mtp_enabled,
                "status": status,
                "tokens_per_second": None,
                "latency_ms": None,
                "constrained_scoring": constrained_scoring,
                "custom_ds4_speedup_inferred": False,
                "blocker_kind": case_blocker,
                "blocker_detail": case_detail,
            }
        )
    return rows


def build_probe(args: argparse.Namespace) -> dict[str, Any]:
    sglang_version, version_blocker = _sglang_version()
    blocker_kind, blocker_detail = _blocker(args, version_blocker)
    probe = {
        "format": FORMAT,
        "run_id": args.run_id or f"sglang-probe-{int(time.time())}",
        "provider_id": args.provider_id,
        "model_id": args.model_id,
        "checkpoint_format": args.checkpoint_format,
        "runtime_id": args.runtime_id,
        "sglang_version": sglang_version,
        "hardware": _hardware(),
        "launch_command": _launch_command(args),
        "recipe": args.recipe,
        "mtp_enabled": bool(args.mtp_enabled),
        "mtp_settings": {"mode": "requested" if args.mtp_enabled else "disabled", "draft_tokens": args.mtp_draft_tokens if args.mtp_enabled else 0},
        "max_running_requests": int(args.max_running_requests),
        "tp_size": int(args.tp_size),
        "pp_size": int(args.pp_size),
        "dp_size": int(args.dp_size),
        "memory_used_gib": None,
        "load_success": blocker_kind == "none",
        "benchmark_results": _benchmark_results(blocker_kind, blocker_detail),
        "blocker_kind": blocker_kind,
        "blocker_detail": blocker_detail,
        "custom_ds4_comparison": {
            "custom_constrained_b512_tok_s_class": "620-650",
            "custom_full_vocab_b512_tok_s_class": "260",
            "custom_mtp_k2_direct_path": "measured separately; compare only after SGLang MTP artifact exists",
        },
        "recommendation": "blocked" if blocker_kind != "none" else "retest",
    }
    probe["artifact_sha256"] = artifact_sha256(probe)
    probe["artifact_hash"] = probe["artifact_sha256"]
    return probe


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--out", required=True)
    parser.add_argument("--run-id", default="")
    parser.add_argument("--provider-id", default="sglang-ds4-local")
    parser.add_argument("--model-id", default="deepseek-ai/DeepSeek-V4-Flash")
    parser.add_argument("--checkpoint-format", default="huggingface")
    parser.add_argument("--runtime-id", default="sglang-local-probe")
    parser.add_argument("--model-path", default="/models/deepseek-v4-flash")
    parser.add_argument("--recipe", choices=("low_latency", "balanced", "max_throughput", "custom"), default="custom")
    parser.add_argument("--mtp-enabled", action="store_true")
    parser.add_argument("--mtp-draft-tokens", type=int, default=2)
    parser.add_argument("--max-running-requests", type=int, default=512)
    parser.add_argument("--tp-size", type=int, default=1)
    parser.add_argument("--pp-size", type=int, default=1)
    parser.add_argument("--dp-size", type=int, default=1)
    parser.add_argument("--allow-launch", action="store_true")
    args = parser.parse_args()
    probe = build_probe(args)
    errors = validate_probe(probe)
    if errors:
        for error in errors:
            print(f"error: {error}", file=sys.stderr)
        return 1
    out = Path(args.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(probe, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(json.dumps(probe, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
