#!/usr/bin/env python3
"""Submit JSONL work to a DS4 gateway CPU service batch."""

from __future__ import annotations

import argparse
import json
import sys
import urllib.error
import urllib.request
from typing import Any, Dict, Iterable, List, Tuple


def read_jsonl(path: str) -> Iterable[Tuple[int, Dict[str, Any]]]:
    src = open(path, "r", encoding="utf-8") if path != "-" else sys.stdin
    close = src is not sys.stdin
    try:
        for idx, raw in enumerate(src, 1):
            line = raw.strip()
            if line == "" or line.startswith("#"):
                continue
            obj = json.loads(line)
            if not isinstance(obj, dict):
                raise ValueError("line %d must be a JSON object" % idx)
            yield(idx, obj)
    finally:
        if close:
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
    p.add_argument("--service", required=True)
    p.add_argument("--input", default="-")
    p.add_argument("--output", default="-")
    p.add_argument("--concurrency", type=int, default=4)
    p.add_argument("--timeout", type=float, default=300.0)
    p.add_argument("--format", choices=("jsonl", "envelope"), default="jsonl")
    return(p.parse_args())


def main() -> int:
    args = parse_args()
    if args.concurrency < 1:
        raise SystemExit("--concurrency must be >= 1")
    endpoint = args.endpoint or (args.base.rstrip("/") + "/ds4/cpu/batches")
    items: List[Dict[str, Any]] = [item for _, item in read_jsonl(args.input)]
    dst = open(args.output, "w", encoding="utf-8") if args.output != "-" else sys.stdout
    close = dst is not sys.stdout
    try:
        payload = {"service": args.service, "items": items, "concurrency": args.concurrency, "timeout_s": args.timeout}
        status, body = post_json(endpoint, payload, args.timeout + 30.0)
        if args.format == "envelope":
            dst.write(json.dumps(body, sort_keys=True, separators=(",", ":")) + "\n")
        elif status >= 200 and status < 300 and isinstance(body, dict) and isinstance(body.get("results"), list):
            for rec in body["results"]:
                dst.write(json.dumps(rec, sort_keys=True, separators=(",", ":")) + "\n")
        else:
            dst.write(json.dumps({"ok": False, "status": status, "response": body}, sort_keys=True, separators=(",", ":")) + "\n")
    finally:
        if close:
            dst.close()
    return(0)


if __name__ == "__main__":
    raise SystemExit(main())
