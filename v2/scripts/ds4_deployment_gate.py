#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys

from ds4_infer.deployment import default_cohort_workers, default_dispatch_window, deployment_readiness
from ds4_infer.env_utils import env_bool, env_int
from ds4_infer.topology import SparkTopology


ROOT = Path(__file__).resolve().parents[1]


def main(argv: list[str] | None = None) -> int:
    args = _parse_args(argv)
    topology = SparkTopology.load(args.topology)
    window = env_int("DS4_API_DISPATCH_WINDOW", default_dispatch_window(topology))
    refill = env_int("DS4_API_DISPATCH_REFILL_BATCH", window)
    workers = env_int("DS4_API_DISPATCH_COHORT_WORKERS", default_cohort_workers(topology))
    payload = deployment_readiness(
        topology=topology,
        dispatcher_window=window,
        dispatcher_refill_batch=refill,
        dispatcher_cohort_workers=workers,
        resident_multimodel=env_bool("DS4_API_RESIDENT_MULTIMODEL", True),
    )
    if args.json:
        print(json.dumps(payload, indent=2 if args.pretty else None, sort_keys=True))
    else:
        _print_text(payload)
    return 0 if payload["ready"] else 1


def _parse_args(argv: list[str] | None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Validate DS4 coordinator deployment readiness.")
    parser.add_argument("--topology", default=str(ROOT / "profiles" / "topology" / "static_sparks.json"))
    parser.add_argument("--json", action="store_true")
    parser.add_argument("--pretty", action="store_true")
    return parser.parse_args(argv)


def _print_text(payload: dict[str, object]) -> None:
    state = "ready" if payload.get("ready") else "not ready"
    print(f"DS4 deployment readiness: {state}")
    print(f"active services: {', '.join(payload.get('active_resident_service_ids', []))}")
    print(f"dispatcher window: {payload.get('dispatcher_window')} refill: {payload.get('dispatcher_refill_batch')}")
    for item in payload.get("checks", []):
        if not isinstance(item, dict):
            continue
        mark = "ok" if item.get("ok") else str(item.get("severity") or "error")
        print(f"[{mark}] {item.get('name')}: {item.get('message')}")


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
