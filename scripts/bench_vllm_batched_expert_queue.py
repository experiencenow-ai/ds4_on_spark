#!/usr/bin/env python3
"""Run or record the DS4 vLLM batched expert queue c512 benchmark."""

from __future__ import annotations

import argparse
import copy
import hashlib
import json
import sys
import time
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from scripts import benchmark_vllm_openai_completions_fanout as fanout


FORMAT = "centaur-standard-runtime-model-benchmark-v1"
BASELINE_C512_TPS = 174.19031762627782
DEFAULT_PROVIDER_ID = "standard-vllm-deepseek-v4-flash-batched-expert-queue-graphsafe"
DEFAULT_BENCHMARK_ID = "ds4-vllm-batched-expert-queue-graphsafe-c512-output128-20260521"


def utc_now() -> str:
	return(time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()))


def canonical_hash(obj: dict[str, Any]) -> str:
	payload = copy.deepcopy(obj)
	payload.pop("artifact_sha256", None)
	data = json.dumps(payload, sort_keys=True, separators=(",", ":"), ensure_ascii=True).encode("utf-8")
	return(hashlib.sha256(data).hexdigest())


def build_common(args: argparse.Namespace) -> dict[str, Any]:
	return({
		"format": FORMAT,
		"artifact_sha256": "",
		"benchmark_id": args.benchmark_id,
		"provider_id": args.provider_id,
		"model_id": args.model_id,
		"model_family": "deepseek_v4_flash",
		"runtime": "vllm",
		"runtime_version": args.runtime_version,
		"model_format": "safetensors",
		"quantization": "official FP8 checkpoint with fp8 KV cache and fp4 expert path",
		"hardware": {
			"fabric": "direct_200g_pair",
			"head_node": "spark4",
			"launcher_node": "spark3",
			"machine": "DGX Spark",
			"worker_node": "spark5",
		},
		"launch_command": args.launch_command,
		"api_endpoint": args.endpoint.rsplit("/", 1)[0],
		"context_length": 200000,
		"mtp_supported": True,
		"mtp_enabled": False,
		"speculative_config": {},
		"ngram_spec_enabled": False,
		"batch_size": 512,
		"prompt_shape": "antirez_dir_steering_eval_prompts_c512_output128",
		"output_mode": "full_vocab",
		"tokens_per_second": None,
		"time_to_first_token_ms": None,
		"prompt_processing_tokens_per_second": None,
		"memory_used_gib": None,
		"parse_valid": False,
		"task_quality_score": None,
		"blocker_kind": "benchmark_not_run",
		"blocker_detail": "",
		"created_utc": args.created_utc or utc_now(),
		"patch_id": "ds4-vllm-no-dp-batched-marlin-prototype",
		"patch_file": "docs/vllm-patches/vllm-deepseek-v4-mxfp4-batched-expert-queue-graphsafe.patch",
		"env_flag": "DS4_VLLM_FORCE_NO_DP_BATCHED_MARLIN=1",
		"baseline_c512_aggregate_tps": BASELINE_C512_TPS,
		"baseline_source_fixture": "fixtures/standard_runtime_benchmarks/vllm_deepseek_v4_flash_tp2_no_mtp_spark45_mixed_fanout_20260521.example.json",
		"benchmark_request": {
			"concurrency": 512,
			"output_length": 128,
			"ignore_eos": True,
			"prompt_source": "antirez/ds4 dir-steering/examples/eval_prompts.txt",
		},
	})


def build_blocked_artifact(args: argparse.Namespace) -> dict[str, Any]:
	obj = build_common(args)
	obj.update({
		"benchmark_status": "blocked",
		"blocker_kind": "endpoint_unavailable",
		"blocker_detail": args.blocker_detail,
		"startup_status": "failed",
		"selected_backend": "BATCHED_MARLIN",
		"prepare_finalize": "BatchedPrepareAndFinalize",
		"error_signature": args.error_signature,
		"startup_observations": {
			"api_ready": False,
			"head_node": "spark4",
			"worker_node": "spark5",
			"max_num_batched_tokens": 512,
			"cudagraph_mode": "FULL_AND_PIECEWISE",
			"spark4_ssh_result": "Connection timed out during banner exchange",
			"spark5_worker_container": "exited before API readiness",
		},
		"raw_runtime_evidence": args.raw_evidence,
	})
	obj["artifact_sha256"] = canonical_hash(obj)
	return(obj)


def build_measured_artifact(args: argparse.Namespace) -> dict[str, Any]:
	prompts = fanout.load_prompts(args.prompt_file)
	round_rec = fanout.run_round(
		args.endpoint,
		args.model,
		prompts,
		512,
		0,
		128,
		args.timeout_s,
		True,
	)
	if int(round_rec["errors"]) != 0:
		args.blocker_detail = "c512/output128 benchmark returned request errors"
		args.error_signature = json.dumps({k: round_rec[k] for k in ("errors", "wall_s")}, sort_keys=True)
		args.raw_evidence = [json.dumps({k: round_rec[k] for k in ("errors", "wall_s", "completion_tokens")}, sort_keys=True)]
		return(build_blocked_artifact(args))
	obj = build_common(args)
	tps = float(round_rec["aggregate_tps"])
	obj.update({
		"benchmark_status": "passed",
		"tokens_per_second": tps,
		"time_to_first_token_ms": args.time_to_first_token_ms,
		"prompt_processing_tokens_per_second": args.prompt_processing_tokens_per_second,
		"memory_used_gib": args.memory_used_gib,
		"parse_valid": True,
		"blocker_kind": "none",
		"blocker_detail": "",
		"measured_c512_aggregate_tps": tps,
		"speedup_vs_baseline": tps / BASELINE_C512_TPS,
		"raw_round": round_rec,
	})
	obj["artifact_sha256"] = canonical_hash(obj)
	return(obj)


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
	p = argparse.ArgumentParser(description=__doc__)
	p.add_argument("--output", required=True)
	p.add_argument("--endpoint", default="http://10.20.0.14:8000/v1/completions")
	p.add_argument("--model", default="deepseek-v4-flash")
	p.add_argument("--prompt-file", default="")
	p.add_argument("--timeout-s", type=float, default=7200.0)
	p.add_argument("--blocked", action="store_true")
	p.add_argument("--blocker-detail", default="")
	p.add_argument("--error-signature", default="")
	p.add_argument("--raw-evidence", action="append", default=[])
	p.add_argument("--benchmark-id", default=DEFAULT_BENCHMARK_ID)
	p.add_argument("--provider-id", default=DEFAULT_PROVIDER_ID)
	p.add_argument("--model-id", default="deepseek-ai/DeepSeek-V4-Flash")
	p.add_argument("--runtime-version", default="0.1.dev16581+gdda4668b5.d20260521")
	p.add_argument("--launch-command", default="DS4_VLLM_FORCE_NO_DP_BATCHED_MARLIN=1 ./run-recipe.sh recipes/deepseek-v4-flash-local-batch512-no-mtp-ds4-batched-marlin-graphsafe-mbt512.yaml --no-ray --no-cache-dirs -d -- --max-num-batched-tokens 512")
	p.add_argument("--created-utc", default="")
	p.add_argument("--time-to-first-token-ms", type=float, default=0.0)
	p.add_argument("--prompt-processing-tokens-per-second", type=float, default=0.0)
	p.add_argument("--memory-used-gib", type=float, default=0.0)
	return(p.parse_args(argv))


def run(args: argparse.Namespace) -> dict[str, Any]:
	if args.blocked:
		if args.blocker_detail == "" or args.error_signature == "":
			raise SystemExit("--blocked requires --blocker-detail and --error-signature")
		artifact = build_blocked_artifact(args)
	else:
		artifact = build_measured_artifact(args)
	path = Path(args.output)
	path.parent.mkdir(parents=True, exist_ok=True)
	with path.open("w", encoding="utf-8") as f:
		json.dump(artifact, f, indent=2, sort_keys=True)
		f.write("\n")
	return(artifact)


def main_args_for_test(argv: list[str]) -> int:
	args = parse_args(argv)
	artifact = run(args)
	print(json.dumps({
		"output": str(Path(args.output)),
		"benchmark_status": artifact.get("benchmark_status"),
		"tokens_per_second": artifact.get("tokens_per_second"),
		"blocker_kind": artifact.get("blocker_kind"),
	}, indent=2, sort_keys=True))
	return(0)


def main() -> int:
	args = parse_args()
	artifact = run(args)
	print(json.dumps({
		"output": args.output,
		"benchmark_status": artifact.get("benchmark_status"),
		"tokens_per_second": artifact.get("tokens_per_second"),
		"blocker_kind": artifact.get("blocker_kind"),
	}, indent=2, sort_keys=True))
	return(0)


if __name__ == "__main__":
	raise SystemExit(main())
