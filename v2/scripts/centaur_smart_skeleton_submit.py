#!/usr/bin/env python3
from __future__ import annotations

import argparse
import datetime
import hashlib
import json
import os
import re
import subprocess
import sys
import time
import urllib.request
from collections import Counter, defaultdict
from pathlib import Path
from typing import Any


DEFAULT_PARSED = "/private/tmp/centaur_sidecar_repo_full_latest/finalized/centaur_function_sidecars_all.parsed.jsonl"
DEFAULT_REPORT = "/private/tmp/centaur_sidecar_repo_full_latest/finalized/centaur_function_sidecars_finalize_report.json"
DEFAULT_OUT_ROOT = "/private/tmp/centaur_smart_skeleton_submit"
TASK_FORMAT = "centaur-smart-skeleton-task-v1"
PLAN_FORMAT = "centaur-smart-skeleton-quartet-plan-v1"
WORKER_ROW_FORMAT = "centaur-smart-skeleton-worker-row-v1"

DEFAULT_QUARTETS = [
    {
        "endpoint_id": "spark3_b8q",
        "endpoint": "http://spark3:18400/v1/chat/completions",
        "model": "glm-5.2-quanttrio",
        "label": "spark3_b8q",
    },
    {
        "endpoint_id": "spark7_b8q",
        "endpoint": "http://spark7:18420/v1/chat/completions",
        "model": "glm-5.2-quanttrio-spark7-8-9-a-b8",
        "label": "spark7_b8q",
    },
    {
        "endpoint_id": "sparkb_b8q",
        "endpoint": "http://sparkb:18440/v1/chat/completions",
        "model": "glm-5.2-quanttrio-b-c-0-1-b8-49k",
        "label": "sparkb_b8q",
    },
]


def utc_now() -> str:
    return datetime.datetime.now(datetime.timezone.utc).isoformat().replace("+00:00", "Z")


def json_bytes(obj: Any) -> bytes:
    return json.dumps(obj, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode("utf-8")


def stable_id(prefix: str, obj: Any) -> str:
    return prefix + hashlib.sha256(json_bytes(obj)).hexdigest()[:20]


def safe_name(value: object) -> str:
    text = re.sub(r"[^A-Za-z0-9_.-]+", "-", str(value or "").strip()).strip("-")
    return text or "item"


def clip_text(value: object, limit: int) -> str:
    text = " ".join(str(value or "").split())
    if len(text) <= limit:
        return text
    return text[: max(0, limit - 3)].rstrip() + "..."


def clip_list(value: object, item_limit: int, text_limit: int) -> list[str]:
    if not isinstance(value, list):
        return []
    return [clip_text(item, text_limit) for item in value[:item_limit] if str(item or "").strip()]


def read_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def read_jsonl(path: Path) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    with path.open(encoding="utf-8", errors="replace") as handle:
        for line in handle:
            text = line.strip()
            if text:
                rows.append(json.loads(text))
    return rows


def write_json(path: Path, obj: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(obj, indent=2, sort_keys=True, ensure_ascii=False) + "\n", encoding="utf-8")


def write_jsonl(path: Path, rows: list[dict[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as handle:
        for row in rows:
            handle.write(json.dumps(row, sort_keys=True, separators=(",", ":"), ensure_ascii=False) + "\n")


def append_jsonl(path: Path, row: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(row, sort_keys=True, separators=(",", ":"), ensure_ascii=False) + "\n")
        handle.flush()
        os.fsync(handle.fileno())


def success_sidecars(parsed_path: Path) -> list[dict[str, Any]]:
    rows = []
    for row in read_jsonl(parsed_path):
        annotation = row.get("annotation")
        worker = row.get("worker")
        if isinstance(annotation, dict) and isinstance(worker, dict) and worker.get("status") == "success":
            rows.append(row)
    return rows


def compact_sidecar(row: dict[str, Any]) -> dict[str, Any]:
    ann = row.get("annotation") if isinstance(row.get("annotation"), dict) else {}
    return {
        "sidecar_id": str(row.get("sidecar_id") or ann.get("sidecar_id") or ""),
        "function_name": clip_text(row.get("function_name") or ann.get("function_name"), 120),
        "signature": clip_text(row.get("signature"), 180),
        "line_start": row.get("line_start"),
        "line_end": row.get("line_end"),
        "summary": clip_text(ann.get("summary"), 320),
        "protocol_role": clip_text(ann.get("protocol_role"), 260),
        "state_effects": clip_list(ann.get("state_effects"), 3, 180),
        "invariants": clip_list(ann.get("invariants"), 4, 180),
        "edit_hazards": clip_list(ann.get("edit_hazards"), 3, 180),
        "lookup_tags": clip_list(ann.get("lookup_tags"), 12, 80),
    }


def dominant_category(rows: list[dict[str, Any]]) -> str:
    counts = Counter(str(row.get("category") or "uncategorized") for row in rows)
    return sorted(counts.items(), key=lambda item: (-item[1], item[0]))[0][0]


def source_file_hash(rows: list[dict[str, Any]]) -> str:
    payload = [(row.get("sidecar_id"), row.get("source_sha256")) for row in rows]
    return "sha256:" + hashlib.sha256(json_bytes(payload)).hexdigest()


def make_file_task(source_file: str, rows: list[dict[str, Any]], *, wave: int, artifact_type: str, chunk_index: int | None = None, chunk_count: int | None = None, depends_on_artifacts: list[str] | None = None) -> dict[str, Any]:
    sorted_rows = sorted(rows, key=lambda row: (int(row.get("line_start") or 0), str(row.get("function_name") or "")))
    category_counts = dict(sorted(Counter(str(row.get("category") or "uncategorized") for row in sorted_rows).items()))
    identity = {
        "artifact_type": artifact_type,
        "source_file": source_file,
        "chunk_index": chunk_index,
        "chunk_count": chunk_count,
        "sidecar_ids": [str(row.get("sidecar_id") or "") for row in sorted_rows],
    }
    artifact_id = stable_id("skel-", identity)
    expected_format = "centaur-file-skeleton-v1" if artifact_type == "file_skeleton" else "centaur-file-skeleton-slice-v1"
    instruction = (
        "Summarize this complete file from successful function sidecars."
        if artifact_type == "file_skeleton"
        else "Summarize this slice of a large file from successful function sidecars."
    )
    return {
        "format": TASK_FORMAT,
        "artifact_id": artifact_id,
        "artifact_type": artifact_type,
        "wave": wave,
        "expected_output_format": expected_format,
        "source_file": source_file,
        "category": dominant_category(sorted_rows),
        "weight": len(sorted_rows),
        "source_sidecar_ids": [str(row.get("sidecar_id") or "") for row in sorted_rows],
        "depends_on_artifacts": list(depends_on_artifacts or []),
        "input": {
            "source_file": source_file,
            "category_counts": category_counts,
            "function_count": len(sorted_rows),
            "source_hash": source_file_hash(sorted_rows),
            "chunk_index": chunk_index,
            "chunk_count": chunk_count,
            "sidecars": [compact_sidecar(row) for row in sorted_rows],
        },
        "instruction": instruction,
        "output_schema": file_output_schema(expected_format),
    }


def make_file_reduce_task(source_file: str, rows: list[dict[str, Any]], chunk_ids: list[str]) -> dict[str, Any]:
    identity = {"artifact_type": "file_skeleton_reduce", "source_file": source_file, "chunk_ids": chunk_ids}
    return {
        "format": TASK_FORMAT,
        "artifact_id": stable_id("skel-", identity),
        "artifact_type": "file_skeleton",
        "wave": 2,
        "expected_output_format": "centaur-file-skeleton-v1",
        "source_file": source_file,
        "category": dominant_category(rows),
        "weight": len(rows),
        "source_sidecar_ids": [str(row.get("sidecar_id") or "") for row in rows],
        "depends_on_artifacts": chunk_ids,
        "input": {
            "source_file": source_file,
            "category_counts": dict(sorted(Counter(str(row.get("category") or "uncategorized") for row in rows).items())),
            "function_count": len(rows),
            "source_hash": source_file_hash(rows),
            "dependency_kind": "file_skeleton_slices",
        },
        "instruction": "Merge the file-skeleton slice outputs into one compact whole-file skeleton.",
        "output_schema": file_output_schema("centaur-file-skeleton-v1"),
    }


def file_output_schema(format_name: str) -> dict[str, Any]:
    return {
        "format": format_name,
        "source_file": "path",
        "source_hash": "sha256 over source sidecar hashes",
        "purpose": "one or two compact sentences",
        "owned_concepts": ["concepts owned by this file"],
        "entry_points": [{"symbol": "name", "role": "why it matters", "sidecar_id": "fside-..."}],
        "internal_flow": ["ordered local flow steps"],
        "state_surfaces": ["files, globals, network/cache state touched"],
        "external_dependencies": ["modules, structs, protocols, files depended on"],
        "invariants": ["file-wide invariants"],
        "edit_hazards": ["high-risk future edits"],
        "lookup_tags": ["dense retrieval tags"],
        "confidence": "0.0..1.0",
    }


def module_output_schema() -> dict[str, Any]:
    return {
        "format": "centaur-module-skeleton-v1",
        "module_id": "category/module id",
        "paths": ["dominant paths"],
        "purpose": "subsystem responsibility",
        "runtime_flows": [{"name": "flow", "steps": ["ordered steps"]}],
        "owned_state": ["persistent/runtime state"],
        "public_entry_points": ["symbols or CLI/API surfaces"],
        "cross_module_contracts": ["caller/callee contracts"],
        "critical_invariants": ["must-preserve facts"],
        "known_risks": ["failure modes and audit hot spots"],
        "lookup_tags": ["dense retrieval tags"],
        "confidence": "0.0..1.0",
    }


def repo_output_schema() -> dict[str, Any]:
    return {
        "format": "centaur-repo-capsule-v1",
        "repo": "name or root",
        "purpose": "what the codebase does",
        "subsystems": [{"module_id": "id", "role": "short role", "paths": ["path"]}],
        "runtime_lifecycle": ["8 to 15 ordered steps"],
        "state_map": ["where important state lives"],
        "context_expansion": [{"task": "query kind", "load": ["module ids or artifact types"]}],
        "lookup_tags": ["dense retrieval tags"],
        "confidence": "0.0..1.0",
    }


def build_file_tasks(rows: list[dict[str, Any]], max_sidecars_per_file_task: int) -> tuple[list[dict[str, Any]], dict[str, str]]:
    by_file: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for row in rows:
        by_file[str(row.get("source_file") or "unknown")].append(row)
    tasks: list[dict[str, Any]] = []
    final_file_artifacts: dict[str, str] = {}
    for source_file in sorted(by_file):
        file_rows = by_file[source_file]
        if len(file_rows) <= max_sidecars_per_file_task:
            task = make_file_task(source_file, file_rows, wave=1, artifact_type="file_skeleton")
            tasks.append(task)
            final_file_artifacts[source_file] = str(task["artifact_id"])
            continue
        chunk_ids: list[str] = []
        chunk_count = (len(file_rows) + max_sidecars_per_file_task - 1) // max_sidecars_per_file_task
        sorted_rows = sorted(file_rows, key=lambda row: (int(row.get("line_start") or 0), str(row.get("function_name") or "")))
        for index in range(chunk_count):
            chunk = sorted_rows[index * max_sidecars_per_file_task : (index + 1) * max_sidecars_per_file_task]
            task = make_file_task(source_file, chunk, wave=1, artifact_type="file_skeleton_slice", chunk_index=index, chunk_count=chunk_count)
            tasks.append(task)
            chunk_ids.append(str(task["artifact_id"]))
        reduce_task = make_file_reduce_task(source_file, file_rows, chunk_ids)
        tasks.append(reduce_task)
        final_file_artifacts[source_file] = str(reduce_task["artifact_id"])
    return tasks, final_file_artifacts


def build_module_tasks(rows: list[dict[str, Any]], final_file_artifacts: dict[str, str]) -> list[dict[str, Any]]:
    by_category: dict[str, set[str]] = defaultdict(set)
    file_rows: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for row in rows:
        source_file = str(row.get("source_file") or "unknown")
        category = str(row.get("category") or "uncategorized")
        by_category[category].add(source_file)
        file_rows[source_file].append(row)
    tasks = []
    for category in sorted(by_category):
        files = sorted(by_category[category])
        file_ids = [final_file_artifacts[path] for path in files if path in final_file_artifacts]
        paths = sorted({path.split("/", 1)[0] + "/" if "/" in path else path for path in files})
        identity = {"artifact_type": "module_skeleton", "category": category, "file_ids": file_ids}
        tasks.append(
            {
                "format": TASK_FORMAT,
                "artifact_id": stable_id("skel-", identity),
                "artifact_type": "module_skeleton",
                "wave": 3,
                "expected_output_format": "centaur-module-skeleton-v1",
                "module_id": category,
                "category": category,
                "weight": sum(len(file_rows[path]) for path in files),
                "source_files": files,
                "depends_on_artifacts": file_ids,
                "input": {"module_id": category, "paths": paths, "source_files": files, "file_skeleton_count": len(file_ids)},
                "instruction": "Summarize this subsystem from its successful file skeletons.",
                "output_schema": module_output_schema(),
            }
        )
    return tasks


def build_repo_task(module_tasks: list[dict[str, Any]]) -> dict[str, Any]:
    module_ids = [str(task["artifact_id"]) for task in module_tasks]
    identity = {"artifact_type": "repo_capsule", "module_ids": module_ids}
    return {
        "format": TASK_FORMAT,
        "artifact_id": stable_id("skel-", identity),
        "artifact_type": "repo_capsule",
        "wave": 4,
        "expected_output_format": "centaur-repo-capsule-v1",
        "category": "repo",
        "weight": len(module_tasks),
        "depends_on_artifacts": module_ids,
        "input": {"module_count": len(module_tasks), "module_artifact_ids": module_ids},
        "instruction": "Summarize the whole repository from module skeletons as a compact repo capsule.",
        "output_schema": repo_output_schema(),
    }


def assign_tasks(tasks: list[dict[str, Any]], quartets: list[dict[str, str]]) -> dict[str, list[dict[str, Any]]]:
    assigned = {str(quartet["endpoint_id"]): [] for quartet in quartets}
    load = {str(quartet["endpoint_id"]): 0 for quartet in quartets}
    for task in sorted(tasks, key=lambda item: (-int(item.get("weight") or 1), str(item.get("artifact_id") or ""))):
        endpoint_id = sorted(load.items(), key=lambda item: (item[1], item[0]))[0][0]
        assigned[endpoint_id].append(task)
        load[endpoint_id] += max(1, int(task.get("weight") or 1))
    return assigned


def build_submission_plan(parsed_path: Path, report_path: Path, out_root: Path, *, max_sidecars_per_file_task: int = 80, allow_incomplete: bool = False, quartets: list[dict[str, str]] | None = None) -> dict[str, Any]:
    report = read_json(report_path) if report_path.is_file() else {"ready": False, "totals": {}, "missing_report": str(report_path)}
    rows = success_sidecars(parsed_path)
    file_tasks, final_file_artifacts = build_file_tasks(rows, max_sidecars_per_file_task)
    module_tasks = build_module_tasks(rows, final_file_artifacts)
    repo_task = build_repo_task(module_tasks)
    tasks = file_tasks + module_tasks + [repo_task]
    quartets = list(quartets or DEFAULT_QUARTETS)
    out_root = out_root.resolve()
    task_root = out_root / "tasks"
    waves: dict[str, Any] = {}
    for wave in sorted({int(task["wave"]) for task in tasks}):
        wave_tasks = [task for task in tasks if int(task["wave"]) == wave]
        assignments = assign_tasks(wave_tasks, quartets)
        wave_info = {"task_count": len(wave_tasks), "endpoint_task_counts": {}, "endpoint_weights": {}, "task_paths": {}}
        for endpoint_id, endpoint_tasks in assignments.items():
            path = task_root / f"wave_{wave}" / f"{endpoint_id}.jsonl"
            write_jsonl(path, endpoint_tasks)
            wave_info["endpoint_task_counts"][endpoint_id] = len(endpoint_tasks)
            wave_info["endpoint_weights"][endpoint_id] = sum(max(1, int(task.get("weight") or 1)) for task in endpoint_tasks)
            wave_info["task_paths"][endpoint_id] = str(path)
        waves[str(wave)] = wave_info
    all_tasks_path = task_root / "all_tasks.jsonl"
    write_jsonl(all_tasks_path, tasks)
    docs_prefix_path = out_root / "smart_skeleton_docs_prefix.txt"
    docs_prefix_path.write_text(skeleton_docs_prefix(), encoding="utf-8")
    manifest = {
        "format": PLAN_FORMAT,
        "created_at": utc_now(),
        "parsed_path": str(parsed_path),
        "report_path": str(report_path),
        "report_ready": bool(report.get("ready")),
        "allow_incomplete": bool(allow_incomplete),
        "report_totals": report.get("totals", {}),
        "out_root": str(out_root),
        "docs_prefix_path": str(docs_prefix_path),
        "all_tasks_path": str(all_tasks_path),
        "quartets": quartets,
        "waves": waves,
        "task_counts": dict(sorted(Counter(str(task["artifact_type"]) for task in tasks).items())),
        "total_tasks": len(tasks),
        "source_file_count": len(final_file_artifacts),
        "success_sidecar_count": len(rows),
        "max_sidecars_per_file_task": max_sidecars_per_file_task,
    }
    manifest_path = out_root / "manifest.json"
    manifest["manifest_path"] = str(manifest_path)
    write_json(manifest_path, manifest)
    write_launch_commands(out_root / "launch_commands.sh", manifest)
    return manifest


def skeleton_docs_prefix() -> str:
    return "\n".join(
        [
            "centaur-smart-skeleton-builder-v1",
            "Use only provided successful sidecars, child skeletons, and metadata.",
            "Do not invent APIs, structs, fields, or runtime behavior.",
            "Return exactly one JSON object. No markdown fences or prose.",
            "If inputs disagree, record the disagreement in known_risks or edit_hazards.",
            "Keep summaries compact and retrieval-friendly.",
            "",
        ]
    )


def write_launch_commands(path: Path, manifest: dict[str, Any]) -> None:
    script = Path(__file__).as_posix()
    lines = ["#!/usr/bin/env bash", "set -euo pipefail", ""]
    for wave in sorted(int(key) for key in manifest["waves"]):
        lines.append(f"python3 {script} launch --manifest {manifest['manifest_path']} --wave {wave}")
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    path.chmod(0o755)


def _json_object_from_text(text: str) -> dict[str, Any] | None:
    raw = text.strip()
    if raw.startswith("```"):
        lines = raw.splitlines()
        if len(lines) >= 3 and lines[-1].strip().startswith("```"):
            raw = "\n".join(lines[1:-1]).strip()
    try:
        obj = json.loads(raw)
        return obj if isinstance(obj, dict) else None
    except json.JSONDecodeError:
        pass
    start = raw.find("{")
    end = raw.rfind("}")
    if start >= 0 and end > start:
        try:
            obj = json.loads(raw[start : end + 1])
            return obj if isinstance(obj, dict) else None
        except json.JSONDecodeError:
            return None
    return None


def completed_artifacts(jsonl_path: Path) -> set[str]:
    done = set()
    if not jsonl_path.is_file():
        return done
    for row in read_jsonl(jsonl_path):
        if row.get("status") == "success" and row.get("artifact_id"):
            done.add(str(row["artifact_id"]))
    return done


def dependency_outputs(out_root: Path, artifact_ids: list[str]) -> tuple[list[dict[str, Any]], list[str]]:
    wanted = set(artifact_ids)
    found: dict[str, dict[str, Any]] = {}
    for path in sorted((out_root / "results").glob("**/annotations.jsonl")):
        for row in read_jsonl(path):
            artifact_id = str(row.get("artifact_id") or "")
            if artifact_id in wanted and row.get("status") == "success" and isinstance(row.get("parsed"), dict):
                found[artifact_id] = row["parsed"]
    missing = sorted(wanted - set(found))
    return [found[artifact_id] for artifact_id in artifact_ids if artifact_id in found], missing


def build_payload(model: str, docs_prefix: str, task: dict[str, Any], deps: list[dict[str, Any]], max_tokens: int) -> dict[str, Any]:
    user = {"task": task, "dependency_outputs": deps}
    return {
        "model": model,
        "messages": [
            {"role": "system", "content": docs_prefix},
            {"role": "user", "content": json.dumps(user, sort_keys=True, separators=(",", ":"), ensure_ascii=False)},
        ],
        "max_tokens": int(max_tokens),
        "temperature": 0.0,
        "stream": True,
        "stream_options": {"include_usage": True},
        "chat_template_kwargs": {"enable_thinking": False},
    }


def stream_task(args: argparse.Namespace, manifest: dict[str, Any], task: dict[str, Any], jsonl_path: Path) -> dict[str, Any]:
    out_root = Path(str(manifest["out_root"]))
    artifact_id = str(task["artifact_id"])
    started_at = utc_now()
    started = time.time()
    deps, missing = dependency_outputs(out_root, [str(item) for item in task.get("depends_on_artifacts", [])])
    if missing:
        row = worker_row(task, started_at, started, "blocked", "", None, {}, "missing dependencies: " + ", ".join(missing))
        append_jsonl(jsonl_path, row)
        return row
    docs_prefix = Path(str(manifest["docs_prefix_path"])).read_text(encoding="utf-8")
    payload = build_payload(str(args.model), docs_prefix, task, deps, int(args.max_tokens))
    data = json.dumps(payload, separators=(",", ":"), ensure_ascii=False).encode("utf-8")
    request = urllib.request.Request(str(args.endpoint), data=data, headers={"Content-Type": "application/json"}, method="POST")
    content_parts: list[str] = []
    usage: dict[str, Any] = {}
    finish_reason = ""
    error = ""
    try:
        with urllib.request.urlopen(request, timeout=float(args.timeout_seconds)) as response:
            for raw_line in response:
                line = raw_line.decode("utf-8", errors="replace").strip()
                if not line.startswith("data:"):
                    continue
                payload_text = line[len("data:") :].strip()
                if payload_text == "[DONE]":
                    break
                try:
                    chunk = json.loads(payload_text)
                except json.JSONDecodeError:
                    continue
                if isinstance(chunk.get("usage"), dict):
                    usage = chunk["usage"]
                choices = chunk.get("choices") if isinstance(chunk.get("choices"), list) else []
                if not choices or not isinstance(choices[0], dict):
                    continue
                choice = choices[0]
                if choice.get("finish_reason"):
                    finish_reason = str(choice.get("finish_reason") or "")
                delta = choice.get("delta") if isinstance(choice.get("delta"), dict) else {}
                text = str(delta.get("content") or "")
                if text:
                    content_parts.append(text)
    except Exception as exc:
        error = str(exc)
    content = "".join(content_parts).strip()
    parsed = _json_object_from_text(content)
    status = "success" if parsed is not None and not error else "raw" if content and not error else "error"
    row = worker_row(task, started_at, started, status, content, parsed, {"usage": usage, "finish_reason": finish_reason}, error)
    partial_dir = jsonl_path.parent / "final"
    partial_dir.mkdir(parents=True, exist_ok=True)
    write_json(partial_dir / f"{safe_name(artifact_id)}.json", row)
    append_jsonl(jsonl_path, row)
    return row


def worker_row(task: dict[str, Any], started_at: str, started: float, status: str, content: str, parsed: dict[str, Any] | None, extra: dict[str, Any], error: str) -> dict[str, Any]:
    schema_issues = []
    expected = str(task.get("expected_output_format") or "")
    if isinstance(parsed, dict) and expected and parsed.get("format") != expected:
        schema_issues.append(f"format mismatch: expected {expected}")
    return {
        "format": WORKER_ROW_FORMAT,
        "status": status,
        "artifact_id": str(task.get("artifact_id") or ""),
        "artifact_type": str(task.get("artifact_type") or ""),
        "wave": int(task.get("wave") or 0),
        "started_at": started_at,
        "finished_at": utc_now(),
        "duration_ms": int((time.time() - started) * 1000),
        "content": content,
        "parsed": parsed,
        "schema_issues": schema_issues,
        "error": error,
        **extra,
    }


def run_worker(args: argparse.Namespace) -> int:
    manifest = read_json(Path(args.manifest))
    tasks = read_jsonl(Path(args.tasks))
    out_dir = Path(args.out_dir)
    jsonl_path = out_dir / "annotations.jsonl"
    done = set() if args.no_resume else completed_artifacts(jsonl_path)
    out_dir.mkdir(parents=True, exist_ok=True)
    print(f"tasks={len(tasks)} done={len(done)} out={jsonl_path}", flush=True)
    for task in tasks:
        artifact_id = str(task.get("artifact_id") or "")
        if artifact_id in done:
            print(f"skip {artifact_id}", flush=True)
            continue
        row = stream_task(args, manifest, task, jsonl_path)
        print(f"{row['status']} wave={row['wave']} {row['artifact_type']} {artifact_id} {row['duration_ms']}ms", flush=True)
    return 0


def metrics_url(endpoint: str) -> str:
    return endpoint.split("/v1/chat/completions", 1)[0].rstrip("/") + "/metrics"


def endpoint_idle(endpoint: str, timeout: float = 5.0) -> tuple[bool, str]:
    url = metrics_url(endpoint)
    try:
        with urllib.request.urlopen(url, timeout=timeout) as response:
            text = response.read().decode("utf-8", errors="replace")
    except Exception as exc:
        return False, f"metrics unavailable {url}: {exc}"
    try:
        obj = json.loads(text)
        running = int(obj.get("running", 0))
        waiting = int(obj.get("waiting", 0))
    except Exception:
        running_match = re.search(r"\brunning\b[^0-9]*(\d+)", text)
        waiting_match = re.search(r"\bwaiting\b[^0-9]*(\d+)", text)
        running = int(running_match.group(1)) if running_match else 0
        waiting = int(waiting_match.group(1)) if waiting_match else 0
    return running == 0 and waiting == 0, f"running={running} waiting={waiting}"


def launch(args: argparse.Namespace) -> int:
    manifest = read_json(Path(args.manifest))
    if not manifest.get("report_ready") and not (manifest.get("allow_incomplete") or args.allow_incomplete):
        print("refusing launch: finalizer report is not ready; pass --allow-incomplete to override", file=sys.stderr)
        return 2
    wave = str(args.wave)
    if wave not in manifest["waves"]:
        print(f"unknown wave {wave}", file=sys.stderr)
        return 2
    out_root = Path(str(manifest["out_root"]))
    logs_dir = out_root / "logs"
    pids_dir = out_root / "pids"
    logs_dir.mkdir(parents=True, exist_ok=True)
    pids_dir.mkdir(parents=True, exist_ok=True)
    launched = []
    quartets = {str(item["endpoint_id"]): item for item in manifest["quartets"]}
    for endpoint_id, task_path in sorted(manifest["waves"][wave]["task_paths"].items()):
        quartet = quartets[endpoint_id]
        if not args.skip_metrics:
            idle, detail = endpoint_idle(str(quartet["endpoint"]))
            if not idle:
                print(f"refusing {endpoint_id}: endpoint busy or down ({detail})", file=sys.stderr)
                return 3
        tasks = read_jsonl(Path(task_path))
        for lane in range(max(1, int(args.lanes))):
            shard = tasks[lane :: max(1, int(args.lanes))]
            if not shard:
                continue
            shard_path = out_root / "shards" / f"wave_{wave}" / endpoint_id / f"lane_{lane}.jsonl"
            write_jsonl(shard_path, shard)
            result_dir = out_root / "results" / endpoint_id / f"wave_{wave}" / f"lane_{lane}"
            log_path = logs_dir / f"{endpoint_id}_wave_{wave}_lane_{lane}.log"
            pid_path = pids_dir / f"{endpoint_id}_wave_{wave}_lane_{lane}.pid"
            cmd = [
                sys.executable,
                str(Path(__file__).resolve()),
                "worker",
                "--manifest",
                str(Path(args.manifest).resolve()),
                "--tasks",
                str(shard_path),
                "--out-dir",
                str(result_dir),
                "--endpoint",
                str(quartet["endpoint"]),
                "--model",
                str(quartet["model"]),
                "--max-tokens",
                str(args.max_tokens),
                "--timeout-seconds",
                str(args.timeout_seconds),
            ]
            with log_path.open("ab", buffering=0) as log:
                proc = subprocess.Popen(cmd, cwd=str(Path(__file__).resolve().parents[2]), stdout=log, stderr=log, start_new_session=True)
            pid_path.write_text(str(proc.pid) + "\n", encoding="utf-8")
            launched.append({"endpoint_id": endpoint_id, "lane": lane, "pid": proc.pid, "tasks": len(shard), "log_path": str(log_path), "pid_path": str(pid_path)})
    summary = {"format": "centaur-smart-skeleton-launch-v1", "created_at": utc_now(), "manifest": args.manifest, "wave": int(wave), "launched": launched}
    write_json(out_root / f"launch_wave_{wave}_{safe_name(utc_now())}.json", summary)
    print(json.dumps(summary, indent=2, sort_keys=True))
    return 0


def parse_args(argv: list[str]) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Plan and launch Centaur smart-skeleton work across the three QuantTrio quartets.")
    sub = parser.add_subparsers(dest="command", required=True)
    plan = sub.add_parser("plan")
    plan.add_argument("--parsed", default=DEFAULT_PARSED)
    plan.add_argument("--report", default=DEFAULT_REPORT)
    plan.add_argument("--out-root", default=DEFAULT_OUT_ROOT)
    plan.add_argument("--max-sidecars-per-file-task", type=int, default=80)
    plan.add_argument("--allow-incomplete", action="store_true")
    launch_parser = sub.add_parser("launch")
    launch_parser.add_argument("--manifest", required=True)
    launch_parser.add_argument("--wave", required=True)
    launch_parser.add_argument("--lanes", type=int, default=8)
    launch_parser.add_argument("--max-tokens", type=int, default=1800)
    launch_parser.add_argument("--timeout-seconds", type=float, default=7200.0)
    launch_parser.add_argument("--allow-incomplete", action="store_true")
    launch_parser.add_argument("--skip-metrics", action="store_true")
    worker = sub.add_parser("worker")
    worker.add_argument("--manifest", required=True)
    worker.add_argument("--tasks", required=True)
    worker.add_argument("--out-dir", required=True)
    worker.add_argument("--endpoint", required=True)
    worker.add_argument("--model", required=True)
    worker.add_argument("--max-tokens", type=int, default=1800)
    worker.add_argument("--timeout-seconds", type=float, default=7200.0)
    worker.add_argument("--no-resume", action="store_true")
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(list(argv or sys.argv[1:]))
    if args.command == "plan":
        manifest = build_submission_plan(
            Path(args.parsed),
            Path(args.report),
            Path(args.out_root),
            max_sidecars_per_file_task=int(args.max_sidecars_per_file_task),
            allow_incomplete=bool(args.allow_incomplete),
        )
        print(json.dumps(manifest, indent=2, sort_keys=True))
        return 0
    if args.command == "launch":
        return launch(args)
    if args.command == "worker":
        return run_worker(args)
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
