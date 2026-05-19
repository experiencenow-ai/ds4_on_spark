#!/usr/bin/env python3
"""Run a small DS4 vLLM PP generation probe and emit JSON."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import time
import traceback
from pathlib import Path
from typing import Any


FORMAT = "ds4-vllm-pp-runtime-probe-v1"


def sha256_text(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def write_artifact(path: str | None, artifact: dict[str, Any]) -> None:
    data = json.dumps(artifact, indent=2, sort_keys=True) + "\n"
    if path:
        Path(path).write_text(data, encoding="utf-8")
    print(data, flush=True)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--model", required=True)
    parser.add_argument("--pipeline-parallel-size", type=int, required=True)
    parser.add_argument("--tensor-parallel-size", type=int, default=1)
    parser.add_argument("--prompt", default="Explain Redis streams in one paragraph.")
    parser.add_argument("--max-tokens", type=int, default=4)
    parser.add_argument("--output")
    parser.add_argument("--speculative-config-json", default="")
    parser.add_argument("--max-model-len", type=int, default=1024)
    parser.add_argument("--max-num-seqs", type=int, default=1)
    parser.add_argument("--max-num-batched-tokens", type=int, default=1024)
    parser.add_argument("--gpu-memory-utilization", type=float, default=0.60)
    parser.add_argument("--kv-cache-dtype", default="fp8")
    parser.add_argument("--enforce-eager", action="store_true")
    args = parser.parse_args()

    artifact: dict[str, Any] = {
        "format": FORMAT,
        "status": "started",
        "utc_start": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "model": args.model,
        "prompt_sha256": sha256_text(args.prompt),
        "pipeline_parallel_size": args.pipeline_parallel_size,
        "tensor_parallel_size": args.tensor_parallel_size,
        "max_tokens": args.max_tokens,
        "max_model_len": args.max_model_len,
        "max_num_seqs": args.max_num_seqs,
        "max_num_batched_tokens": args.max_num_batched_tokens,
        "gpu_memory_utilization": args.gpu_memory_utilization,
        "kv_cache_dtype": args.kv_cache_dtype,
        "enforce_eager": args.enforce_eager,
        "vllm_pp_layer_partition": os.environ.get("VLLM_PP_LAYER_PARTITION", ""),
        "vllm_host_ip": os.environ.get("VLLM_HOST_IP", ""),
        "ray_address": os.environ.get("RAY_ADDRESS", ""),
        "speculative_config_json": args.speculative_config_json,
    }
    start = time.monotonic()
    try:
        print("import_vllm", flush=True)
        from vllm import LLM, SamplingParams

        llm_kwargs: dict[str, Any] = {
            "model": args.model,
            "tokenizer_mode": "deepseek_v4",
            "trust_remote_code": True,
            "tensor_parallel_size": args.tensor_parallel_size,
            "pipeline_parallel_size": args.pipeline_parallel_size,
            "distributed_executor_backend": "ray",
            "max_model_len": args.max_model_len,
            "max_num_seqs": args.max_num_seqs,
            "max_num_batched_tokens": args.max_num_batched_tokens,
            "gpu_memory_utilization": args.gpu_memory_utilization,
            "kv_cache_dtype": args.kv_cache_dtype,
            "disable_custom_all_reduce": True,
            "enforce_eager": args.enforce_eager,
        }
        if args.speculative_config_json.strip():
            llm_kwargs["speculative_config"] = json.loads(args.speculative_config_json)
        print("construct_llm", flush=True)
        llm = LLM(**llm_kwargs)
        loaded = time.monotonic()
        artifact["load_s"] = loaded - start
        print("generate", flush=True)
        outputs = llm.generate([args.prompt], SamplingParams(max_tokens=args.max_tokens, temperature=0.0))
        finished = time.monotonic()
        token_ids: list[int] = []
        text = ""
        if outputs and outputs[0].outputs:
            out = outputs[0].outputs[0]
            text = getattr(out, "text", "") or ""
            raw_ids = getattr(out, "token_ids", []) or []
            token_ids = [int(x) for x in raw_ids]
        artifact.update(
            {
                "status": "passed",
                "load_s": loaded - start,
                "generate_s": finished - loaded,
                "total_s": finished - start,
                "generated_tokens": len(token_ids),
                "generation_tps": (len(token_ids) / (finished - loaded)) if finished > loaded else 0.0,
                "token_ids": token_ids,
                "token_hash": sha256_text(json.dumps(token_ids, separators=(",", ":"))),
                "output_text_preview": text[:512],
            }
        )
        write_artifact(args.output, artifact)
        return 0
    except Exception as exc:
        finished = time.monotonic()
        artifact.update(
            {
                "status": "failed",
                "total_s": finished - start,
                "error_type": type(exc).__name__,
                "error": str(exc),
                "traceback": traceback.format_exc(),
            }
        )
        write_artifact(args.output, artifact)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
