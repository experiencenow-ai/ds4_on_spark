from __future__ import annotations

import argparse
import json
import sys

from .experiment import VllmBuildPlan, plan_spark7_experiment, write_spark7_experiment
from .service import NixlDeployment, plan_deployment, write_launch_scripts


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="ds4-nixl")
    sub = parser.add_subparsers(dest="cmd", required=True)

    plan = sub.add_parser("plan")
    plan.add_argument("--deployment", required=True)

    write_scripts = sub.add_parser("write-scripts")
    write_scripts.add_argument("--deployment", required=True)
    write_scripts.add_argument("--output-dir", required=True)

    spark7_plan = sub.add_parser("spark7-experiment-plan")
    spark7_plan.add_argument("--deployment", required=True)
    spark7_plan.add_argument("--vllm-build", required=True)

    spark7_write = sub.add_parser("write-spark7-experiment")
    spark7_write.add_argument("--deployment", required=True)
    spark7_write.add_argument("--vllm-build", required=True)
    spark7_write.add_argument("--output-dir", required=True)

    args = parser.parse_args(argv)

    deployment = NixlDeployment.load(args.deployment)
    if args.cmd == "plan":
        print(json.dumps(plan_deployment(deployment), indent=2, sort_keys=True))
        return 0
    if args.cmd == "write-scripts":
        print(json.dumps(write_launch_scripts(deployment, args.output_dir), indent=2, sort_keys=True))
        return 0
    if args.cmd == "spark7-experiment-plan":
        build = VllmBuildPlan.load(args.vllm_build)
        print(json.dumps(plan_spark7_experiment(deployment=deployment, build=build), indent=2, sort_keys=True))
        return 0
    if args.cmd == "write-spark7-experiment":
        build = VllmBuildPlan.load(args.vllm_build)
        print(json.dumps(write_spark7_experiment(deployment=deployment, build=build, output_dir=args.output_dir), indent=2, sort_keys=True))
        return 0
    raise AssertionError(args.cmd)


if __name__ == "__main__":
    sys.exit(main())
