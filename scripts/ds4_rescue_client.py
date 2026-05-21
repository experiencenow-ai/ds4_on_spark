#!/usr/bin/env python3
"""Client for ds4_rescue_agent.py."""

from __future__ import annotations

import argparse
import json
import sys
import urllib.error
import urllib.request
from pathlib import Path


def request(host: str, port: int, token: str, method: str, path: str, body: dict[str, str] | None) -> str:
    data = None if body is None else json.dumps(body).encode("utf-8")
    req = urllib.request.Request(
        f"http://{host}:{port}{path}",
        data=data,
        method=method,
        headers={
            "X-DS4-Rescue-Token": token,
            "Content-Type": "application/json",
        },
    )
    try:
        with urllib.request.urlopen(req, timeout=10) as resp:
            return resp.read().decode("utf-8")
    except urllib.error.HTTPError as exc:
        return exc.read().decode("utf-8")


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("host")
    ap.add_argument("command", choices=["health", "status", "ssh-probe", "restart-ssh", "self-rescue"])
    ap.add_argument("--port", default=25100, type=int)
    ap.add_argument("--token-file", default="/private/tmp/ds4_rescue_token")
    args = ap.parse_args()
    token = Path(args.token_file).read_text(encoding="utf-8").strip()
    if args.command == "health":
        out = request(args.host, args.port, token, "GET", "/health", None)
    elif args.command == "status":
        out = request(args.host, args.port, token, "GET", "/status", None)
    elif args.command == "ssh-probe":
        out = request(args.host, args.port, token, "GET", "/ssh-probe", None)
    elif args.command == "restart-ssh":
        out = request(args.host, args.port, token, "POST", "/action", {"action": "restart_ssh"})
    else:
        out = request(args.host, args.port, token, "POST", "/action", {"action": "self_rescue"})
    try:
        print(json.dumps(json.loads(out), indent=2, sort_keys=True))
    except json.JSONDecodeError:
        sys.stdout.write(out)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
