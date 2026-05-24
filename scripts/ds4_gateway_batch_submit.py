#!/usr/bin/env python3
"""Submit a JSONL batch to an OpenAI-compatible DS4 model gateway."""

from __future__ import annotations

import argparse
import json
import urllib.error
import urllib.request
from typing import Any, Dict, Iterable, List, Tuple


def read_jsonl(path: str) -> Iterable[Tuple[int, Dict[str, Any]]]:
    src = open(path, "r", encoding="utf-8") if path != "-" else None
    try:
        f = src if src is not None else __import__("sys").stdin
        for idx, raw in enumerate(f, 1):
            line = raw.strip()
            if line == "" or line.startswith("#"):
                continue
            obj = json.loads(line)
            if not isinstance(obj, dict):
                raise ValueError("line %d must be a JSON object" % idx)
            yield(idx, obj)
    finally:
        if src is not None:
            src.close()


def post_json(url: str, payload: Dict[str, Any], timeout: float) -> Tuple[int, Dict[str, Any] | str]:
    data = json.dumps(payload, separators=(",", ":")).encode("utf-8")
    req = urllib.request.Request(url, data=data, headers={"content-type": "application/json"}, method="POST")
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            body = resp.read().decode("utf-8", "replace")
            try:
                return(resp.status, json.loads(body))
            except json.JSONDecodeError:
                return(resp.status, body)
    except urllib.error.HTTPError as e:
        body = e.read().decode("utf-8", "replace")
        try:
            return(e.code, json.loads(body))
        except json.JSONDecodeError:
            return(e.code, body)


def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--base", default="http://127.0.0.1:8000")
    p.add_argument("--endpoint", default="")
    p.add_argument("--model", required=True)
    p.add_argument("--input", default="-")
    p.add_argument("--output", default="-")
    p.add_argument("--concurrency", type=int, default=4)
    p.add_argument("--timeout", type=float, default=900.0)
    p.add_argument("--max-tokens", type=int, default=512)
    p.add_argument("--format", choices=("jsonl", "envelope"), default="jsonl")
    return(p.parse_args())


def main() -> int:
    args = parse_args()
    if args.concurrency < 1:
        raise SystemExit("--concurrency must be >= 1")
    if args.endpoint == "":
        args.endpoint = args.base.rstrip("/") + "/ds4/batches"
    items: List[Dict[str, Any]] = [item for _, item in read_jsonl(args.input)]
    dst = open(args.output, "w", encoding="utf-8") if args.output != "-" else None
    try:
        f = dst if dst is not None else __import__("sys").stdout
        payload = {
            "model": args.model,
            "items": items,
            "concurrency": args.concurrency,
            "timeout_s": args.timeout,
            "max_tokens": args.max_tokens,
        }
        waves = max(1, (len(items) + args.concurrency - 1) // args.concurrency)
        status, body = post_json(args.endpoint, payload, max(args.timeout, 30.0 + (args.timeout * waves)))
        if args.format == "envelope":
            f.write(json.dumps(body, sort_keys=True, separators=(",", ":")) + "\n")
        elif status >= 200 and status < 300 and isinstance(body, dict) and isinstance(body.get("results"), list):
            for rec in body["results"]:
                f.write(json.dumps(rec, sort_keys=True, separators=(",", ":")) + "\n")
                f.flush()
        else:
            f.write(json.dumps({"ok": False, "status": status, "response": body}, sort_keys=True, separators=(",", ":")) + "\n")
    finally:
        if dst is not None:
            dst.close()
    return(0)


if __name__ == "__main__":
    raise SystemExit(main())
