#!/usr/bin/env python3
"""Build a DS4 SGLang provider probe artifact from the local environment."""

from __future__ import annotations

import argparse
import importlib.metadata
import json
import os
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


def _sglang_version(override: str) -> tuple[str, str | None]:
    if override:
        return override, None if override != "not_installed" else "sglang_not_installed"
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
    python_executable = _python_executable(args)
    command = [
        python_executable,
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


def _python_executable(args: argparse.Namespace) -> str:
    if args.python_executable:
        return args.python_executable
    if args.target_host and args.target_host != "local":
        return "python3"
    return sys.executable


def _reachability_report(path_text: str) -> dict[str, Any] | None:
    if not path_text:
        return None
    path = Path(path_text)
    return json.loads(path.read_text(encoding="utf-8"))


def _blocker(args: argparse.Namespace, version_blocker: str | None, reachability: dict[str, Any] | None) -> tuple[str, str]:
    if args.blocker_kind_override:
        return args.blocker_kind_override, args.blocker_detail_override
    if reachability is not None and reachability.get("blocker_kind") != "none":
        return "host_unreachable", "Spark reachability report blocked SGLang launch: " + str(reachability.get("blocker_detail") or "")
    if version_blocker:
        return version_blocker, "Python package 'sglang' is not installed in this environment."
    if not Path(args.model_path).exists():
        return "model_checkpoint_missing", f"model path does not exist: {args.model_path}"
    if not args.allow_launch:
        return "launch_not_run_requires_explicit_allow_launch", "SGLang package and checkpoint are present, but launch was not attempted without --allow-launch."
    return "benchmark_not_run", "SGLang launch/benchmark execution is not implemented in this lightweight probe runner."


def _checkpoint_source(args: argparse.Namespace) -> dict[str, Any]:
    status = args.checkpoint_source_status
    if status == "auto":
        status = "available" if Path(args.model_path).exists() else "missing"
    detail = args.checkpoint_source_detail
    if not detail:
        if status == "available":
            detail = "checkpoint path exists"
        elif status == "missing":
            detail = f"checkpoint path does not exist: {args.model_path}"
        else:
            detail = "checkpoint acquisition was not completed"
    return {
        "kind": args.checkpoint_source_kind,
        "repo_id": args.checkpoint_source_repo_id or args.model_id,
        "local_path": args.model_path,
        "hf_token_present": bool(args.hf_token_present),
        "status": status,
        "detail": detail,
    }


def _api_health_status(args: argparse.Namespace, blocker_kind: str, blocker_detail: str) -> dict[str, Any]:
    if args.api_health_status_override:
        status = args.api_health_status_override
    elif blocker_kind == "none":
        status = "not_run"
    else:
        status = "blocked"
    error = args.api_health_error_override
    if not error and status in {"blocked", "failed"}:
        error = blocker_detail
    return {
        "status": status,
        "endpoint": args.api_health_endpoint,
        "http_status": None,
        "latency_ms": None,
        "output_token_count": None,
        "response_hash": None,
        "error": error,
    }


def _acquisition_attempts(args: argparse.Namespace) -> list[dict[str, Any]]:
    attempts = []
    for item in args.acquisition_attempt_json:
        attempts.append(json.loads(item))
    return attempts


def _reachability_report_ref(path_text: str) -> dict[str, str] | None:
    if not path_text:
        return None
    obj = _reachability_report(path_text)
    path = Path(path_text)
    return {
        "path": path_text,
        "sha256": str(obj.get("artifact_sha256", "")),
        "format": str(obj.get("format", "")),
    }


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
    sglang_version, version_blocker = _sglang_version(args.sglang_version_override)
    reachability = _reachability_report(args.reachability_report_path)
    blocker_kind, blocker_detail = _blocker(args, version_blocker, reachability)
    hf_token_present = bool(os.environ.get("HF_TOKEN") or os.environ.get("HUGGING_FACE_HUB_TOKEN"))
    if not args.hf_token_present:
        args.hf_token_present = hf_token_present
    probe = {
        "format": FORMAT,
        "run_id": args.run_id or f"sglang-probe-{int(time.time())}",
        "provider_id": args.provider_id,
        "model_id": args.model_id,
        "checkpoint_format": args.checkpoint_format,
        "checkpoint_source": _checkpoint_source(args),
        "runtime_id": args.runtime_id,
        "sglang_version": sglang_version,
        "hardware": json.loads(args.hardware_json) if args.hardware_json else _hardware(),
        "launch_command": _launch_command(args),
        "launch_environment": {
            "python_executable": _python_executable(args),
            "env_keys_checked": ["HF_TOKEN", "HUGGING_FACE_HUB_TOKEN"],
            "hf_token_present": bool(args.hf_token_present),
            "target_host": args.target_host,
        },
        "recipe": args.recipe,
        "mtp_enabled": bool(args.mtp_enabled),
        "mtp_settings": {"mode": "requested" if args.mtp_enabled else "disabled", "draft_tokens": args.mtp_draft_tokens if args.mtp_enabled else 0},
        "max_running_requests": int(args.max_running_requests),
        "tp_size": int(args.tp_size),
        "pp_size": int(args.pp_size),
        "dp_size": int(args.dp_size),
        "memory_used_gib": None,
        "load_success": blocker_kind == "none",
        "api_health_status": _api_health_status(args, blocker_kind, blocker_detail),
        "acquisition_attempts": _acquisition_attempts(args),
        "reachability_report_ref": _reachability_report_ref(args.reachability_report_path),
        "benchmark_results": _benchmark_results(blocker_kind, blocker_detail),
        "blocker_kind": blocker_kind,
        "blocker_detail": blocker_detail,
        "custom_ds4_comparison": {
            "custom_ds4_constrained_b512": {
                "summary": "custom DS4 constrained B512 class",
                "reference_tok_s_class": "620-650",
                "scope": "custom DS4 constrained output only; not transferable to SGLang",
            },
            "custom_ds4_full_vocab_b512": {
                "summary": "custom DS4 full-vocab B512 class",
                "reference_tok_s_class": "260",
                "scope": "custom DS4 full-vocab output only; compare after SGLang full-vocab artifact exists",
            },
            "custom_ds4_mtp_k2": {
                "summary": "custom DS4 MTP K=2 direct path",
                "scope": "measured separately; compare after SGLang MTP artifact exists",
            },
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
    parser.add_argument("--checkpoint-source-kind", choices=("huggingface", "local_path", "gguf_custom_path", "unknown"), default="huggingface")
    parser.add_argument("--checkpoint-source-repo-id", default="")
    parser.add_argument("--checkpoint-source-status", choices=("auto", "available", "blocked", "missing", "not_checked"), default="auto")
    parser.add_argument("--checkpoint-source-detail", default="")
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
    parser.add_argument("--python-executable", default="")
    parser.add_argument("--hf-token-present", action="store_true")
    parser.add_argument("--target-host", default="local")
    parser.add_argument("--sglang-version-override", default="")
    parser.add_argument("--hardware-json", default="")
    parser.add_argument("--blocker-kind-override", choices=("none", "sglang_not_installed", "model_checkpoint_missing", "missing_hf_token", "checkpoint_unavailable", "insufficient_disk", "insufficient_memory", "unsupported_gpu", "host_unreachable", "spark_reachability_blocked", "runtime_install_failed", "dependency_conflict", "launch_not_run_requires_explicit_allow_launch", "launch_failed", "api_health_failed", "benchmark_not_run", "unsupported_constrained_output", "other", "unknown"), default="")
    parser.add_argument("--blocker-detail-override", default="")
    parser.add_argument("--api-health-status-override", choices=("success", "failed", "blocked", "not_run"), default="")
    parser.add_argument("--api-health-error-override", default="")
    parser.add_argument("--api-health-endpoint", default="http://127.0.0.1:30000/v1/chat/completions")
    parser.add_argument("--acquisition-attempt-json", action="append", default=[])
    parser.add_argument("--reachability-report-path", default="")
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
