from __future__ import annotations
import json
from pathlib import Path
from typing import Iterable

from .kv_cache import resolve_request_cache_refs
from .profiles import ProfileRegistry
from .runners import Runner
from .schemas import BATCH_MANIFEST_FORMAT, InferenceRequest
from .topology import SparkTopology

def load_requests_jsonl(path: str | Path) -> list[InferenceRequest]:
    requests: list[InferenceRequest] = []
    request_path = Path(path)
    with request_path.open("r", encoding="utf-8") as handle:
        for line_number, line in enumerate(handle, start=1):
            stripped = line.strip()
            if not stripped:
                continue
            try:
                data = resolve_request_cache_refs(json.loads(stripped), base_dir=request_path.parent)
                requests.append(InferenceRequest.from_json(data))
            except Exception as exc:
                raise ValueError(f"invalid request on line {line_number}: {exc}") from exc
    return requests

def run_requests(*, requests: Iterable[InferenceRequest], registry: ProfileRegistry, runner: Runner, out_dir: str | Path, topology: SparkTopology | None = None) -> dict:
    root = Path(out_dir)
    root.mkdir(parents=True, exist_ok=True)
    responses_path = root / "responses.jsonl"
    failures_path = root / "failures.jsonl"
    manifest_path = root / "batch_manifest.json"
    request_count = completed_count = failed_count = 0
    selected_profiles: dict[str, int] = {}
    selected_nodes: dict[str, int] = {}
    node_load: dict[str, int] = {}
    with responses_path.open("w", encoding="utf-8") as responses, failures_path.open("w", encoding="utf-8") as failures:
        for request in requests:
            request_count += 1
            try:
                profile = registry.resolve(capability=request.capability, chat=request.chat, job_class=request.job_class, model_pin=request.model_pin)
                selected_profiles[profile.profile_id] = selected_profiles.get(profile.profile_id, 0) + 1
                if topology is not None:
                    assignment = topology.assign_profile(profile, immediate=request.immediate, current_load=node_load)
                    node_load[assignment.node_id] = node_load.get(assignment.node_id, 0) + 1
                    selected_nodes[assignment.node_id] = selected_nodes.get(assignment.node_id, 0) + 1
                else:
                    assignment = None
                if assignment is not None:
                    if hasattr(runner, "run_one_on_node"):
                        result = runner.run_one_on_node(request, profile, assignment.node_id)  # type: ignore[attr-defined]
                    else:
                        result = runner.run_one(request, profile)
                    result["selected_node"] = assignment.to_public_dict()
                else:
                    result = runner.run_one(request, profile)
                if result.get("status") == "completed":
                    completed_count += 1
                    responses.write(json.dumps(result, sort_keys=True) + "\n")
                else:
                    failed_count += 1
                    failures.write(json.dumps(result, sort_keys=True) + "\n")
            except Exception as exc:
                failed_count += 1
                failures.write(json.dumps({"format": "ds4-inference-failure-v1", "request_id": request.request_id, "status": "failed_before_runner", "error": str(exc)}, sort_keys=True) + "\n")
    manifest = {"format": BATCH_MANIFEST_FORMAT, "state": "completed" if failed_count == 0 else "completed_with_failures", "request_count": request_count, "completed_count": completed_count, "failed_count": failed_count, "selected_profiles": selected_profiles, "selected_nodes": selected_nodes, "topology_id": topology.topology_id if topology is not None else None, "responses_path": str(responses_path), "failures_path": str(failures_path)}
    manifest_path.write_text(json.dumps(manifest, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return manifest
