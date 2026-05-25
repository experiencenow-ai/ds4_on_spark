from __future__ import annotations

import argparse
import json
import sys

from .profiles import ProfileRegistry
from .queue import InferenceQueue
from .runners import AntirezRunner, AutoRunner, CommandRunner, FakeRunner, SparkHttpRunner, VllmOpenAIRunner
from .service import load_requests_jsonl, run_requests
from .topology import SparkTopology


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="ds4-infer")
    sub = parser.add_subparsers(dest="cmd", required=True)

    profiles = sub.add_parser("profiles")
    profiles.add_argument("--profiles-dir", required=True)

    topology_cmd = sub.add_parser("topology")
    topology_cmd.add_argument("--topology", required=True)
    topology_cmd.add_argument("--capacity", action="store_true")

    submit = sub.add_parser("submit")
    submit.add_argument("--profiles-dir", required=True)
    submit.add_argument("--requests", required=True)
    submit.add_argument("--out", required=True)
    submit.add_argument("--runner", choices=["fake", "command", "vllm", "antirez", "auto", "spark"], default="fake")
    submit.add_argument("--runner-timeout-s", type=int, default=300)
    submit.add_argument("--topology")
    submit.add_argument("--command", nargs="*")
    submit.add_argument("--run", action="store_true")

    queue_submit = sub.add_parser("queue-submit")
    queue_submit.add_argument("--queue-dir", required=True)
    queue_submit.add_argument("--profiles-dir", required=True)
    queue_submit.add_argument("--requests", required=True)
    queue_submit.add_argument("--topology")
    queue_submit.add_argument("--batch-id")

    queue_work = sub.add_parser("queue-work")
    queue_work.add_argument("--queue-dir", required=True)
    queue_work.add_argument("--profiles-dir", required=True)
    queue_work.add_argument("--runner", choices=["fake", "command", "vllm", "antirez", "auto", "spark"], default="fake")
    queue_work.add_argument("--runner-timeout-s", type=int, default=300)
    queue_work.add_argument("--command", nargs="*")
    queue_work.add_argument("--node-id")
    queue_work.add_argument("--batch-key")
    queue_work.add_argument("--limit", type=int, default=1)

    queue_status = sub.add_parser("queue-status")
    queue_status.add_argument("--queue-dir", required=True)
    queue_status.add_argument("--request-id")
    queue_status.add_argument("--batch-id")

    queue_poll = sub.add_parser("queue-poll")
    queue_poll.add_argument("--queue-dir", required=True)
    queue_poll.add_argument("--after-event-id", type=int, default=0)
    queue_poll.add_argument("--limit", type=int, default=100)

    queue_collect = sub.add_parser("queue-collect")
    queue_collect.add_argument("--queue-dir", required=True)
    queue_collect.add_argument("--request-id")
    queue_collect.add_argument("--batch-id")

    args = parser.parse_args(argv)

    if args.cmd == "profiles":
        registry = ProfileRegistry.load(args.profiles_dir)
        print(json.dumps([profile.to_public_dict() for profile in registry.all_profiles()], indent=2, sort_keys=True))
        return 0

    if args.cmd == "topology":
        topology = SparkTopology.load(args.topology)
        payload = topology.estimate_capacity_by_profile() if args.capacity else topology.to_public_dict()
        print(json.dumps(payload, indent=2, sort_keys=True))
        return 0

    if args.cmd == "submit":
        registry = ProfileRegistry.load(args.profiles_dir)
        requests = load_requests_jsonl(args.requests)
        if not args.run:
            print(json.dumps({"state": "accepted", "request_count": len(requests)}, sort_keys=True))
            return 0
        runner = _make_runner(args.runner, args.command or [], args.runner_timeout_s)
        topology = SparkTopology.load(args.topology) if args.topology else None
        print(json.dumps(run_requests(requests=requests, registry=registry, runner=runner, out_dir=args.out, topology=topology), indent=2, sort_keys=True))
        return 0

    if args.cmd == "queue-submit":
        queue = InferenceQueue(args.queue_dir)
        registry = ProfileRegistry.load(args.profiles_dir)
        topology = SparkTopology.load(args.topology) if args.topology else None
        requests = load_requests_jsonl(args.requests)
        print(json.dumps(queue.submit_requests(requests=requests, registry=registry, topology=topology, batch_id=args.batch_id), indent=2, sort_keys=True))
        return 0

    if args.cmd == "queue-work":
        queue = InferenceQueue(args.queue_dir)
        registry = ProfileRegistry.load(args.profiles_dir)
        runner = _make_runner(args.runner, args.command or [], args.runner_timeout_s)
        print(json.dumps(queue.work(registry=registry, runner=runner, node_id=args.node_id, batch_key=args.batch_key, limit=args.limit), indent=2, sort_keys=True))
        return 0

    if args.cmd == "queue-status":
        queue = InferenceQueue(args.queue_dir)
        print(json.dumps(queue.status(request_id=args.request_id, batch_id=args.batch_id), indent=2, sort_keys=True))
        return 0

    if args.cmd == "queue-poll":
        queue = InferenceQueue(args.queue_dir)
        print(json.dumps(queue.poll(after_event_id=args.after_event_id, limit=args.limit), indent=2, sort_keys=True))
        return 0

    if args.cmd == "queue-collect":
        queue = InferenceQueue(args.queue_dir)
        print(json.dumps(queue.collect(request_id=args.request_id, batch_id=args.batch_id), indent=2, sort_keys=True))
        return 0

    raise AssertionError(args.cmd)


def _make_runner(kind: str, command: list[str], timeout_s: int):
    if kind == "fake":
        return FakeRunner()
    if kind == "command":
        return CommandRunner(command, timeout_s=timeout_s)
    if kind == "vllm":
        return VllmOpenAIRunner(timeout_s=timeout_s)
    if kind == "antirez":
        return AntirezRunner(timeout_s=timeout_s)
    if kind == "auto":
        return AutoRunner(timeout_s=timeout_s)
    if kind == "spark":
        return SparkHttpRunner(timeout_s=timeout_s)
    raise ValueError(f"unknown runner: {kind}")


if __name__ == "__main__":
    sys.exit(main())
