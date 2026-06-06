from __future__ import annotations

import argparse
import json
import sys
import time

from .profiles import ProfileRegistry
from .control import trim_spark_memory
from .pipelines import pipeline_service_batch_limit
from .queue import InferenceQueue
from .runners import AntirezRunner, AutoRunner, CommandRunner, FakeRunner, HmaPersistentRunner, PipelineOpenAIRunner, SparkHttpRunner, VllmOpenAIRunner
from .service import load_requests_jsonl
from .topology import SparkTopology

RUNNER_CHOICES = ("fake", "command", "vllm", "hma", "antirez", "auto", "spark", "pipeline")


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="ds4-infer")
    sub = parser.add_subparsers(dest="cmd", required=True)
    _add_basic_args(sub)
    _add_submit_args(sub)
    _add_queue_work_args(sub)
    _add_queue_status_args(sub)
    return parser


def _add_basic_args(sub: argparse._SubParsersAction) -> None:
    profiles = sub.add_parser("profiles")
    profiles.add_argument("--profiles-dir", required=True)
    topology_cmd = sub.add_parser("topology")
    topology_cmd.add_argument("--topology", required=True)
    topology_cmd.add_argument("--capacity", action="store_true")
    trim = sub.add_parser("trim-spark-memory")
    trim.add_argument("--node-id", required=True)
    trim.add_argument("--topology", default="profiles/topology/static_sparks.json")
    trim.add_argument("--profiles-dir", default="profiles/models")
    trim.add_argument("--contracts-dir", default="profiles/runtime_contracts")
    trim.add_argument("--profile-id")
    trim.add_argument("--base-url")
    trim.add_argument("--timeout-s", type=int, default=60)
    trim.add_argument("--mode", choices=("abort", "wait"), default="abort")
    trim.add_argument("--reset-external", action=argparse.BooleanOptionalAction, default=True)
    trim.add_argument("--release-offload-memory", action=argparse.BooleanOptionalAction, default=True)
    trim.add_argument("--malloc-trim", action=argparse.BooleanOptionalAction, default=True)
    trim.add_argument("--resume", action=argparse.BooleanOptionalAction, default=True)
    trim.add_argument("--execute", action="store_true")
    preconnect = sub.add_parser("spark-ssh-preconnect")
    preconnect.add_argument("--nodes", default="spark0,spark1,spark2,spark3,spark4,spark5,spark6,spark7")
    preconnect.add_argument("--runner-timeout-s", type=int, default=300)


def _add_submit_args(sub: argparse._SubParsersAction) -> None:
    submit = sub.add_parser("submit")
    submit.add_argument("--profiles-dir", required=True)
    submit.add_argument("--requests", required=True)
    queue_submit = sub.add_parser("queue-submit")
    queue_submit.add_argument("--queue-dir", required=True)
    queue_submit.add_argument("--profiles-dir", required=True)
    queue_submit.add_argument("--requests", required=True)
    queue_submit.add_argument("--topology", required=True)
    queue_submit.add_argument("--batch-id")
    queue_submit.add_argument("--priority", type=int, help="Lower numbers run first. Default is 10 for normal queued requests and 0 for immediate requests.")

    queue_submit_cpu = sub.add_parser("queue-submit-cpu")
    queue_submit_cpu.add_argument("--queue-dir", required=True)
    queue_submit_cpu.add_argument("--service", required=True)
    queue_submit_cpu.add_argument("--items", required=True)
    queue_submit_cpu.add_argument("--batch-id")
    queue_submit_cpu.add_argument("--node-id")
    queue_submit_cpu.add_argument("--timeout-s", type=float)
    queue_submit_cpu.add_argument("--immediate", action="store_true")
    queue_submit_cpu.add_argument("--priority", type=int, help="Lower numbers run first. Default is 10 for normal queued requests and 0 for immediate requests.")


def _add_queue_work_args(sub: argparse._SubParsersAction) -> None:
    queue_work = sub.add_parser("queue-work")
    _add_queue_worker_args(queue_work)
    queue_worker = sub.add_parser("queue-worker")
    _add_queue_worker_args(queue_worker)
    queue_reap = sub.add_parser("queue-reap-leases")
    queue_reap.add_argument("--queue-dir", required=True)
    queue_reap.add_argument("--max-attempts", type=int, default=3)


def _add_queue_status_args(sub: argparse._SubParsersAction) -> None:
    queue_status = sub.add_parser("queue-status")
    queue_status.add_argument("--queue-dir", required=True)
    queue_status.add_argument("--request-id")
    queue_status.add_argument("--batch-id")
    queue_status.add_argument("--job-id")

    queue_cancel = sub.add_parser("queue-cancel")
    queue_cancel.add_argument("--queue-dir", required=True)
    queue_cancel.add_argument("--request-id")
    queue_cancel.add_argument("--batch-id")
    queue_cancel.add_argument("--job-id")
    queue_cancel.add_argument("--reason", default="cancelled by operator")

    queue_poll = sub.add_parser("queue-poll")
    queue_poll.add_argument("--queue-dir", required=True)
    queue_poll.add_argument("--after-event-id", type=int, default=0)
    queue_poll.add_argument("--limit", type=int, default=100)

    queue_collect = sub.add_parser("queue-collect")
    queue_collect.add_argument("--queue-dir", required=True)
    queue_collect.add_argument("--request-id")
    queue_collect.add_argument("--batch-id")
    queue_collect.add_argument("--job-id")

    pipeline_status = sub.add_parser("pipeline-status")
    pipeline_status.add_argument("--queue-dir", required=True)
    pipeline_status.add_argument("--service-id")

    telemetry = sub.add_parser("pipeline-telemetry-report")
    telemetry.add_argument("--queue-dir", required=True)
    telemetry.add_argument("--service-id", required=True)
    telemetry.add_argument("--node-id", required=True)
    telemetry.add_argument("--stage-index", type=int, required=True)
    telemetry.add_argument("--stage-count", type=int, required=True)
    telemetry.add_argument("--layer-start", type=int)
    telemetry.add_argument("--layer-end", type=int)
    telemetry.add_argument("--kv-shard-bytes", type=int, default=0)
    telemetry.add_argument("--payload-json", default="{}")

    queue_pipeline_status = sub.add_parser("queue-pipeline-status")
    queue_pipeline_status.add_argument("--queue-dir", required=True)

    queue_pipeline_telemetry = sub.add_parser("queue-pipeline-telemetry")
    queue_pipeline_telemetry.add_argument("--queue-dir", required=True)
    queue_pipeline_telemetry.add_argument("--report", required=True)


def main(argv: list[str] | None = None) -> int:
    return _run(_build_parser().parse_args(argv))


def _run(args: argparse.Namespace) -> int:
    handlers = {
        "profiles": _cmd_profiles,
        "topology": _cmd_topology,
        "trim-spark-memory": _cmd_trim_spark_memory,
        "spark-ssh-preconnect": _cmd_spark_ssh_preconnect,
        "submit": _cmd_submit,
        "queue-submit": _cmd_queue_submit,
        "queue-submit-cpu": _cmd_queue_submit_cpu,
        "queue-work": _cmd_queue_work,
        "queue-worker": _cmd_queue_work,
        "queue-reap-leases": _cmd_queue_reap,
        "queue-status": _cmd_queue_status,
        "queue-cancel": _cmd_queue_cancel,
        "queue-poll": _cmd_queue_poll,
        "queue-collect": _cmd_queue_collect,
        "pipeline-status": _cmd_pipeline_status,
        "pipeline-telemetry-report": _cmd_pipeline_telemetry_report,
        "pipeline-status": _cmd_pipeline_status,
        "pipeline-telemetry-report": _cmd_pipeline_telemetry_report,
        "queue-pipeline-status": _cmd_queue_pipeline_status,
        "queue-pipeline-telemetry": _cmd_queue_pipeline_telemetry,
    }
    try:
        return handlers[args.cmd](args)
    except KeyError as exc:
        raise AssertionError(args.cmd) from exc


def _emit(payload: object, *, indent: int | None = 2, flush: bool = False) -> None:
    print(json.dumps(payload, indent=indent, sort_keys=True), flush=flush)


def _cmd_profiles(args: argparse.Namespace) -> int:
    registry = ProfileRegistry.load(args.profiles_dir)
    _emit([profile.to_public_dict() for profile in registry.all_profiles()])
    return 0


def _cmd_topology(args: argparse.Namespace) -> int:
    topology = SparkTopology.load(args.topology)
    _emit(topology.estimate_capacity_by_profile() if args.capacity else topology.to_public_dict())
    return 0


def _cmd_trim_spark_memory(args: argparse.Namespace) -> int:
    _emit(
        trim_spark_memory(
            node_id=args.node_id,
            topology_path=args.topology,
            profiles_dir=args.profiles_dir,
            contracts_dir=args.contracts_dir,
            profile_id=args.profile_id,
            base_url=args.base_url,
            execute=args.execute,
            timeout_s=args.timeout_s,
            mode=args.mode,
            reset_external=args.reset_external,
            release_offload_memory=args.release_offload_memory,
            malloc_trim=args.malloc_trim,
            resume=args.resume,
        )
    )
    return 0


def _cmd_spark_ssh_preconnect(args: argparse.Namespace) -> int:
    nodes = [node.strip() for node in str(args.nodes).split(",") if node.strip()]
    _emit(SparkHttpRunner(timeout_s=args.runner_timeout_s).preconnect(nodes))
    return 0


def _cmd_submit(args: argparse.Namespace) -> int:
    requests = load_requests_jsonl(args.requests)
    _emit(
        {
            "state": "accepted",
            "request_count": len(requests),
            "live_run": "removed",
            "next": "use queue-submit plus queue-worker",
        },
        indent=None,
    )
    return 0


def _cmd_queue_submit(args: argparse.Namespace) -> int:
    queue = InferenceQueue(args.queue_dir)
    registry = ProfileRegistry.load(args.profiles_dir)
    topology = SparkTopology.load(args.topology) if args.topology else None
    requests = load_requests_jsonl(args.requests)
    _emit(queue.submit_requests(requests=requests, registry=registry, topology=topology, batch_id=args.batch_id, priority=args.priority))
    return 0


def _cmd_queue_submit_cpu(args: argparse.Namespace) -> int:
    queue = InferenceQueue(args.queue_dir)
    _emit(
        queue.submit_cpu_requests(
            service=args.service,
            items=_load_jsonl(args.items),
            batch_id=args.batch_id,
            immediate=args.immediate,
            node_id=args.node_id,
            timeout_s=args.timeout_s,
            priority=args.priority,
        )
    )
    return 0


def _cmd_queue_work(args: argparse.Namespace) -> int:
    queue = InferenceQueue(args.queue_dir)
    registry = ProfileRegistry.load(args.profiles_dir)
    runner = _make_runner(args.runner, args.command or [], args.runner_timeout_s, topology_path=args.topology)
    iterations = 0
    while True:
        result = _queue_work_once(queue, registry, runner, args)
        _emit(result, indent=None, flush=True)
        iterations += 1
        if not args.loop or (args.max_iterations > 0 and iterations >= args.max_iterations):
            break
        if result.get("claimed_count", 0) == 0:
            time.sleep(args.sleep_s)
    return 0


def _queue_work_once(queue: InferenceQueue, registry: ProfileRegistry, runner: object, args: argparse.Namespace) -> dict:
    return queue.work(
        registry=registry,
        runner=runner,
        node_id=args.node_id,
        batch_id=args.batch_id,
        limit=args.limit,
        concurrency=args.concurrency,
        worker_id=args.worker_id,
        lease_ttl_s=args.lease_ttl_s,
        heartbeat_interval_s=args.heartbeat_interval_s,
        node_profile_ids=_node_profile_ids(args.topology, args.node_id),
        max_node_depth=args.max_node_depth,
        batch_linger_s=args.batch_linger_s,
        kv_capacity_bytes=args.kv_capacity_bytes,
        transport_max_attempts=args.transport_max_attempts,
        kv_shard_layouts_by_profile=_pipeline_layouts(args.topology),
        batch_limits_by_service=_pipeline_batch_limits(args.topology),
        refill_low_watermarks_by_service=_pipeline_refill_low_watermarks(args.topology),
    )


def _node_profile_ids(topology_path: str | None, node_id: str | None) -> tuple[str, ...] | None:
    if not topology_path or not node_id:
        return None
    topology = SparkTopology.load(topology_path)
    for node in topology.nodes:
        if node.node_id == node_id:
            profile_ids = set(node.resident_profiles)
            for pipeline in topology.pipeline_services.values():
                if node_id in pipeline.node_ids:
                    profile_ids.add(pipeline.profile_id)
            return tuple(sorted(profile_ids))
    raise ValueError(f"node {node_id!r} not found in topology")


def _pipeline_layouts(topology_path: str | None) -> dict:
    if not topology_path:
        return {}
    topology = SparkTopology.load(topology_path)
    return dict(topology.profile_pipeline_services)


def _pipeline_batch_limits(topology_path: str | None) -> dict[str, int]:
    if not topology_path:
        return {}
    topology = SparkTopology.load(topology_path)
    return {service.service_id: pipeline_service_batch_limit(service) for service in topology.pipeline_services.values()}


def _pipeline_refill_low_watermarks(topology_path: str | None) -> dict[str, int]:
    if not topology_path:
        return {}
    topology = SparkTopology.load(topology_path)
    return {service.service_id: int(service.scheduler.get("refill_low_watermark") or 0) for service in topology.pipeline_services.values()}


def _pipeline_base_urls(topology_path: str | None) -> dict[str, str]:
    if not topology_path:
        return {}
    topology = SparkTopology.load(topology_path)
    urls: dict[str, str] = {}
    for pipeline in topology.pipeline_services.values():
        if not pipeline.api_base_url:
            continue
        urls[pipeline.profile_id] = pipeline.api_base_url
        urls[pipeline.service_id] = pipeline.api_base_url
        urls[pipeline.model_id] = pipeline.api_base_url
    return urls


def _cmd_queue_reap(args: argparse.Namespace) -> int:
    _emit(InferenceQueue(args.queue_dir).requeue_expired_leases(max_attempts=args.max_attempts))
    return 0


def _cmd_queue_status(args: argparse.Namespace) -> int:
    _emit(InferenceQueue(args.queue_dir).status(request_id=args.request_id, batch_id=args.batch_id, job_id=args.job_id))
    return 0


def _cmd_queue_cancel(args: argparse.Namespace) -> int:
    _emit(InferenceQueue(args.queue_dir).cancel(request_id=args.request_id, batch_id=args.batch_id, job_id=args.job_id, reason=args.reason))
    return 0


def _cmd_queue_poll(args: argparse.Namespace) -> int:
    _emit(InferenceQueue(args.queue_dir).poll(after_event_id=args.after_event_id, limit=args.limit))
    return 0


def _cmd_queue_collect(args: argparse.Namespace) -> int:
    _emit(InferenceQueue(args.queue_dir).collect(request_id=args.request_id, batch_id=args.batch_id, job_id=args.job_id))
    return 0


def _cmd_pipeline_status(args: argparse.Namespace) -> int:
    _emit(InferenceQueue(args.queue_dir).pipeline_status(service_id=args.service_id))
    return 0


def _cmd_pipeline_telemetry_report(args: argparse.Namespace) -> int:
    payload = json.loads(args.payload_json)
    _emit(
        InferenceQueue(args.queue_dir).report_pipeline_telemetry(
            service_id=args.service_id,
            node_id=args.node_id,
            stage_index=args.stage_index,
            stage_count=args.stage_count,
            layer_start=args.layer_start,
            layer_end=args.layer_end,
            kv_shard_bytes=args.kv_shard_bytes,
            payload=payload,
        )
    )
    return 0


def _cmd_pipeline_status(args: argparse.Namespace) -> int:
    _emit(InferenceQueue(args.queue_dir).pipeline_status(service_id=getattr(args, "service_id", None)))
    return 0


def _cmd_pipeline_telemetry_report(args: argparse.Namespace) -> int:
    payload = json.loads(args.payload_json)
    if not isinstance(payload, dict):
        raise ValueError("--payload-json must decode to a JSON object")
    _emit(
        InferenceQueue(args.queue_dir).report_pipeline_telemetry(
            service_id=args.service_id,
            node_id=args.node_id,
            stage_index=args.stage_index,
            stage_count=args.stage_count,
            layer_start=args.layer_start,
            layer_end=args.layer_end,
            kv_shard_bytes=args.kv_shard_bytes,
            payload=payload,
        )
    )
    return 0


def _cmd_queue_pipeline_status(args: argparse.Namespace) -> int:
    _emit(InferenceQueue(args.queue_dir).pipeline_status())
    return 0


def _cmd_queue_pipeline_telemetry(args: argparse.Namespace) -> int:
    report = json.loads(open(args.report, "r", encoding="utf-8").read())
    _emit(InferenceQueue(args.queue_dir).record_pipeline_telemetry(report))
    return 0


def _add_queue_worker_args(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("--queue-dir", required=True)
    parser.add_argument("--profiles-dir", required=True)
    parser.add_argument("--runner", choices=RUNNER_CHOICES, default="fake")
    parser.add_argument("--runner-timeout-s", type=int, default=300)
    parser.add_argument("--command", nargs="*")
    parser.add_argument("--node-id")
    parser.add_argument("--topology")
    parser.add_argument("--batch-id")
    parser.add_argument("--limit", type=int, default=1)
    parser.add_argument("--concurrency", type=int, default=1)
    parser.add_argument("--max-node-depth", type=int, default=0, help="For node workers, cap queued+running model claims on this node; 0 disables the cap.")
    parser.add_argument("--batch-linger-s", type=float, default=0.0, help="Wait this long after the newest ready request before dispatching a partial batch.")
    parser.add_argument("--kv-capacity-bytes", type=int, default=0, help="Node-local KV reservation cap; 0 disables the cap.")
    parser.add_argument("--transport-max-attempts", type=int, default=3, help="Requeue transient transport failures until this attempt count, then fail.")
    parser.add_argument("--worker-id")
    parser.add_argument("--lease-ttl-s", type=int, default=900)
    parser.add_argument("--heartbeat-interval-s", type=float, default=5.0)
    parser.add_argument("--loop", action="store_true")
    parser.add_argument("--sleep-s", type=float, default=1.0)
    parser.add_argument("--max-iterations", type=int, default=0)


def _load_jsonl(path: str) -> list[dict]:
    rows: list[dict] = []
    with open(path, "r", encoding="utf-8") as handle:
        for line_number, line in enumerate(handle, start=1):
            if not line.strip():
                continue
            row = json.loads(line)
            if not isinstance(row, dict):
                raise ValueError(f"CPU item line {line_number} must be a JSON object")
            rows.append(row)
    return rows


def _make_runner(kind: str, command: list[str], timeout_s: int, *, topology_path: str | None = None):
    if kind == "fake":
        return FakeRunner()
    if kind == "command":
        return CommandRunner(command, timeout_s=timeout_s)
    if kind == "vllm":
        return VllmOpenAIRunner(timeout_s=timeout_s)
    if kind == "hma":
        return HmaPersistentRunner(timeout_s=timeout_s)
    if kind == "antirez":
        return AntirezRunner(timeout_s=timeout_s)
    if kind == "auto":
        return AutoRunner(timeout_s=timeout_s)
    if kind == "spark":
        return SparkHttpRunner(timeout_s=timeout_s)
    if kind == "pipeline":
        return PipelineOpenAIRunner(timeout_s=timeout_s, base_urls=_pipeline_base_urls(topology_path))
    raise ValueError(f"unknown runner: {kind}")


if __name__ == "__main__":
    sys.exit(main())
