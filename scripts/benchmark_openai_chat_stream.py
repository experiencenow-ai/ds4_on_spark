#!/usr/bin/env python3
"""Benchmark an OpenAI-compatible streaming chat endpoint.

Inspired by AEON-7's public DGX Spark DFlash benchmark methodology:
stream responses, measure true TTFT, use greedy decoding, and compute decode
throughput from the server's streamed usage block when available.
"""

from __future__ import annotations

import argparse
import concurrent.futures
import csv
import json
import os
import statistics
import sys
import time
import urllib.error
import urllib.request
from dataclasses import dataclass
from typing import Any, Dict, Iterable, List, Optional


@dataclass(frozen=True)
class Prompt:
    name: str
    category: str
    text: str
    max_tokens: int


PROMPTS: List[Prompt] = [
    Prompt("warmup", "warmup", "Reply with exactly: OK", 8),
    Prompt("decode_short", "decode", "Explain computational complexity to a CS student in one compact paragraph.", 180),
    Prompt("math_word", "math", "A bat and ball cost $1.10 total. The bat costs $1.00 more than the ball. What does the ball cost? Show concise reasoning.", 160),
    Prompt("code_python", "code", "Write a Python function fib(n) using memoization. Include two tiny assertions.", 260),
    Prompt("code_sql", "code", "Given customers(id,name) and orders(id,customer_id,total), write SQL for the top 3 customers by total spend.", 220),
    Prompt("reasoning", "reasoning", "All bloops are razzles. All razzles are lazzles. Are all bloops lazzles? Answer with a short proof.", 160),
    Prompt("json_extract", "extraction", "Return JSON only with keys verdict, confidence, and reasons for: Model A is faster; Model B is more accurate; choose a deployment winner.", 160),
    Prompt("judge_short", "judge", "Two models answer a task. A is correct but verbose. B is concise but misses one constraint. Pick A or B and give one sentence.", 120),
]


def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--endpoint", default=os.environ.get("OPENAI_CHAT_ENDPOINT", "http://localhost:8000/v1/chat/completions"))
    p.add_argument("--model", default=os.environ.get("OPENAI_MODEL", "aeon-ultimate"))
    p.add_argument("--api-key", default=os.environ.get("OPENAI_API_KEY", os.environ.get("VLLM_API_KEY", "")))
    p.add_argument("--thinking", choices=("off", "on"), default=os.environ.get("BENCH_THINKING", "off"))
    p.add_argument("--temperature", type=float, default=0.0)
    p.add_argument("--concurrency", type=int, default=1)
    p.add_argument("--timeout", type=float, default=600.0)
    p.add_argument("--max-prompts", type=int, default=0, help="limit prompt count after filtering; 0 means all")
    p.add_argument("--category", action="append", default=[], help="include only this category; repeatable")
    p.add_argument("--out-dir", default=os.environ.get("OUT_DIR", ""), help="optional output directory; sets default jsonl/csv/summary paths inside it")
    p.add_argument("--jsonl-out", default="")
    p.add_argument("--csv-out", default="")
    p.add_argument("--summary-json-out", default="", help="optional path to write a machine-readable summary JSON")
    p.add_argument("--baseline-summary-out", default="", help="optional path to write a baseline key=value summary block (for MODEL_RUNS_CSV ingestion)")
    return(p.parse_args())


def selected_prompts(args: argparse.Namespace) -> List[Prompt]:
    prompts = PROMPTS
    if args.category:
        wanted = set(args.category)
        prompts = [p for p in prompts if p.category in wanted]
    if args.max_prompts > 0:
        prompts = prompts[:args.max_prompts]
    return(prompts)


def payload_for(args: argparse.Namespace, prompt: Prompt) -> Dict[str, Any]:
    payload: Dict[str, Any] = {
        "model": args.model,
        "messages": [{"role": "user", "content": prompt.text}],
        "max_tokens": prompt.max_tokens,
        "temperature": args.temperature,
        "stream": True,
        "stream_options": {"include_usage": True},
    }
    if args.thinking == "off":
        payload["chat_template_kwargs"] = {"enable_thinking": False}
    return(payload)


def iter_sse(endpoint: str, payload: Dict[str, Any], api_key: str, timeout: float) -> Iterable[Dict[str, Any]]:
    headers = {"Content-Type": "application/json"}
    if api_key != "":
        headers["Authorization"] = "Bearer " + api_key
    data = json.dumps(payload, separators=(",", ":")).encode("utf-8")
    req = urllib.request.Request(endpoint, data=data, headers=headers, method="POST")
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        for raw in resp:
            line = raw.decode("utf-8", errors="replace").strip()
            if line == "" or line.startswith(":") or line.startswith("event:"):
                continue
            if line.startswith("data:"):
                line = line[5:].strip()
            if line == "[DONE]":
                break
            try:
                obj = json.loads(line)
            except json.JSONDecodeError:
                continue
            if isinstance(obj, dict):
                yield(obj)


def delta_text(obj: Dict[str, Any]) -> str:
    out: List[str] = []
    for choice in obj.get("choices", []):
        delta = choice.get("delta") or {}
        for key in ("content", "reasoning", "reasoning_content"):
            v = delta.get(key)
            if isinstance(v, str) and v != "":
                out.append(v)
    return("".join(out))


def run_one(args: argparse.Namespace, prompt: Prompt, replica: int, group_id: int) -> Dict[str, Any]:
    t0 = time.perf_counter()
    ttft: Optional[float] = None
    completion_tokens: Optional[int] = None
    prompt_tokens: Optional[int] = None
    text_parts: List[str] = []
    error = ""
    try:
        for obj in iter_sse(args.endpoint, payload_for(args, prompt), args.api_key, args.timeout):
            usage = obj.get("usage")
            if isinstance(usage, dict):
                if usage.get("completion_tokens") is not None:
                    completion_tokens = int(usage.get("completion_tokens"))
                if usage.get("prompt_tokens") is not None:
                    prompt_tokens = int(usage.get("prompt_tokens"))
            piece = delta_text(obj)
            if piece != "":
                if ttft is None:
                    ttft = time.perf_counter() - t0
                text_parts.append(piece)
    except (urllib.error.URLError, TimeoutError, OSError) as e:
        error = repr(e)
    total = time.perf_counter() - t0
    decode_time = None
    decode_tps = None
    if ttft is not None:
        decode_time = max(0.0, total - ttft)
    if completion_tokens is not None and decode_time is not None and decode_time > 0.0:
        decode_tps = completion_tokens / decode_time
    text = "".join(text_parts)
    return({
        "model": args.model,
        "prompt": prompt.name,
        "category": prompt.category,
        "replica": replica,
        "group_id": group_id,
        "thinking": args.thinking,
        "concurrency": args.concurrency,
        "ttft_s": ttft,
        "total_wall_s": total,
        "decode_time_s": decode_time,
        "prompt_tokens": prompt_tokens,
        "output_tokens": completion_tokens,
        "decode_tps": decode_tps,
        "text_preview": text.replace("\n", " ")[:220],
        "error": error,
    })


def run_group(args: argparse.Namespace, prompt: Prompt, group_id: int) -> List[Dict[str, Any]]:
    start = time.perf_counter()
    rows: List[Dict[str, Any]] = []
    with concurrent.futures.ThreadPoolExecutor(max_workers=args.concurrency) as ex:
        futs = [ex.submit(run_one, args, prompt, i, group_id) for i in range(args.concurrency)]
        for fut in concurrent.futures.as_completed(futs):
            rows.append(fut.result())
    wall = time.perf_counter() - start
    total_tokens = sum((r.get("output_tokens") or 0) for r in rows)
    aggregate_tps = (total_tokens / wall) if wall > 0.0 and total_tokens > 0 else None
    for r in rows:
        r["group_wall_s"] = wall
        r["aggregate_output_tps"] = aggregate_tps
    return(sorted(rows, key=lambda r: int(r["replica"])))


def fmt(v: Any) -> str:
    if v is None:
        return("")
    if isinstance(v, float):
        return(f"{v:.6f}")
    return(str(v))


def write_jsonl(path: str, rows: Iterable[Dict[str, Any]]) -> None:
    if path == "":
        return
    with open(path, "w", encoding="utf-8") as f:
        for row in rows:
            f.write(json.dumps(row, sort_keys=True) + "\n")


def write_csv(path: str, rows: List[Dict[str, Any]]) -> None:
    if path == "" or not rows:
        return
    fields = [
        "model", "prompt", "category", "replica", "group_id", "thinking",
        "concurrency", "ttft_s", "total_wall_s", "decode_time_s",
        "prompt_tokens", "output_tokens", "decode_tps", "group_wall_s",
        "aggregate_output_tps", "error",
    ]
    with open(path, "w", encoding="utf-8", newline="") as f:
        w = csv.DictWriter(f, fieldnames=fields, extrasaction="ignore")
        w.writeheader()
        for row in rows:
            w.writerow({k: fmt(row.get(k)) for k in fields})


def median(xs: List[float]) -> Optional[float]:
    if not xs:
        return(None)
    return(float(statistics.median(xs)))


def print_summary(rows: List[Dict[str, Any]]) -> None:
    real = [r for r in rows if r["category"] != "warmup" and r.get("error", "") == ""]
    rates = [float(r["decode_tps"]) for r in real if r.get("decode_tps") is not None]
    ttfts = [float(r["ttft_s"]) for r in real if r.get("ttft_s") is not None]
    aggs = [float(r["aggregate_output_tps"]) for r in real if r.get("aggregate_output_tps") is not None]
    print("== summary ==")
    print(f"rows={len(rows)} real_rows={len(real)}")
    print(f"median_decode_tps={fmt(median(rates))}")
    print(f"median_ttft_s={fmt(median(ttfts))}")
    print(f"median_group_aggregate_output_tps={fmt(median(aggs))}")
    print()
    print("| category | n | median decode tok/s | median TTFT s | median aggregate tok/s |")
    print("| --- | ---: | ---: | ---: | ---: |")
    for category in sorted({r["category"] for r in real}):
        cr = [r for r in real if r["category"] == category]
        cr_rates = [float(r["decode_tps"]) for r in cr if r.get("decode_tps") is not None]
        cr_ttfts = [float(r["ttft_s"]) for r in cr if r.get("ttft_s") is not None]
        cr_aggs = [float(r["aggregate_output_tps"]) for r in cr if r.get("aggregate_output_tps") is not None]
        print(f"| {category} | {len(cr)} | {fmt(median(cr_rates))} | {fmt(median(cr_ttfts))} | {fmt(median(cr_aggs))} |")


def build_summary(rows: List[Dict[str, Any]]) -> Dict[str, Any]:
    real = [r for r in rows if r["category"] != "warmup" and r.get("error", "") == ""]
    out: Dict[str, Any] = {
        "rows": len(rows),
        "real_rows": len(real),
        "errors": sum(1 for r in rows if r.get("error", "") != ""),
    }

    def _med(field: str) -> Optional[float]:
        xs: List[float] = []
        for r in real:
            v = r.get(field)
            if v is None:
                continue
            try:
                xs.append(float(v))
            except (TypeError, ValueError):
                continue
        return(median(xs))

    out["median_decode_tps"] = _med("decode_tps")
    out["median_ttft_s"] = _med("ttft_s")
    out["median_total_wall_s"] = _med("total_wall_s")
    out["median_output_tokens"] = _med("output_tokens")
    out["median_prompt_tokens"] = _med("prompt_tokens")
    out["median_group_aggregate_output_tps"] = _med("aggregate_output_tps")

    cats = sorted({r["category"] for r in real})
    per_cat: Dict[str, Any] = {}
    for cat in cats:
        cr = [r for r in real if r["category"] == cat]
        per_cat[cat] = {
            "n": len(cr),
            "median_decode_tps": median([float(r["decode_tps"]) for r in cr if r.get("decode_tps") is not None]),
            "median_ttft_s": median([float(r["ttft_s"]) for r in cr if r.get("ttft_s") is not None]),
            "median_group_aggregate_output_tps": median([float(r["aggregate_output_tps"]) for r in cr if r.get("aggregate_output_tps") is not None]),
        }
    out["per_category"] = per_cat
    return(out)


def maybe_write_summary_json(path: str, summary: Dict[str, Any]) -> None:
    if path == "":
        return
    with open(path, "w", encoding="utf-8") as f:
        json.dump(summary, f, sort_keys=True, indent=2)
        f.write("\n")


def maybe_write_baseline_summary(path: str, args: argparse.Namespace, summary: Dict[str, Any]) -> None:
    if path == "":
        return

    ttft_s = summary.get("median_ttft_s")
    decode_tps = summary.get("median_decode_tps")
    total_wall_s = summary.get("median_total_wall_s")
    output_tokens = summary.get("median_output_tokens")
    prompt_tokens = summary.get("median_prompt_tokens")

    prefill_tps = None
    try:
        if isinstance(prompt_tokens, (int, float)) and isinstance(ttft_s, (int, float)) and float(ttft_s) > 0.0:
            prefill_tps = float(prompt_tokens) / float(ttft_s)
    except Exception:
        prefill_tps = None

    lines: List[str] = []
    lines.append("endpoint=" + str(args.endpoint))
    lines.append("model=" + str(args.model))
    lines.append("thinking=" + str(args.thinking))
    lines.append("concurrency=" + str(args.concurrency))
    if isinstance(ttft_s, (int, float)):
        lines.append("ttft_s=%.6f" % float(ttft_s))
    if isinstance(prefill_tps, (int, float)):
        lines.append("prefill_tps=%.6f" % float(prefill_tps))
    if isinstance(decode_tps, (int, float)):
        lines.append("decode_tps=%.6f" % float(decode_tps))
    if isinstance(total_wall_s, (int, float)):
        lines.append("total_wall_s=%.6f" % float(total_wall_s))
    if isinstance(output_tokens, (int, float)):
        lines.append("output_tokens=%.0f" % float(output_tokens))

    with open(path, "w", encoding="utf-8") as f:
        f.write("== baseline summary (approx) ==\n")
        f.write("\n".join(lines) + "\n")


def main() -> int:
    args = parse_args()
    if args.concurrency < 1:
        raise SystemExit("--concurrency must be >= 1")
    if args.out_dir != "":
        os.makedirs(args.out_dir, exist_ok=True)
        if args.jsonl_out == "":
            args.jsonl_out = os.path.join(args.out_dir, "openai_chat_stream.jsonl")
        if args.csv_out == "":
            args.csv_out = os.path.join(args.out_dir, "openai_chat_stream.csv")
        if args.summary_json_out == "":
            args.summary_json_out = os.path.join(args.out_dir, "openai_chat_stream.summary.json")
        if args.baseline_summary_out == "":
            args.baseline_summary_out = os.path.join(args.out_dir, "openai_chat_stream.baseline_summary.txt")
    prompts = selected_prompts(args)
    if not prompts:
        raise SystemExit("no prompts selected")
    print(f"endpoint={args.endpoint}")
    print(f"model={args.model}")
    print(f"thinking={args.thinking}")
    print(f"concurrency={args.concurrency}")
    print()
    rows: List[Dict[str, Any]] = []
    for group_id, prompt in enumerate(prompts):
        group_rows = run_group(args, prompt, group_id)
        rows.extend(group_rows)
        ok = [r for r in group_rows if r.get("error", "") == ""]
        rates = [float(r["decode_tps"]) for r in ok if r.get("decode_tps") is not None]
        aggs = [float(r["aggregate_output_tps"]) for r in ok if r.get("aggregate_output_tps") is not None]
        errors = len(group_rows) - len(ok)
        print(f"[{prompt.category}] {prompt.name}: n={len(group_rows)} errors={errors} median_decode_tps={fmt(median(rates))} aggregate_tps={fmt(median(aggs))}")
        sys.stdout.flush()
    write_jsonl(args.jsonl_out, rows)
    write_csv(args.csv_out, rows)
    print()
    summary = build_summary(rows)
    maybe_write_summary_json(args.summary_json_out, summary)
    maybe_write_baseline_summary(args.baseline_summary_out, args, summary)
    print_summary(rows)
    if args.baseline_summary_out != "":
        try:
            raw = open(args.baseline_summary_out, "r", encoding="utf-8").read()
        except OSError:
            raw = ""
        if raw != "":
            print()
            print("== baseline summary (approx) ==")
            print(raw.split("== baseline summary (approx) ==\n", 1)[-1], end="")
    return(0 if all(r.get("error", "") == "" for r in rows) else 3)


if __name__ == "__main__":
    raise SystemExit(main())
