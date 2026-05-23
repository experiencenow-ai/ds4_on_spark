#!/usr/bin/env python3
"""Run the DS4 diamond-refinement Phase-A loop."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from scripts._lib.diamond_local_model import DiamondLocalModelClient
from scripts._lib.diamond_local_model import DiamondSshTransformersClient
from scripts.diamond_refinement_domain import FORMAT
from scripts.diamond_refinement_domain import run_synthetic


def main() -> int:
    parser = argparse.ArgumentParser(description="Run diamond refinement candidates in a verifier sandbox.")
    parser.add_argument("--synthetic", action="store_true", help="Run the Phase-A synthetic coal-to-diamond example.")
    parser.add_argument("--model-endpoint", help="Spark-local model endpoint. Frontier API endpoints are rejected.")
    parser.add_argument("--provider-id", default="spark2-local-small")
    parser.add_argument("--spark-host", default="spark2")
    parser.add_argument("--spark-transformers-model-path", help="Use a Spark-hosted Transformers model through SSH instead of HTTP.")
    parser.add_argument("--spark-python", default="python3")
    parser.add_argument("--timeout-seconds", type=float, default=60.0)
    parser.add_argument("--output", type=Path, help="Write the JSON artifact to this path.")
    args = parser.parse_args()
    if not args.synthetic:
        parser.error("Phase A currently supports --synthetic only.")
    if bool(args.model_endpoint) == bool(args.spark_transformers_model_path):
        parser.error("Provide exactly one of --model-endpoint or --spark-transformers-model-path.")
    if args.spark_transformers_model_path:
        client = DiamondSshTransformersClient(
            args.spark_host,
            args.spark_transformers_model_path,
            provider_id=args.provider_id,
            python_executable=args.spark_python,
            timeout_seconds=args.timeout_seconds,
        )
    else:
        client = DiamondLocalModelClient(
            args.model_endpoint or "",
            provider_id=args.provider_id,
            timeout_seconds=args.timeout_seconds,
        )
    record = run_synthetic(client, args.output)
    if record.get("format") != FORMAT:
        raise RuntimeError("internal format mismatch")
    sys.stdout.write(json.dumps(record, indent=2, sort_keys=True) + "\n")
    return 0 if record.get("status") == "passed" else 1


if __name__ == "__main__":
    raise SystemExit(main())
