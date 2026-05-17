#!/usr/bin/env python3
"""Build fixture benchmark/profile records for standard local runtimes."""

from __future__ import annotations

import argparse
import copy
import hashlib
import importlib.metadata
import json
import platform
import shutil
from pathlib import Path
from typing import Any


BENCHMARK_FORMAT = "centaur-standard-runtime-model-benchmark-v1"
PROFILE_FORMAT = "centaur-model-provider-profile-v1"


def canonical_hash(obj: dict[str, Any], hash_field: str = "artifact_sha256") -> str:
    payload = copy.deepcopy(obj)
    payload.pop(hash_field, None)
    data = json.dumps(payload, sort_keys=True, separators=(",", ":"), ensure_ascii=True).encode("utf-8")
    return hashlib.sha256(data).hexdigest()


def safe_version(package: str) -> str:
    try:
        return importlib.metadata.version(package)
    except importlib.metadata.PackageNotFoundError:
        return ""


def local_hardware() -> dict[str, Any]:
    return {
        "system": platform.system(),
        "machine": platform.machine(),
        "processor": platform.processor(),
        "note": "Fixture builder records host class only; no live benchmark was run.",
    }


def base_benchmark(case: dict[str, Any], hardware: dict[str, Any]) -> dict[str, Any]:
    obj = {
        "format": BENCHMARK_FORMAT,
        "artifact_sha256": "",
        "benchmark_id": case["benchmark_id"],
        "provider_id": case["provider_id"],
        "model_id": case["model_id"],
        "model_family": case["model_family"],
        "runtime": case["runtime"],
        "runtime_version": case["runtime_version"],
        "model_format": case["model_format"],
        "quantization": case["quantization"],
        "hardware": hardware,
        "launch_command": case.get("launch_command", ""),
        "api_endpoint": case.get("api_endpoint", ""),
        "context_length": case.get("context_length", 0),
        "mtp_supported": case.get("mtp_supported", False),
        "mtp_enabled": case.get("mtp_enabled", False),
        "speculative_config": case.get("speculative_config", {}),
        "ngram_spec_enabled": case.get("ngram_spec_enabled", False),
        "batch_size": case.get("batch_size", 1),
        "prompt_shape": case["prompt_shape"],
        "output_mode": case.get("output_mode", "full_vocab"),
        "tokens_per_second": None,
        "time_to_first_token_ms": None,
        "prompt_processing_tokens_per_second": None,
        "memory_used_gib": None,
        "parse_valid": False,
        "task_quality_score": None,
        "blocker_kind": case["blocker_kind"],
        "blocker_detail": case["blocker_detail"],
        "task_class": case["task_class"],
        "benchmark_status": "blocked",
        "live_routing_eligible": False,
        "structured_output_semantics": case.get("structured_output_semantics", "not_applicable"),
        "notes": case.get("notes", []),
    }
    obj["artifact_sha256"] = canonical_hash(obj)
    return obj


def profile_obj(case: dict[str, Any], fixture_path: str) -> dict[str, Any]:
    return {
        "format": PROFILE_FORMAT,
        "provider_id": case["provider_id"],
        "tier": case["tier"],
        "model_id": case["model_id"],
        "runtime": case["runtime"],
        "endpoint": case["endpoint"],
        "node_ids": [],
        "provider_kind": case["provider_kind"],
        "supported_lanes": case["supported_lanes"],
        "preferred_batch_tokens": case["preferred_batch_tokens"],
        "minimum_batch_tokens": case["minimum_batch_tokens"],
        "maximum_wait_ms": case["maximum_wait_ms"],
        "measured_input_tps": None,
        "measured_output_tps": None,
        "quality_scores": {
            "structured_classification": None,
            "dry_route_id": None,
            "routine_code_explanation": None,
            "small_code_patch_plan": None,
            "judge_reviewer_decision": None,
            "free_form_chat": None,
        },
        "last_probe_artifact": fixture_path,
        "production_eligible": False,
        "blocked_reason": case["blocked_reason"],
        "benchmark_refs": [fixture_path],
    }


def detected_cases() -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    llama_cli = shutil.which("llama-cli")
    llama_server = shutil.which("llama-server")
    sglang_version = safe_version("sglang")
    hardware = local_hardware()
    llama_detail = "llama-cli and llama-server were not found on PATH; no standard-runtime GGUF benchmark was run."
    if llama_cli or llama_server:
        llama_detail = "llama.cpp binary was found, but no real local GGUF model path was configured for this fixture run."
    sglang_detail = "SGLang Python package is not installed in this environment; no SGLang endpoint was launched."
    if sglang_version:
        sglang_detail = "SGLang is installed, but no DeepSeek/Ling/Qwen checkpoint path was configured for this fixture run."
    cases = [
        {
            "benchmark_id": "llama-cpp-qwen-coder-gguf-baseline-blocked",
            "provider_id": "standard-llama-cpp-qwen-coder-gguf",
            "model_id": "qwen-coder-gguf-candidate",
            "model_family": "qwen_coder",
            "runtime": "llama_cpp",
            "runtime_version": "",
            "model_format": "gguf",
            "quantization": "unknown",
            "context_length": 0,
            "batch_size": 1,
            "prompt_shape": "b1_free_form_chat_and_short_coding",
            "task_class": "routine_code_explanation",
            "blocker_kind": "runtime_install_blocked" if not (llama_cli or llama_server) else "model_unavailable",
            "blocker_detail": llama_detail,
            "launch_command": "llama-cli --model <model.gguf> --prompt <fixture>",
            "notes": ["No custom DS4 runtime was used.", "No frontier API was called."],
        },
        {
            "benchmark_id": "llama-cpp-qwen-mtp-gguf-blocked",
            "provider_id": "standard-llama-cpp-qwen-mtp-gguf",
            "model_id": "qwen-mtp-gguf-candidate",
            "model_family": "qwen_mtp",
            "runtime": "llama_cpp",
            "runtime_version": "",
            "model_format": "gguf",
            "quantization": "unknown",
            "context_length": 0,
            "batch_size": 1,
            "prompt_shape": "b1_free_form_chat_mtp_probe",
            "task_class": "free_form_chat",
            "mtp_supported": False,
            "mtp_enabled": False,
            "speculative_config": {"requested": "draft-mtp", "draft_max": [2, 3], "status": "not_run"},
            "blocker_kind": "runtime_install_blocked" if not (llama_cli or llama_server) else "mtp_heads_unavailable",
            "blocker_detail": llama_detail if not (llama_cli or llama_server) else "No configured local GGUF model with verified MTP heads was available.",
            "launch_command": "llama-cli --model <mtp-model.gguf> --spec-type draft-mtp --draft-max 2",
        },
        {
            "benchmark_id": "llama-cpp-devstral-small-gguf-blocked",
            "provider_id": "standard-llama-cpp-devstral-small-gguf",
            "model_id": "devstral-small-gguf-candidate",
            "model_family": "devstral",
            "runtime": "llama_cpp",
            "runtime_version": "",
            "model_format": "gguf",
            "quantization": "unknown",
            "context_length": 0,
            "batch_size": 1,
            "prompt_shape": "b1_short_code_patch_plan",
            "task_class": "small_code_patch_plan",
            "blocker_kind": "runtime_install_blocked" if not (llama_cli or llama_server) else "model_unavailable",
            "blocker_detail": llama_detail if not (llama_cli or llama_server) else "No configured local Devstral GGUF model was available.",
            "launch_command": "llama-cli --model <devstral-small.gguf> --prompt <fixture>",
        },
        {
            "benchmark_id": "sglang-ling-flash-standard-blocked",
            "provider_id": "standard-sglang-ling-flash",
            "model_id": "ling-2.6-flash-candidate",
            "model_family": "ling_flash",
            "runtime": "sglang",
            "runtime_version": sglang_version,
            "model_format": "hf",
            "quantization": "unknown",
            "context_length": 0,
            "batch_size": 4,
            "prompt_shape": "b4_independent_full_vocab_rows",
            "task_class": "free_form_chat",
            "blocker_kind": "runtime_install_blocked" if not sglang_version else "model_unavailable",
            "blocker_detail": sglang_detail,
            "launch_command": "python -m sglang.launch_server --model-path <hf-checkpoint>",
            "api_endpoint": "http://127.0.0.1:<port>/v1",
        },
        {
            "benchmark_id": "sglang-structured-output-semantics-blocked",
            "provider_id": "standard-sglang-structured-output",
            "model_id": "sglang-structured-output-candidate",
            "model_family": "mixed_local",
            "runtime": "sglang",
            "runtime_version": sglang_version,
            "model_format": "hf",
            "quantization": "unknown",
            "context_length": 0,
            "batch_size": 16,
            "prompt_shape": "structured_classification",
            "task_class": "structured_classification",
            "output_mode": "grammar_masked",
            "structured_output_semantics": "full_vocab_plus_mask_or_unknown",
            "blocker_kind": "structured_output_not_candidate_only",
            "blocker_detail": "No SGLang artifact proves candidate-only constrained scoring; grammar or mask support must not be labeled constrained-fast.",
            "launch_command": "python -m sglang.launch_server --model-path <hf-checkpoint>",
            "api_endpoint": "http://127.0.0.1:<port>/v1",
        },
        {
            "benchmark_id": "local-small-openai-compatible-blocked",
            "provider_id": "standard-local-small-openai-compatible",
            "model_id": "local-small-classifier-candidate",
            "model_family": "local_small",
            "runtime": "local_openai_compatible",
            "runtime_version": "",
            "model_format": "other",
            "quantization": "unknown",
            "context_length": 0,
            "batch_size": 1,
            "prompt_shape": "short_classification",
            "task_class": "structured_classification",
            "blocker_kind": "endpoint_unavailable",
            "blocker_detail": "No local OpenAI-compatible endpoint was configured for this fixture run.",
            "api_endpoint": "${CENTAUR_LOCAL_OPENAI_BASE_URL}",
        },
    ]
    profiles = [
        {
            "provider_id": "standard-llama-cpp-qwen-coder-gguf",
            "model_id": "qwen-coder-gguf-candidate",
            "runtime": "llama_cpp",
            "tier": "local_coder",
            "endpoint": {"kind": "local_binary", "binary": llama_cli or llama_server or "", "status": "blocked"},
            "provider_kind": "independent_lane",
            "supported_lanes": ["routine_code_explanation", "small_code_patch_plan", "judge_reviewer_decision", "free_form_chat"],
            "preferred_batch_tokens": 1,
            "minimum_batch_tokens": 1,
            "maximum_wait_ms": 0,
            "blocked_reason": "No live llama.cpp benchmark artifact is available.",
            "fixture": "fixtures/standard_runtime_benchmarks/llama_cpp_qwen_coder_gguf_baseline_blocked.example.json",
        },
        {
            "provider_id": "standard-sglang-ling-flash",
            "model_id": "ling-2.6-flash-candidate",
            "runtime": "sglang",
            "tier": "near_frontier_local",
            "endpoint": {"kind": "openai_compatible_endpoint", "url": "http://127.0.0.1:<port>/v1", "status": "blocked"},
            "provider_kind": "openai_compatible_endpoint",
            "supported_lanes": ["free_form_chat", "routine_code_explanation", "small_code_patch_plan"],
            "preferred_batch_tokens": 4,
            "minimum_batch_tokens": 1,
            "maximum_wait_ms": 50,
            "blocked_reason": "No live SGLang launch or benchmark artifact is available.",
            "fixture": "fixtures/standard_runtime_benchmarks/sglang_ling_flash_standard_blocked.example.json",
        },
        {
            "provider_id": "standard-llama-cpp-devstral-small-gguf",
            "model_id": "devstral-small-gguf-candidate",
            "runtime": "llama_cpp",
            "tier": "local_coder",
            "endpoint": {"kind": "local_binary", "binary": llama_cli or llama_server or "", "status": "blocked"},
            "provider_kind": "independent_lane",
            "supported_lanes": ["routine_code_explanation", "small_code_patch_plan", "judge_reviewer_decision"],
            "preferred_batch_tokens": 1,
            "minimum_batch_tokens": 1,
            "maximum_wait_ms": 0,
            "blocked_reason": "No live Devstral llama.cpp benchmark artifact is available.",
            "fixture": "fixtures/standard_runtime_benchmarks/llama_cpp_devstral_small_gguf_blocked.example.json",
        },
        {
            "provider_id": "standard-local-small-openai-compatible",
            "model_id": "local-small-classifier-candidate",
            "runtime": "local_openai_compatible",
            "tier": "local_small",
            "endpoint": {"kind": "openai_compatible_endpoint", "url_env": "CENTAUR_LOCAL_OPENAI_BASE_URL", "status": "blocked"},
            "provider_kind": "openai_compatible_endpoint",
            "supported_lanes": ["structured_classification", "dry_route_id", "candidate_prefilter"],
            "preferred_batch_tokens": 1,
            "minimum_batch_tokens": 1,
            "maximum_wait_ms": 10,
            "blocked_reason": "No local OpenAI-compatible endpoint was configured for this fixture run.",
            "fixture": "fixtures/standard_runtime_benchmarks/local_small_openai_compatible_blocked.example.json",
        },
    ]
    benchmarks = [base_benchmark(case, hardware) for case in cases]
    return benchmarks, profiles


def write_json(path: Path, obj: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(obj, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def main() -> int:
    parser = argparse.ArgumentParser(description="Build standard-runtime benchmark/profile fixture records.")
    parser.add_argument("--benchmark-dir", default="fixtures/standard_runtime_benchmarks", help="Directory for benchmark artifacts.")
    parser.add_argument("--profile-dir", default="fixtures/model_providers", help="Directory for provider profile artifacts.")
    args = parser.parse_args()
    root = Path.cwd()
    benchmark_dir = root / args.benchmark_dir
    profile_dir = root / args.profile_dir
    benchmarks, profile_cases = detected_cases()
    name_map = {
        "llama-cpp-qwen-coder-gguf-baseline-blocked": "llama_cpp_qwen_coder_gguf_baseline_blocked.example.json",
        "llama-cpp-qwen-mtp-gguf-blocked": "llama_cpp_qwen_mtp_gguf_blocked.example.json",
        "llama-cpp-devstral-small-gguf-blocked": "llama_cpp_devstral_small_gguf_blocked.example.json",
        "sglang-ling-flash-standard-blocked": "sglang_ling_flash_standard_blocked.example.json",
        "sglang-structured-output-semantics-blocked": "sglang_structured_output_semantics_blocked.example.json",
        "local-small-openai-compatible-blocked": "local_small_openai_compatible_blocked.example.json",
    }
    for item in benchmarks:
        write_json(benchmark_dir / name_map[item["benchmark_id"]], item)
    for case in profile_cases:
        fixture_path = case.pop("fixture")
        profile = profile_obj(case, fixture_path)
        profile_name = case["provider_id"].replace("-", "_") + ".example.json"
        write_json(profile_dir / profile_name, profile)
    print(f"wrote {len(benchmarks)} benchmark fixture(s) and {len(profile_cases)} provider profile(s)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
