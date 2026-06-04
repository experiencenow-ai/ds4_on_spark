#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys

from ds4_infer.baked_profiles import (
    create_engine_lock,
    parse_csv_ints,
    parse_csv_strings,
    parse_key_value,
    parse_set_arg,
    resolve_path,
    write_lock,
)


def main() -> int:
    args = _parse_args()
    v2_dir = Path(__file__).resolve().parents[1]
    repo_dir = v2_dir.parent
    arg_sets = dict(parse_set_arg(item) for item in args.set_arg)
    env_sets = dict(parse_key_value(item) for item in args.set_env)
    expected_banner = dict(parse_key_value(item) for item in args.expect_banner)
    lock = create_engine_lock(
        profile_name=args.profile_name,
        runtime_contract_path=resolve_path(args.runtime_contract, v2_dir),
        topology_path=resolve_path(args.topology, v2_dir) if args.topology else None,
        service_id=args.service_id,
        ds4_repo=resolve_path(args.ds4_repo, repo_dir),
        vllm_repo=resolve_path(args.vllm_repo, repo_dir) if args.vllm_repo else None,
        model_path=args.model_path or None,
        served_model_name=args.served_model_name or None,
        node_ids=parse_csv_strings(args.node_ids) if args.node_ids else None,
        layer_partition=parse_csv_ints(args.layer_partition) if args.layer_partition else None,
        pipeline_parallel_size=args.pipeline_parallel_size,
        tensor_parallel_size=args.tensor_parallel_size,
        arg_sets=arg_sets,
        arg_drops=args.drop_arg,
        env_sets=env_sets,
        expected_banner=expected_banner,
        cache_root=args.cache_root or None,
        cache_root_base=args.cache_root_base,
        semantic_preset=args.semantic_preset,
        allow_dirty=args.allow_dirty,
    )
    output_path = write_lock(lock, Path(args.output).expanduser())
    print(json.dumps({"lock": str(output_path), "profile_hash": lock["profile_hash"], "lock_sha256": lock["lock_sha256"]}, sort_keys=True))
    return 0


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Resolve a DS4/vLLM profile into a deterministic engine.lock.json.")
    parser.add_argument("--profile-name", required=True)
    parser.add_argument("--runtime-contract", default="profiles/runtime_contracts/dsv4_flash_pp8_mtp_v1.json")
    parser.add_argument("--topology", default="profiles/topology/static_sparks.json")
    parser.add_argument("--service-id", default="dsv4_flash_pp8")
    parser.add_argument("--ds4-repo", default=".")
    parser.add_argument("--vllm-repo", default="")
    parser.add_argument("--output", required=True)
    parser.add_argument("--model-path", default="")
    parser.add_argument("--served-model-name", default="")
    parser.add_argument("--node-ids", default="")
    parser.add_argument("--layer-partition", default="")
    parser.add_argument("--pipeline-parallel-size", type=int)
    parser.add_argument("--tensor-parallel-size", type=int)
    parser.add_argument("--set-arg", action="append", default=[], help="Set/replace a vLLM arg as --flag=value.")
    parser.add_argument("--drop-arg", action="append", default=[], help="Drop a vLLM arg by flag. Use --drop-arg=--flag.")
    parser.add_argument("--set-env", action="append", default=[], help="Set a locked environment variable as KEY=VALUE.")
    parser.add_argument("--expect-banner", action="append", default=[], help="Record an expected startup banner key as KEY=VALUE.")
    parser.add_argument("--cache-root", default="")
    parser.add_argument("--cache-root-base", default="/opt/ds4/vllm_cache")
    parser.add_argument("--semantic-preset", choices=("none", "dsv4-basic"), default="none")
    parser.add_argument("--allow-dirty", action="store_true")
    return parser.parse_args()


if __name__ == "__main__":
    raise SystemExit(main())
