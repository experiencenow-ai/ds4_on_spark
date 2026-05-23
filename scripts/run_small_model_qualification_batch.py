#!/usr/bin/env python3
from __future__ import annotations

import argparse
import datetime
import json
import re
import sys
import time
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from scripts.qualify_small_model import DEFAULT_EVAL_SET
from scripts.qualify_small_model import DEFAULT_LLAMA_CLI
from scripts.qualify_small_model import DEFAULT_TRANSFORMERS_DOCKER_IMAGE
from scripts.qualify_small_model import DEFAULT_TRANSFORMERS_MODEL_MOUNT
from scripts.qualify_small_model import DEFAULT_TRANSFORMERS_PYTHON
from scripts.qualify_small_model import cost_proxy
from scripts.qualify_small_model import load_eval_set
from scripts.qualify_small_model import qualify_model
from scripts.qualify_small_model import write_json


FORMAT = "small-model-qualification-batch-v1"
FAILURE_FORMAT = "small-model-qualification-v1"


def utc_now() -> str:
    return datetime.datetime.now(datetime.timezone.utc).isoformat().replace("+00:00", "Z")


def slug(text: str) -> str:
    return re.sub(r"[^A-Za-z0-9_.-]+", "-", text).strip("-")


def load_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def failure_record(model: dict[str, Any], eval_set_id: str, reason: str) -> dict[str, Any]:
    return {
        "format": FAILURE_FORMAT,
        "qualification_timestamp": utc_now(),
        "hardware_node": model.get("hardware_node") or "spark2",
        "model_id": model.get("model_id"),
        "model_path": model.get("model_path"),
        "model_size_params": model.get("model_size_params"),
        "model_dtype": model.get("model_dtype") or "unknown",
        "serve_backend": model.get("serve_backend") or "unknown",
        "eval_set_id": eval_set_id,
        "status": "failed",
        "failure_reason": reason,
        "per_prompt_results": [],
        "aggregate_metrics": {"prompt_count": 0, "pass_count": 0, "pass_rate": 0.0, "mean_tok_s": 0.0, "median_tok_s": 0.0, "p50_latency_ms": 0.0, "p95_latency_ms": 0.0},
        "cost_proxy_estimate": cost_proxy(model.get("model_size_params"), 0.0),
    }


def qualify_or_fail(model: dict[str, Any], eval_set: dict[str, Any], host: str, llama_cli: str, timeout_seconds: float, transformers_python: str = DEFAULT_TRANSFORMERS_PYTHON, transformers_docker_image: str = DEFAULT_TRANSFORMERS_DOCKER_IMAGE, transformers_model_mount: str = DEFAULT_TRANSFORMERS_MODEL_MOUNT) -> dict[str, Any]:
    backend = model.get("serve_backend")
    if backend not in {"llama.cpp", "transformers"}:
        return failure_record(model, eval_set["eval_set_id"], f"unsupported serve_backend for live qualification: {backend}")
    if backend == "llama.cpp" and not model.get("can_serve_request"):
        return failure_record(model, eval_set["eval_set_id"], "model is not marked can_serve_request in inventory")
    try:
        record = qualify_model(model, eval_set, host, llama_cli, timeout_seconds=timeout_seconds, transformers_python=transformers_python, transformers_docker_image=transformers_docker_image, transformers_model_mount=transformers_model_mount)
    except Exception as exc:
        return failure_record(model, eval_set["eval_set_id"], f"qualification failed: {exc}")
    record["status"] = "passed"
    return record


def ranking(records: list[dict[str, Any]], metric: str, reverse: bool) -> list[dict[str, Any]]:
    rows = []
    for record in records:
        aggregate = record.get("aggregate_metrics") or {}
        cost = record.get("cost_proxy_estimate") or {}
        value = cost.get("score") if metric == "cost_proxy" else aggregate.get(metric)
        if value is None:
            continue
        rows.append({"model_id": record.get("model_id"), "status": record.get("status"), metric: value})
    return sorted(rows, key=lambda item: item[metric], reverse=reverse)


def build_summary(records: list[dict[str, Any]], inventory: dict[str, Any], output_dir: Path, started: float) -> dict[str, Any]:
    failures = [record for record in records if record.get("status") != "passed"]
    return {
        "format": FORMAT,
        "batch_timestamp": utc_now(),
        "hardware_node": inventory.get("hardware_node") or "spark2",
        "inventory_model_count": int(inventory.get("model_count") or len(inventory.get("models") or [])),
        "record_count": len(records),
        "passed_record_count": len(records) - len(failures),
        "failure_count": len(failures),
        "wall_clock_seconds": round(max(time.perf_counter() - started, 0.000001), 3),
        "record_dir": str(output_dir),
        "top_by_pass_rate": ranking(records, "pass_rate", True)[:10],
        "top_by_mean_tok_s": ranking(records, "mean_tok_s", True)[:10],
        "top_by_cost_proxy": ranking(records, "cost_proxy", False)[:10],
        "failed_models": [{"model_id": record.get("model_id"), "reason": record.get("failure_reason") or "failed prompts"} for record in failures],
    }


def write_results_doc(path: Path, summary: dict[str, Any]) -> None:
    passed_record_count = int(summary.get("passed_record_count", int(summary["record_count"]) - int(summary["failure_count"])))
    lines = [
        "# Small Model Qualification Results",
        "",
        f"Batch timestamp: `{summary['batch_timestamp']}`",
        f"Hardware node: `{summary['hardware_node']}`",
        f"Records: `{summary['record_count']}` of `{summary['inventory_model_count']}` inventory entries",
        f"Executed records: `{passed_record_count}`",
        f"Failures: `{summary['failure_count']}`",
        f"Wall clock seconds: `{summary['wall_clock_seconds']}`",
        "",
        "## Top 3 By Quality",
    ]
    for row in summary["top_by_pass_rate"][:3]:
        lines.append(f"- `{row['model_id']}` pass_rate={row['pass_rate']}")
    lines.append("")
    lines.append("## Top 3 By Mean Tok/s")
    for row in summary["top_by_mean_tok_s"][:3]:
        lines.append(f"- `{row['model_id']}` mean_tok_s={row['mean_tok_s']}")
    lines.append("")
    lines.append("## Top 3 By Cost Proxy")
    for row in summary["top_by_cost_proxy"][:3]:
        lines.append(f"- `{row['model_id']}` cost_proxy={row['cost_proxy']}")
    lines.append("")
    lines.append("## Failed Models")
    for row in summary["failed_models"]:
        lines.append(f"- `{row['model_id']}`: {row['reason']}")
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def run_batch(inventory: dict[str, Any], eval_set: dict[str, Any], output_dir: Path, host: str, llama_cli: str, timeout_seconds: float, limit: int = 0, model_ids: list[str] | None = None, run_id: str = "20260521T1210Z", transformers_python: str = DEFAULT_TRANSFORMERS_PYTHON, transformers_docker_image: str = DEFAULT_TRANSFORMERS_DOCKER_IMAGE, transformers_model_mount: str = DEFAULT_TRANSFORMERS_MODEL_MOUNT, results_doc: Path = Path("docs/SMALL_MODEL_QUALIFICATION_RESULTS.md")) -> dict[str, Any]:
    started = time.perf_counter()
    models = list(inventory.get("models") or [])
    models = sorted(models, key=lambda model: (model.get("serve_backend") != "llama.cpp", model.get("model_size_params") is None, int(model.get("model_size_params") or 10**18), str(model.get("model_id") or "")))
    if model_ids:
        selected = set(model_ids)
        models = [model for model in models if model.get("model_id") in selected]
        missing = sorted(selected - {str(model.get("model_id")) for model in models})
        if missing:
            raise ValueError("model_id not found in inventory: " + ", ".join(missing))
    if limit > 0:
        models = models[:limit]
    records = []
    output_dir.mkdir(parents=True, exist_ok=True)
    for index, model in enumerate(models, start=1):
        record = qualify_or_fail(model, eval_set, host, llama_cli, timeout_seconds, transformers_python, transformers_docker_image, transformers_model_mount)
        record["batch_index"] = index
        record_path = output_dir / f"{index:03d}_{slug(str(record.get('model_id') or 'unknown'))}.json"
        write_json(record_path, record)
        records.append(record)
        print(json.dumps({"index": index, "model_id": record.get("model_id"), "status": record.get("status"), "pass_rate": record.get("aggregate_metrics", {}).get("pass_rate"), "path": str(record_path)}, sort_keys=True), flush=True)
    summary = build_summary(records, inventory, output_dir, started)
    write_json(output_dir / f"batch_summary_spark2_{run_id}.json", summary)
    write_results_doc(results_doc, summary)
    return summary


def main() -> int:
    parser = argparse.ArgumentParser(description="Run small-model qualification for every model in an inventory.")
    parser.add_argument("--inventory", required=True)
    parser.add_argument("--eval-set", default=str(DEFAULT_EVAL_SET))
    parser.add_argument("--output-dir", default="fixtures/small_model_qualification/batch_spark2_20260521T1210Z")
    parser.add_argument("--host", default="spark2")
    parser.add_argument("--llama-cli", default=DEFAULT_LLAMA_CLI)
    parser.add_argument("--transformers-python", default=DEFAULT_TRANSFORMERS_PYTHON)
    parser.add_argument("--transformers-docker-image", default=DEFAULT_TRANSFORMERS_DOCKER_IMAGE)
    parser.add_argument("--transformers-model-mount", default=DEFAULT_TRANSFORMERS_MODEL_MOUNT)
    parser.add_argument("--timeout-seconds", type=float, default=90.0)
    parser.add_argument("--limit", type=int, default=0)
    parser.add_argument("--model-id", action="append", default=[])
    parser.add_argument("--run-id", default="20260521T1210Z")
    parser.add_argument("--results-doc", default="docs/SMALL_MODEL_QUALIFICATION_RESULTS.md")
    args = parser.parse_args()
    inventory = load_json(Path(args.inventory))
    eval_set = load_eval_set(Path(args.eval_set))
    summary = run_batch(inventory, eval_set, Path(args.output_dir), args.host, args.llama_cli, args.timeout_seconds, args.limit, args.model_id, args.run_id, args.transformers_python, args.transformers_docker_image, args.transformers_model_mount, Path(args.results_doc))
    print(json.dumps(summary, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
