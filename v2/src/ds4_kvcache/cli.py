from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
import sys

from .service import KvCacheDeployment, plan_deployment, write_launch_scripts


ROOT = Path(__file__).resolve().parents[2]


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="ds4-kvcache")
    sub = parser.add_subparsers(dest="cmd", required=True)

    plan = sub.add_parser("plan")
    plan.add_argument("--deployment", required=True)

    write_scripts = sub.add_parser("write-scripts")
    write_scripts.add_argument("--deployment", required=True)
    write_scripts.add_argument("--output-dir", required=True)

    args = parser.parse_args(argv)
    deployment = KvCacheDeployment.load(args.deployment)
    if args.cmd == "plan":
        print(json.dumps(plan_deployment(deployment), indent=2, sort_keys=True))
        return 0
    if args.cmd == "write-scripts":
        _require_lifecycle_write_scripts(deployment)
        print(json.dumps(write_launch_scripts(deployment, args.output_dir), indent=2, sort_keys=True))
        return 0
    raise AssertionError(args.cmd)


def _require_lifecycle_write_scripts(deployment: KvCacheDeployment) -> None:
    service_id = _static_pipeline_service_id(deployment)
    if service_id is None:
        return
    if os.environ.get("DS4_PIPELINE_LIFECYCLE") == "1":
        return
    raise SystemExit(
        "ERROR: write-scripts for resident topology pipelines must go through "
        "v2/scripts/ds4_pipeline_lifecycle.py; use: "
        f"python3 scripts/ds4_pipeline_lifecycle.py --service {service_id} write-scripts --execute"
    )


def _static_pipeline_service_id(deployment: KvCacheDeployment) -> str | None:
    topology_path = ROOT / "profiles" / "topology" / "static_sparks.json"
    if not topology_path.exists():
        return None
    data = json.loads(topology_path.read_text(encoding="utf-8"))
    routing = data.get("routing_policy") if isinstance(data.get("routing_policy"), dict) else {}
    services = routing.get("pipeline_services") if isinstance(routing.get("pipeline_services"), dict) else {}
    for service_id, service in services.items():
        if isinstance(service, dict) and str(service.get("profile_id")) == deployment.profile_id:
            return str(service_id)
    return None


if __name__ == "__main__":
    sys.exit(main())
