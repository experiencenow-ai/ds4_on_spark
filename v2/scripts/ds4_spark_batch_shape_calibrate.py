#!/usr/bin/env python3
from __future__ import annotations

from dataclasses import dataclass
import argparse
import json
from pathlib import Path
import shlex
import subprocess
import sys
import time
from typing import Any

V2_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(V2_ROOT / "src"))

from ds4_infer.builders import apply_thinking_fields_for_model


@dataclass(frozen=True)
class Shape:
    model: str
    input_tokens: int
    output_tokens: int
    thinking_tokens: int


@dataclass(frozen=True)
class Probe:
    batch_size: int
    concurrency: int
    ok: bool
    succeeded: int
    failed: int
    completion_tokens: int
    elapsed_s: float
    tok_s: float
    error: str | None


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    out_dir = Path(args.out_dir or f"/tmp/ds4_batch_shape_calibrate_{args.node}_{int(time.time())}")
    out_dir.mkdir(parents=True, exist_ok=True)
    shapes = [
        Shape(model=model, input_tokens=input_tokens, output_tokens=output_tokens, thinking_tokens=thinking_tokens)
        for model in split_csv(args.models)
        for input_tokens in split_ints(args.input_tokens)
        for output_tokens in split_ints(args.output_tokens)
        for thinking_tokens in split_ints(args.thinking_tokens)
    ]
    manifest = {"format": "ds4-batch-shape-calibration-v1", "node": args.node, "base_url": args.base_url, "max_concurrency": args.max_concurrency, "max_batch_size": args.max_batch_size, "shapes": [shape_public(shape) for shape in shapes]}
    (out_dir / "manifest.json").write_text(json.dumps(manifest, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    results: list[dict[str, Any]] = []
    for shape in shapes:
        warm = run_probe(args, shape, batch_size=1)
        append_jsonl(out_dir / "probes.jsonl", {"shape": shape_public(shape), "probe": probe_public(warm), "phase": "warmup"})
        best, probes = calibrate_shape(args, shape)
        for probe in probes:
            append_jsonl(out_dir / "probes.jsonl", {"shape": shape_public(shape), "probe": probe_public(probe), "phase": "search"})
        row = {"shape": shape_public(shape), "best": probe_public(best) if best is not None else None, "probe_count": len(probes)}
        results.append(row)
        append_jsonl(out_dir / "summary.jsonl", row)
        print(json.dumps(row, sort_keys=True), flush=True)
    summary = summarize(args, results)
    (out_dir / "summary.json").write_text(json.dumps(summary, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(json.dumps({"out_dir": str(out_dir), **summary}, sort_keys=True), flush=True)
    return 0 if summary["ok"] else 2


def parse_args(argv: list[str] | None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Calibrate DS4 gateway batch item limits by model/input/output/thinking shape")
    parser.add_argument("--node", default="spark7")
    parser.add_argument("--base-url", default="http://127.0.0.1:8000")
    parser.add_argument("--models", default="Qwen/Qwen3.6-27B-FP8")
    parser.add_argument("--input-tokens", default="128,1024")
    parser.add_argument("--output-tokens", default="64,256")
    parser.add_argument("--thinking-tokens", default="0")
    parser.add_argument("--max-batch-size", type=int, default=256)
    parser.add_argument("--max-concurrency", type=int, default=16)
    parser.add_argument("--timeout-s", type=int, default=900)
    parser.add_argument("--repetitions", type=int, default=1)
    parser.add_argument("--out-dir")
    args = parser.parse_args(argv)
    if args.max_batch_size < 1 or args.max_concurrency < 1:
        raise ValueError("max batch size and max concurrency must be positive")
    if args.repetitions < 1:
        raise ValueError("repetitions must be positive")
    return args


def calibrate_shape(args: argparse.Namespace, shape: Shape) -> tuple[Probe | None, list[Probe]]:
    probes: list[Probe] = []
    best: Probe | None = None
    size = 1
    failed_size: int | None = None
    while size <= args.max_batch_size:
        probe = repeated_probe(args, shape, size)
        probes.append(probe)
        if probe.ok:
            best = probe
            size *= 2
            continue
        failed_size = size
        break
    if failed_size is None:
        return best, probes
    low = best.batch_size if best is not None else 0
    high = failed_size
    while high - low > 1:
        mid = ((low + high) // 2)
        probe = repeated_probe(args, shape, mid)
        probes.append(probe)
        if probe.ok:
            best = probe
            low = mid
        else:
            high = mid
    return best, probes


def repeated_probe(args: argparse.Namespace, shape: Shape, batch_size: int) -> Probe:
    probes = [run_probe(args, shape, batch_size=batch_size) for _ in range(args.repetitions)]
    if len(probes) == 1:
        return probes[0]
    ok = all(item.ok for item in probes)
    completion_tokens = sum(item.completion_tokens for item in probes)
    elapsed_s = sum(item.elapsed_s for item in probes)
    return Probe(batch_size=batch_size, concurrency=probes[0].concurrency, ok=ok, succeeded=sum(item.succeeded for item in probes), failed=sum(item.failed for item in probes), completion_tokens=completion_tokens, elapsed_s=elapsed_s, tok_s=(completion_tokens / elapsed_s if elapsed_s > 0 else 0.0), error=None if ok else "; ".join(item.error or "failed" for item in probes if not item.ok)[:1000])


def run_probe(args: argparse.Namespace, shape: Shape, *, batch_size: int) -> Probe:
    concurrency = min(batch_size, args.max_concurrency)
    max_tokens = shape.output_tokens + shape.thinking_tokens
    payload = {"model": shape.model, "endpoint": "/v1/chat/completions", "concurrency": concurrency, "timeout_s": args.timeout_s, "max_tokens": max_tokens, "items": [make_item(shape, idx) for idx in range(batch_size)]}
    started = time.time()
    completed = subprocess.run(["ssh", "-o", "BatchMode=yes", "-o", "ConnectTimeout=6", args.node, "python3 -c " + shlex.quote(remote_client(args.base_url, args.timeout_s))], input=json.dumps(payload), text=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE, timeout=args.timeout_s + 30, check=False)
    elapsed = time.time() - started
    if completed.returncode != 0:
        return Probe(batch_size=batch_size, concurrency=concurrency, ok=False, succeeded=0, failed=batch_size, completion_tokens=0, elapsed_s=round(elapsed, 6), tok_s=0.0, error=(completed.stderr or completed.stdout)[-2000:])
    try:
        response = json.loads(completed.stdout)
    except json.JSONDecodeError as exc:
        return Probe(batch_size=batch_size, concurrency=concurrency, ok=False, succeeded=0, failed=batch_size, completion_tokens=0, elapsed_s=round(elapsed, 6), tok_s=0.0, error=str(exc))
    counts = response.get("counts", {}) if isinstance(response, dict) else {}
    results = response.get("results", []) if isinstance(response, dict) else []
    succeeded = int(counts.get("succeeded", 0))
    failed = int(counts.get("failed", batch_size - succeeded))
    tokens = sum(result_tokens(item) for item in results if isinstance(item, dict) and item.get("ok"))
    ok = failed == 0 and succeeded == batch_size
    return Probe(batch_size=batch_size, concurrency=concurrency, ok=ok, succeeded=succeeded, failed=failed, completion_tokens=tokens, elapsed_s=round(elapsed, 6), tok_s=round(tokens / elapsed, 6) if elapsed > 0 else 0.0, error=None if ok else json.dumps(response, sort_keys=True)[-2000:])


def remote_client(base_url: str, timeout_s: int) -> str:
    return (
        "import json,sys,urllib.request\n"
        f"base={base_url!r}; timeout={timeout_s!r}\n"
        "payload=json.loads(sys.stdin.read())\n"
        "data=json.dumps(payload).encode()\n"
        "req=urllib.request.Request(base.rstrip('/')+'/ds4/batches', data=data, headers={'content-type':'application/json'})\n"
        "print(urllib.request.urlopen(req, timeout=timeout).read().decode())\n"
    )


def make_item(shape: Shape, idx: int) -> dict[str, Any]:
    prompt = prompt_for_tokens(shape.input_tokens, idx)
    item: dict[str, Any] = {"custom_id": f"shape-{shape.input_tokens}-{shape.output_tokens}-{shape.thinking_tokens}-{idx:05d}", "messages": [{"role": "user", "content": prompt}], "max_tokens": shape.output_tokens + shape.thinking_tokens, "temperature": 0}
    apply_thinking_fields_for_model(item, model_id=shape.model, supports_thinking=True, chat=True, thinking_budget_tokens=shape.thinking_tokens)
    return item


def prompt_for_tokens(tokens: int, idx: int) -> str:
    words = max(1, tokens)
    filler = " ".join("calibration" for _ in range(words))
    return f"Request {idx}. Produce concise numbered observations until the token budget is used. {filler}"


def result_tokens(item: dict[str, Any]) -> int:
    usage = item.get("response", {}).get("usage", {}) if isinstance(item.get("response"), dict) else {}
    if isinstance(usage, dict):
        value = usage.get("completion_tokens")
        if isinstance(value, (int, float)) and value >= 0:
            return int(value)
    text = json.dumps(item.get("response", {}), sort_keys=True)
    return max(0, len(text.encode("utf-8")) // 4)


def summarize(args: argparse.Namespace, results: list[dict[str, Any]]) -> dict[str, Any]:
    ok_count = sum(1 for item in results if item.get("best") is not None)
    return {"format": "ds4-batch-shape-calibration-summary-v1", "ok": ok_count == len(results), "node": args.node, "shape_count": len(results), "qualified_shape_count": ok_count, "results": results}


def split_csv(value: str) -> list[str]:
    return [item.strip() for item in value.split(",") if item.strip()]


def split_ints(value: str) -> list[int]:
    return [int(item.strip()) for item in value.split(",") if item.strip()]


def shape_public(shape: Shape) -> dict[str, Any]:
    return {"model": shape.model, "input_tokens": shape.input_tokens, "output_tokens": shape.output_tokens, "thinking_tokens": shape.thinking_tokens}


def probe_public(probe: Probe) -> dict[str, Any]:
    return {"batch_size": probe.batch_size, "concurrency": probe.concurrency, "ok": probe.ok, "succeeded": probe.succeeded, "failed": probe.failed, "completion_tokens": probe.completion_tokens, "elapsed_s": probe.elapsed_s, "tok_s": probe.tok_s, "error": probe.error}


def append_jsonl(path: Path, row: dict[str, Any]) -> None:
    with path.open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(row, sort_keys=True) + "\n")


if __name__ == "__main__":
    raise SystemExit(main())
