#!/usr/bin/env python3
"""Benchmark every model exposed by the DS4 model gateway."""

from __future__ import annotations

import argparse
import csv
import json
import os
import re
import subprocess
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from typing import Any, Dict, Iterable, List, Optional


def parse_csv_ints(raw: str) -> List[int]:
    out: List[int] = []
    for part in raw.split(","):
        part = part.strip()
        if part != "":
            out.append(int(part))
    return(out or [1])


def sanitize(name: str) -> str:
    name = re.sub(r"[^A-Za-z0-9._-]+", "_", name)
    return(name.strip("_") or "model")


def jdump(obj: Any) -> str:
    return(json.dumps(obj, sort_keys=True, separators=(",", ":")))


def request_json(method: str, url: str, payload: Optional[Dict[str, Any]] = None, timeout: float = 60.0) -> Dict[str, Any]:
    data = None
    headers = {"content-type": "application/json"}
    if payload is not None:
        data = json.dumps(payload, separators=(",", ":")).encode("utf-8")
    req = urllib.request.Request(url, data=data, headers=headers, method=method)
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            text = resp.read().decode("utf-8", "replace")
            return(json.loads(text))
    except urllib.error.HTTPError as e:
        text = e.read().decode("utf-8", "replace")
        try:
            body = json.loads(text)
        except json.JSONDecodeError:
            body = {"error": text}
        body["http_status"] = e.code
        return(body)


def gateway_models(base: str) -> List[Dict[str, Any]]:
    data = request_json("GET", base.rstrip("/") + "/v1/models")
    rows = data.get("data", [])
    if not isinstance(rows, list):
        raise SystemExit("gateway model response missing data[]")
    return(sorted((r for r in rows if isinstance(r, dict)), key=lambda r: str(r.get("id", ""))))


def gateway_status(base: str) -> Dict[str, Any]:
    return(request_json("GET", base.rstrip("/") + "/ds4/status", timeout=30.0))


def release_gateway(base: str, model: str = "") -> Dict[str, Any]:
    url = base.rstrip("/") + "/ds4/release"
    if model != "":
        url += "?model=" + urllib.parse.quote(model, safe="")
    return(request_json("POST", url, timeout=180.0))


def keep_model(model: str, only: Iterable[str], skip: Iterable[str]) -> bool:
    only_set = set(only)
    skip_set = set(skip)
    leaf = model.rsplit("/", 1)[-1]
    if only_set and model not in only_set and leaf not in only_set:
        return(False)
    if model in skip_set or leaf in skip_set:
        return(False)
    return(True)


def read_summary(path: str) -> Dict[str, Any]:
    try:
        with open(path, "r", encoding="utf-8") as f:
            return(json.load(f))
    except (OSError, json.JSONDecodeError):
        return({})


def write_json(path: str, obj: Any) -> None:
    with open(path, "w", encoding="utf-8") as f:
        json.dump(obj, f, sort_keys=True, indent=2)
        f.write("\n")


def benchmark_script() -> str:
    return(os.path.join(os.path.dirname(__file__), "benchmark_openai_chat_stream.py"))


def run_one(args: argparse.Namespace, model: str, meta: Dict[str, Any], concurrency: int, seq: int) -> Dict[str, Any]:
    model_dir = os.path.join(args.out_dir, "%03d-%s-c%d" % (seq, sanitize(model), concurrency))
    os.makedirs(model_dir, exist_ok=True)
    summary_path = os.path.join(model_dir, "openai_chat_stream.summary.json")
    stdout_path = os.path.join(model_dir, "stdout.txt")
    stderr_path = os.path.join(model_dir, "stderr.txt")
    cmd = [
        sys.executable,
        benchmark_script(),
        "--endpoint",
        args.base.rstrip("/") + "/v1/chat/completions",
        "--model",
        model,
        "--thinking",
        args.thinking,
        "--concurrency",
        str(concurrency),
        "--timeout",
        str(args.timeout),
        "--max-prompts",
        str(args.max_prompts),
        "--warmup-count",
        str(args.warmup_count),
        "--out-dir",
        model_dir,
    ]
    for category in args.category:
        cmd.extend(["--category", category])
    started = time.time()
    if args.dry_run:
        rc = 0
        out = "dry_run command: " + " ".join(cmd) + "\n"
        err = ""
    else:
        proc = subprocess.run(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
        rc = proc.returncode
        out = proc.stdout
        err = proc.stderr
    with open(stdout_path, "w", encoding="utf-8") as f:
        f.write(out)
    with open(stderr_path, "w", encoding="utf-8") as f:
        f.write(err)
    summary = read_summary(summary_path)
    return({
        "model": model,
        "backend": meta.get("backend", ""),
        "root": meta.get("root", ""),
        "concurrency": concurrency,
        "returncode": rc,
        "elapsed_s": round(time.time() - started, 3),
        "run_dir": model_dir,
        "summary": summary,
    })


def load_targets(path: str) -> Dict[str, Any]:
    if path == "":
        return({})
    try:
        with open(path, "r", encoding="utf-8") as f:
            data = json.load(f)
    except (OSError, json.JSONDecodeError) as e:
        raise SystemExit("cannot load targets JSON %s: %s" % (path, e))
    if not isinstance(data, dict):
        raise SystemExit("targets JSON must be an object")
    return(data.get("models", data))


def target_eval(model: str, summary: Dict[str, Any], targets: Dict[str, Any]) -> Dict[str, Any]:
    target = targets.get(model) or targets.get(model.rsplit("/", 1)[-1]) or {}
    if not isinstance(target, dict):
        return({})
    want = target.get("decode_tps")
    got = summary.get("median_decode_tps")
    out = dict(target)
    if isinstance(want, (int, float)) and isinstance(got, (int, float)) and float(want) > 0.0:
        threshold = float(target.get("threshold", 0.9))
        ratio = float(got) / float(want)
        out["ratio"] = ratio
        out["status"] = "pass" if ratio >= threshold else "below_target"
    return(out)


def write_csv_summary(path: str, rows: List[Dict[str, Any]], targets: Dict[str, Any]) -> None:
    fields = [
        "model",
        "backend",
        "concurrency",
        "returncode",
        "median_decode_tps",
        "median_group_aggregate_output_tps",
        "median_ttft_s",
        "errors",
        "sota_status",
        "sota_ratio",
        "run_dir",
    ]
    with open(path, "w", encoding="utf-8", newline="") as f:
        w = csv.DictWriter(f, fieldnames=fields)
        w.writeheader()
        for row in rows:
            s = row.get("summary", {})
            t = target_eval(str(row.get("model", "")), s, targets)
            w.writerow({
                "model": row.get("model", ""),
                "backend": row.get("backend", ""),
                "concurrency": row.get("concurrency", ""),
                "returncode": row.get("returncode", ""),
                "median_decode_tps": s.get("median_decode_tps", ""),
                "median_group_aggregate_output_tps": s.get("median_group_aggregate_output_tps", ""),
                "median_ttft_s": s.get("median_ttft_s", ""),
                "errors": s.get("errors", ""),
                "sota_status": t.get("status", ""),
                "sota_ratio": "%.3f" % float(t["ratio"]) if isinstance(t.get("ratio"), (int, float)) else "",
                "run_dir": row.get("run_dir", ""),
            })


def write_markdown(path: str, rows: List[Dict[str, Any]], targets: Dict[str, Any], status: Dict[str, Any]) -> None:
    with open(path, "w", encoding="utf-8") as f:
        f.write("# DS4 Gateway Model Benchmark\n\n")
        f.write("- generated_utc: `%s`\n" % time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()))
        f.write("- gateway_models: `%d`\n" % len(status.get("models", [])))
        f.write("- active_at_start: `%s`\n\n" % status.get("current_model"))
        f.write("| model | backend | c | decode tok/s | aggregate tok/s | TTFT s | errors | target |\n")
        f.write("| --- | --- | ---: | ---: | ---: | ---: | ---: | --- |\n")
        for row in rows:
            s = row.get("summary", {})
            t = target_eval(str(row.get("model", "")), s, targets)
            target = t.get("status", "")
            if isinstance(t.get("ratio"), (int, float)):
                target = "%s %.2fx" % (target, float(t["ratio"]))
            f.write("| `%s` | `%s` | %s | %s | %s | %s | %s | %s |\n" % (
                row.get("model", ""),
                row.get("backend", ""),
                row.get("concurrency", ""),
                s.get("median_decode_tps", ""),
                s.get("median_group_aggregate_output_tps", ""),
                s.get("median_ttft_s", ""),
                s.get("errors", ""),
                target,
            ))


def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--base", default=os.environ.get("BASE", "http://127.0.0.1:8000"))
    p.add_argument("--out-dir", default=os.environ.get("OUT_DIR", ""))
    p.add_argument("--only", action="append", default=[])
    p.add_argument("--skip", action="append", default=[])
    p.add_argument("--category", action="append", default=["decode", "code", "reasoning"])
    p.add_argument("--max-prompts", type=int, default=int(os.environ.get("MAX_PROMPTS", "4")))
    p.add_argument("--warmup-count", type=int, default=int(os.environ.get("WARMUP_COUNT", "1")))
    p.add_argument("--concurrency", default=os.environ.get("CONCURRENCY", "1"))
    p.add_argument("--thinking", choices=("off", "on"), default=os.environ.get("BENCH_THINKING", "off"))
    p.add_argument("--timeout", type=float, default=float(os.environ.get("TIMEOUT", "1200")))
    p.add_argument("--targets-json", default=os.environ.get("SOTA_TARGETS_JSON", ""))
    p.add_argument("--no-release-between", action="store_true")
    p.add_argument("--dry-run", action="store_true")
    return(p.parse_args())


def main() -> int:
    args = parse_args()
    if args.out_dir == "":
        args.out_dir = os.path.join("/tmp", "ds4_gateway_bench", time.strftime("%Y%m%dT%H%M%SZ", time.gmtime()))
    os.makedirs(args.out_dir, exist_ok=True)
    targets = load_targets(args.targets_json)
    status0 = gateway_status(args.base)
    models = [m for m in gateway_models(args.base) if keep_model(str(m.get("id", "")), args.only, args.skip)]
    concurrencies = parse_csv_ints(args.concurrency)
    manifest = {"base": args.base, "models": models, "concurrency": concurrencies, "status_at_start": status0}
    write_json(os.path.join(args.out_dir, "manifest.json"), manifest)
    rows: List[Dict[str, Any]] = []
    total = len(models) * len(concurrencies)
    idx = 0
    for meta in models:
        model = str(meta.get("id", ""))
        if model == "":
            continue
        if not args.no_release_between and not args.dry_run:
            release_gateway(args.base)
        for concurrency in concurrencies:
            idx += 1
            print("BENCH_START %d/%d c=%d %s" % (idx, total, concurrency, model), flush=True)
            row = run_one(args, model, meta, concurrency, idx)
            rows.append(row)
            write_json(os.path.join(args.out_dir, "runs.json"), rows)
            print("BENCH_DONE rc=%s %s" % (row.get("returncode"), model), flush=True)
        if not args.no_release_between and not args.dry_run:
            release_gateway(args.base, model)
    write_json(os.path.join(args.out_dir, "runs.json"), rows)
    write_csv_summary(os.path.join(args.out_dir, "summary.csv"), rows, targets)
    write_markdown(os.path.join(args.out_dir, "summary.md"), rows, targets, status0)
    print("wrote %s" % args.out_dir)
    return(0 if all(int(r.get("returncode", 1)) == 0 for r in rows) else 3)


if __name__ == "__main__":
    raise SystemExit(main())
