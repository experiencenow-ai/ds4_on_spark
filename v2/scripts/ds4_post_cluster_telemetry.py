#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
from pathlib import Path
import time
from typing import Any
from urllib import request


ROOT = Path(__file__).resolve().parents[1]
DEFAULT_SUMMARY = Path("/tmp/ds4_telemetry/mac/cluster_summary.json")


def main() -> int:
    args = _parse_args()
    summary = json.loads(Path(args.summary_json).read_text(encoding="utf-8"))
    topology = json.loads(Path(args.topology).read_text(encoding="utf-8"))
    report = build_report(summary, topology, service_id=args.service_id)
    if args.dry_run:
        print(json.dumps(report, sort_keys=True))
        return 0
    response = _post_json(args.base_url, "/ds4/pipeline/telemetry", report)
    print(json.dumps(response, sort_keys=True))
    return 0


def build_report(summary: dict[str, Any], topology: dict[str, Any], *, service_id: str) -> dict[str, Any]:
    routing = topology.get("routing_policy") if isinstance(topology.get("routing_policy"), dict) else {}
    services = routing.get("pipeline_services") if isinstance(routing.get("pipeline_services"), dict) else {}
    service = services.get(service_id)
    if not isinstance(service, dict):
        raise ValueError(f"unknown pipeline service_id: {service_id}")
    nodes = summary.get("nodes") if isinstance(summary.get("nodes"), dict) else {}
    node_ids = [str(item) for item in service.get("node_ids", [])]
    partition = [int(item) for item in service.get("layer_partition", [])]
    if len(node_ids) != len(partition):
        raise ValueError(f"service {service_id} node_ids/layer_partition mismatch")
    layer_start = 0
    stages = []
    reported_at = float(summary.get("updated_unix") or time.time())
    for stage_index, (node_id, layer_count) in enumerate(zip(node_ids, partition)):
        node = nodes.get(node_id)
        payload = _node_payload(node if isinstance(node, dict) else {})
        stages.append(
            {
                "service_id": service_id,
                "profile_id": service.get("profile_id"),
                "node_id": node_id,
                "stage_index": stage_index,
                "stage_count": len(node_ids),
                "layer_start": layer_start,
                "layer_end": layer_start + layer_count,
                "reported_at": reported_at,
                "payload": payload,
            }
        )
        layer_start += layer_count
    return {"format": "ds4-cluster-telemetry-bridge-v1", "service_id": service_id, "reported_at": reported_at, "source": str(summary.get("combined_csv") or ""), "stages": stages}


def _node_payload(node: dict[str, Any]) -> dict[str, Any]:
    keys = (
        "sample_count",
        "stale_data",
        "error",
        "fetch_error",
        "last_iso_ts",
        "last_sample_age_s",
        "last_gpu_util_pct",
        "last_gpu_temp_c",
        "last_gpu_power_w",
        "last_mem_used_pct",
        "last_net_rx_mbps",
        "last_net_tx_mbps",
        "last_vllm_metrics_up",
        "last_vllm_requests_running",
        "last_vllm_requests_waiting",
        "last_vllm_generation_tokens_per_s",
        "last_vllm_prompt_tokens_per_s",
        "last_vllm_tokens_per_s",
        "last_vllm_kv_cache_pct",
        "last_vllm_prefix_cache_hit_pct",
        "last_vllm_external_prefix_cache_hit_pct",
        "last_local_queue_depth",
        "last_local_queue_running",
        "last_local_queue_completion_tok_s",
        "last_local_queue_prompt_tok_s",
    )
    payload = {key: node.get(key) for key in keys if key in node}
    for group in ("gpu_util_pct", "mem_used_pct", "vllm_generation_tokens_per_s", "vllm_prompt_tokens_per_s", "local_queue_depth", "local_queue_running"):
        value = node.get(group)
        if isinstance(value, dict):
            payload[group] = dict(value)
    return payload


def _post_json(base_url: str, endpoint: str, body: dict[str, Any]) -> dict[str, Any]:
    data = json.dumps(body).encode("utf-8")
    req = request.Request(base_url.rstrip("/") + endpoint, data=data, headers={"content-type": "application/json"}, method="POST")
    with request.urlopen(req, timeout=30) as response:
        return json.loads(response.read().decode("utf-8"))


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Bridge the existing Mac Spark telemetry summary into DS4 pipeline telemetry.")
    parser.add_argument("--summary-json", default=str(DEFAULT_SUMMARY))
    parser.add_argument("--topology", default=str(ROOT / "profiles" / "topology" / "static_sparks.json"))
    parser.add_argument("--base-url", default="http://10.20.0.10:8700")
    parser.add_argument("--service-id", default="dsv4_flash_pp8")
    parser.add_argument("--dry-run", action="store_true")
    return parser.parse_args()


if __name__ == "__main__":
    raise SystemExit(main())
