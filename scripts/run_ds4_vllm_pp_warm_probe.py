#!/usr/bin/env python3
"""Run a PP vLLM warmup/measurement decode probe and emit JSON."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import time
import traceback
from pathlib import Path
from typing import Any


def sha256_text(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def write_artifact(path: str | None, artifact: dict[str, Any]) -> None:
    data = json.dumps(artifact, indent=2, sort_keys=True) + "\n"
    if path:
        Path(path).write_text(data, encoding="utf-8")
    print(data, flush=True)


def collect_batch_ids(outputs: Any) -> list[list[int]]:
    token_ids: list[list[int]] = []
    for output in outputs or []:
        if output.outputs:
            raw_ids = getattr(output.outputs[0], "token_ids", []) or []
            token_ids.append([int(x) for x in raw_ids])
        else:
            token_ids.append([])
    return token_ids


def flatten_ids(batch_ids: list[list[int]]) -> list[int]:
    return [token_id for row in batch_ids for token_id in row]


def make_prompts(prompt: str, batch_size: int, *, unique_prompts: bool) -> list[str]:
    if batch_size <= 1:
        return [prompt]
    if not unique_prompts:
        return [prompt for _ in range(batch_size)]
    return [f"{prompt}\nRow: {idx}" for idx in range(batch_size)]


def tps_for_tokens(token_count: int, seconds: float) -> float:
    if seconds <= 0.0:
        return 0.0
    return token_count / seconds


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--model", required=True)
    parser.add_argument("--pipeline-parallel-size", type=int, required=True)
    parser.add_argument("--tensor-parallel-size", type=int, default=1)
    parser.add_argument("--prompt", default="Explain Redis streams in one paragraph.")
    parser.add_argument("--warm-tokens", type=int, default=1)
    parser.add_argument("--measure-tokens", type=int, default=8)
    parser.add_argument("--measure-iterations", type=int, default=1)
    parser.add_argument("--batch-size", type=int, default=1)
    parser.add_argument("--shared-prompt", action="store_true")
    parser.add_argument("--max-model-len", type=int, default=64)
    parser.add_argument("--max-num-seqs", type=int, default=1)
    parser.add_argument("--max-num-batched-tokens", type=int, default=64)
    parser.add_argument("--gpu-memory-utilization", type=float, default=0.65)
    parser.add_argument("--kv-cache-dtype", default="fp8")
    parser.add_argument("--enforce-eager", action="store_true")
    parser.add_argument("--enable-auto-functionalized-v2", action="store_true")
    parser.add_argument("--compile-mode-none", action="store_true")
    parser.add_argument("--cudagraph-mode")
    parser.add_argument("--enable-expert-parallel", action="store_true")
    parser.add_argument("--moe-backend")
    parser.add_argument("--output")
    args = parser.parse_args()

    artifact: dict[str, Any] = {
        "format": "ds4-vllm-pp-warm-runtime-probe-v1",
        "status": "started",
        "utc_start": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "model": args.model,
        "prompt_sha256": sha256_text(args.prompt),
        "pipeline_parallel_size": args.pipeline_parallel_size,
        "tensor_parallel_size": args.tensor_parallel_size,
        "warm_tokens": args.warm_tokens,
        "measure_tokens": args.measure_tokens,
        "measure_iterations": args.measure_iterations,
        "batch_size": args.batch_size,
        "shared_prompt": args.shared_prompt,
        "max_model_len": args.max_model_len,
        "max_num_seqs": args.max_num_seqs,
        "max_num_batched_tokens": args.max_num_batched_tokens,
        "gpu_memory_utilization": args.gpu_memory_utilization,
        "kv_cache_dtype": args.kv_cache_dtype,
        "enforce_eager": args.enforce_eager,
        "enable_auto_functionalized_v2": args.enable_auto_functionalized_v2,
        "compile_mode_none": args.compile_mode_none,
        "cudagraph_mode": args.cudagraph_mode,
        "enable_expert_parallel": args.enable_expert_parallel,
        "moe_backend": args.moe_backend,
        "vllm_pp_layer_partition": os.environ.get("VLLM_PP_LAYER_PARTITION", ""),
        "vllm_host_ip": os.environ.get("VLLM_HOST_IP", ""),
        "ray_address": os.environ.get("RAY_ADDRESS", ""),
        "max_jobs": os.environ.get("MAX_JOBS", ""),
    }
    start = time.monotonic()
    try:
        from vllm import LLM, SamplingParams

        compilation_config = None
        if args.enable_auto_functionalized_v2 or args.compile_mode_none or args.cudagraph_mode:
            compilation_config = {}
            if args.compile_mode_none:
                compilation_config["mode"] = "NONE"
            if args.cudagraph_mode:
                compilation_config["cudagraph_mode"] = args.cudagraph_mode
            if args.enable_auto_functionalized_v2:
                compilation_config["inductor_compile_config"] = {
                    "enable_auto_functionalized_v2": True,
                }

        llm = LLM(
            model=args.model,
            tokenizer_mode="deepseek_v4",
            trust_remote_code=True,
            tensor_parallel_size=args.tensor_parallel_size,
            pipeline_parallel_size=args.pipeline_parallel_size,
            distributed_executor_backend="ray",
            max_model_len=args.max_model_len,
            max_num_seqs=args.max_num_seqs,
            max_num_batched_tokens=args.max_num_batched_tokens,
            gpu_memory_utilization=args.gpu_memory_utilization,
            kv_cache_dtype=args.kv_cache_dtype,
            disable_custom_all_reduce=True,
            enforce_eager=args.enforce_eager,
            compilation_config=compilation_config,
            enable_expert_parallel=args.enable_expert_parallel,
            moe_backend=args.moe_backend or "auto",
        )
        loaded = time.monotonic()
        warm_start = time.monotonic()
        prompts = make_prompts(
            args.prompt,
            args.batch_size,
            unique_prompts=not args.shared_prompt,
        )
        warm_outputs = llm.generate(
            prompts,
            SamplingParams(max_tokens=args.warm_tokens, temperature=0.0),
        )
        warm_end = time.monotonic()
        measured_batch_ids_by_iteration: list[list[list[int]]] = []
        measured_iteration_s: list[float] = []
        for _ in range(args.measure_iterations):
            measure_start = time.monotonic()
            measured_outputs = llm.generate(
                prompts,
                SamplingParams(max_tokens=args.measure_tokens, temperature=0.0),
            )
            measure_end = time.monotonic()
            measured_batch_ids_by_iteration.append(collect_batch_ids(measured_outputs))
            measured_iteration_s.append(measure_end - measure_start)
        warm_batch_ids = collect_batch_ids(warm_outputs)
        warm_ids = flatten_ids(warm_batch_ids)
        measured_ids = flatten_ids(
            [
                row
                for measured_batch_ids in measured_batch_ids_by_iteration
                for row in measured_batch_ids
            ]
        )
        measured_generated_tokens_by_iteration = [
            len(flatten_ids(measured_batch_ids))
            for measured_batch_ids in measured_batch_ids_by_iteration
        ]
        measured_tps_by_iteration = [
            tps_for_tokens(token_count, seconds)
            for token_count, seconds in zip(measured_generated_tokens_by_iteration, measured_iteration_s)
        ]
        measured_token_hashes_by_iteration = [
            sha256_text(json.dumps(flatten_ids(measured_batch_ids), separators=(",", ":")))
            for measured_batch_ids in measured_batch_ids_by_iteration
        ]
        measure_s = sum(measured_iteration_s)
        artifact.update(
            {
                "status": "passed",
                "load_s": loaded - start,
                "warm_s": warm_end - warm_start,
                "measure_s": measure_s,
                "total_s": time.monotonic() - start,
                "warm_generated_tokens": len(warm_ids),
                "measured_generated_tokens": len(measured_ids),
                "warm_generated_tokens_per_row": [len(row) for row in warm_batch_ids],
                "measured_generated_tokens_per_iteration": measured_generated_tokens_by_iteration,
                "measured_tps_per_iteration": measured_tps_by_iteration,
                "measured_iteration_s": measured_iteration_s,
                "warm_tps": tps_for_tokens(len(warm_ids), warm_end - warm_start),
                "measured_tps": tps_for_tokens(len(measured_ids), measure_s),
                "warm_token_ids": warm_ids,
                "measured_token_ids": measured_ids,
                "warm_batch_token_ids": warm_batch_ids,
                "measured_batch_token_ids_by_iteration": measured_batch_ids_by_iteration,
                "measured_token_hashes_by_iteration": measured_token_hashes_by_iteration,
                "measured_token_hash": sha256_text(json.dumps(measured_ids, separators=(",", ":"))),
            }
        )
        write_artifact(args.output, artifact)
        return 0
    except Exception as exc:
        artifact.update(
            {
                "status": "failed",
                "total_s": time.monotonic() - start,
                "error_type": type(exc).__name__,
                "error": str(exc),
                "traceback": traceback.format_exc(),
            }
        )
        write_artifact(args.output, artifact)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
