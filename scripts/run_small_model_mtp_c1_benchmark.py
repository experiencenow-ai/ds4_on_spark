#!/usr/bin/env python3
from __future__ import annotations

import argparse
import datetime
import hashlib
import json
import re
import shlex
import sys
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from scripts.qualify_small_model import default_command_runner, find_model, load_json, write_json


FORMAT = "small-model-mtp-c1-benchmark-v1"
DEFAULT_INVENTORY = Path("fixtures/small_model_qualification/inventory_spark2_20260521T1155Z.json")
DEFAULT_LLAMA_CLI = "/home/spark2/src/llama.cpp-kamnxt-master/build-rpc-cuda-nvcc/bin/llama-cli"
DEFAULT_MODELS = ["ds4-DeepSeek-V4-Flash-MTP-Q4K-Q8_0-F32", "qwen36_mtp-Qwen3.6-27B-MTP-Q8_0", "qwen36_mtp_q4-Qwen3.6-27B-MTP-Q4_K_M"]


def sha256_text(text: str) -> str:
    return "sha256:" + hashlib.sha256(text.encode("utf-8")).hexdigest()


def centaur_prompts() -> list[dict[str, Any]]:
    prompts: list[dict[str, Any]] = []
    asks = [
        "identify the duplicate helper and the shared abstraction",
        "rank the maintainability risk and give one bounded fix",
        "choose the safest provider lane and explain the rejected option",
        "classify the request as full_vocab chat or constrained output",
        "decide pass/fail and give the shortest supporting reason",
    ]
    context = "Centaur promotes state machines only after deterministic verification, measured artifacts, and no invented throughput. "
    for index in range(50):
        prompt = (
            f"You are a local Centaur worker. Task {index + 1}/50.\n"
            f"{context * 7}\n"
            f"Signal: file_{index % 9}.py repeats parsing code, provider_{index % 4} has evidence level {index % 3}, "
            f"and issue #{1325 + index} needs a concise operational answer.\n"
            f"Question: {asks[index % len(asks)]}. Answer in two short sentences."
        )
        prompts.append({"task_id": f"centaur_{index + 1:02d}", "prompt": prompt, "max_tokens": 32})
    return prompts


def command_for(host: str, llama_cli: str, model_path: str, prompt: dict[str, Any], mtp_k: int, timeout_seconds: float) -> list[str]:
    remote = ["timeout", "-k", "5s", str(int(timeout_seconds)), llama_cli, "-m", model_path, "-p", str(prompt["prompt"]), "-n", str(prompt["max_tokens"]), "--temp", "0", "--no-display-prompt", "--single-turn", "--simple-io", "--show-timings", "--no-warmup"]
    if mtp_k > 0:
        remote += ["--draft", str(mtp_k), "--draft-min", str(mtp_k)]
    return ["ssh", "-o", "BatchMode=yes", "-o", "ConnectTimeout=8", host, shlex.join(remote)]


def classify(stderr: str, stdout: str, returncode: int) -> tuple[str, str]:
    text = (stderr + "\n" + stdout).strip()
    if returncode == 0:
        return ("none", "")
    checks = [
        ("unknown model architecture", "runtime_unsupported_architecture"),
        ("missing tensor", "checkpoint_missing_tensor"),
        ("not within the file bounds", "checkpoint_corrupt_or_incomplete"),
        ("corrupted or incomplete", "checkpoint_corrupt_or_incomplete"),
        ("CUDA error: out of memory", "cuda_out_of_memory"),
        ("timeout expired", "timeout"),
    ]
    for needle, kind in checks:
        if needle in text:
            return (kind, text[-900:])
    return ("command_failed", text[-900:])


def parse_perf(stderr: str, stdout: str) -> dict[str, Any]:
    text = stderr + "\n" + stdout
    total = re.search(r"total time\s*=\s*([0-9.]+)\s*ms\s*/\s*(\d+)\s*tokens", text)
    drafted = sum(int(m.group(1)) for m in re.finditer(r"(?:drafted|attempted(?:_draft_tokens)?)\D+(\d+)", text, re.IGNORECASE))
    committed = sum(int(m.group(1)) for m in re.finditer(r"(?:accepted|committed|accept(?:ed)?_draft_tokens)\D+(\d+)", text, re.IGNORECASE))
    return {
        "total_ms": float(total.group(1)) if total else None,
        "total_tokens": int(total.group(2)) if total else 0,
        "accepted_draft_tokens": committed,
        "attempted_draft_tokens": drafted,
        "draft_acceptance_rate": (committed / drafted) if drafted > 0 else None,
    }


def run_cell(model: dict[str, Any], prompts: list[dict[str, Any]], host: str, llama_cli: str, mtp_k: int, timeout_seconds: float) -> dict[str, Any]:
    rows: list[dict[str, Any]] = []
    for prompt in prompts:
        command = command_for(host, llama_cli, str(model["model_path"]), prompt, mtp_k, timeout_seconds)
        result = default_command_runner(command, timeout_seconds)
        stderr = str(result.get("stderr") or "")
        stdout = str(result.get("stdout") or "")
        kind, detail = classify(stderr, stdout, int(result.get("returncode") or 0))
        perf = parse_perf(stderr, stdout)
        tokens = int(perf["total_tokens"])
        elapsed = float(result.get("elapsed_seconds") or 0.0)
        rows.append({"task_id": prompt["task_id"], "prompt_sha256": sha256_text(str(prompt["prompt"])), "returncode": int(result.get("returncode") or 0), "latency_ms": round(elapsed * 1000, 3), "tok_s": (tokens / elapsed) if elapsed > 0 and kind == "none" else 0.0, "blocker_kind": kind, "blocker_detail": detail, "stderr_tail": stderr[-1200:], "stdout_tail": stdout[-1200:], "perf": perf, "command": " ".join(shlex.quote(part) for part in command)})
        if kind != "none":
            break
    good = [row for row in rows if row["blocker_kind"] == "none"]
    attempted = sum(int(row["perf"]["attempted_draft_tokens"]) for row in rows)
    accepted = sum(int(row["perf"]["accepted_draft_tokens"]) for row in rows)
    blocker = next((row for row in rows if row["blocker_kind"] != "none"), None)
    return {"model_id": model["model_id"], "model_path": model["model_path"], "mtp_k": mtp_k, "planned_prompt_count": len(prompts), "executed_prompt_count": len(rows), "successful_prompt_count": len(good), "status": "passed" if len(good) == len(prompts) else "blocked", "tok_s_mean": sum(float(row["tok_s"]) for row in good) / len(good) if good else 0.0, "draft_acceptance_rate": (accepted / attempted) if attempted > 0 else None, "accepted_draft_tokens": accepted, "attempted_draft_tokens": attempted, "blocker_kind": blocker["blocker_kind"] if blocker else "none", "blocker_detail": blocker["blocker_detail"] if blocker else "", "per_prompt_results": rows}


def build_record(inventory: dict[str, Any], model_ids: list[str], k_values: list[int], host: str, llama_cli: str, timeout_seconds: float, run_id: str) -> dict[str, Any]:
    prompts = centaur_prompts()
    cells = [run_cell(find_model(inventory, model_id), prompts, host, llama_cli, mtp_k, timeout_seconds) for model_id in model_ids for mtp_k in k_values]
    return {"format": FORMAT, "run_id": run_id, "created_at": datetime.datetime.now(datetime.timezone.utc).isoformat().replace("+00:00", "Z"), "hardware_node": host, "llama_cli": llama_cli, "prompt_workload": "centaur_shape_50x500_tokenish_c1", "prompt_count": len(prompts), "prompt_hashes": [sha256_text(str(prompt["prompt"])) for prompt in prompts], "model_ids": model_ids, "k_values": k_values, "cells": cells, "blocker_kind": "none" if all(cell["status"] == "passed" for cell in cells) else "one_or_more_cells_blocked"}


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--inventory", default=str(DEFAULT_INVENTORY))
    parser.add_argument("--output-dir", default="fixtures/small_model_mtp")
    parser.add_argument("--host", default="spark2")
    parser.add_argument("--llama-cli", default=DEFAULT_LLAMA_CLI)
    parser.add_argument("--timeout-seconds", type=float, default=180.0)
    parser.add_argument("--model-id", action="append", default=[])
    parser.add_argument("--mtp-k", action="append", type=int, default=[])
    parser.add_argument("--run-id", default=datetime.datetime.now(datetime.timezone.utc).strftime("%Y%m%dT%H%M%SZ"))
    args = parser.parse_args()
    record = build_record(load_json(Path(args.inventory)), args.model_id or DEFAULT_MODELS, args.mtp_k or [0, 2, 4], args.host, args.llama_cli, args.timeout_seconds, args.run_id)
    path = Path(args.output_dir) / f"{record['run_id']}.json"
    write_json(path, record)
    summary = [{"model_id": c["model_id"], "mtp_k": c["mtp_k"], "status": c["status"], "tok_s_mean": c["tok_s_mean"], "draft_acceptance_rate": c["draft_acceptance_rate"], "blocker_kind": c["blocker_kind"]} for c in record["cells"]]
    print(json.dumps({"artifact": str(path), "format": FORMAT, "blocker_kind": record["blocker_kind"], "cells": summary}, indent=2, sort_keys=True))
    return 0 if record["blocker_kind"] == "none" else 1


if __name__ == "__main__":
    raise SystemExit(main())
