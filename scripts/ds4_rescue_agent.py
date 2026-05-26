#!/usr/bin/env python3
"""Small authenticated non-SSH rescue endpoint for Spark nodes.

This agent is intentionally narrow: it exposes health/status probes and a
passwordless-sudo ssh restart hook when the host has been configured to allow
that exact operation. It does not expose a general shell.
"""

from __future__ import annotations

import argparse
import hmac
import http.server
import json
import os
import socket
import subprocess
import time
from pathlib import Path
from typing import Any


def read_token(path: Path) -> str:
    token = path.read_text(encoding="utf-8").strip()
    if len(token) < 32:
        raise SystemExit("token must be at least 32 characters")
    return token


def run_cmd(argv: list[str], timeout: float = 10.0) -> dict[str, Any]:
    start = time.time()
    try:
        cp = subprocess.run(argv, text=True, capture_output=True, timeout=timeout)
        return {
            "argv": argv,
            "rc": cp.returncode,
            "stdout": cp.stdout[-20000:],
            "stderr": cp.stderr[-20000:],
            "seconds": round(time.time() - start, 3),
        }
    except Exception as exc:
        return {
            "argv": argv,
            "error": repr(exc),
            "seconds": round(time.time() - start, 3),
        }


def ssh_banner_probe() -> dict[str, Any]:
    start = time.time()
    try:
        with socket.create_connection(("127.0.0.1", 22), timeout=2.0) as sock:
            sock.settimeout(2.0)
            data = sock.recv(128)
        banner = data.decode("utf-8", "replace").strip()
        ok = banner.startswith("SSH-")
        return {
            "ok": ok,
            "banner": banner,
            "seconds": round(time.time() - start, 3),
        }
    except Exception as exc:
        return {
            "ok": False,
            "error": repr(exc),
            "seconds": round(time.time() - start, 3),
        }


def status_payload() -> dict[str, Any]:
    return {
        "schema": "ds4.rescue.status.v1",
        "host": socket.gethostname(),
        "time_utc": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "user": os.environ.get("USER", ""),
        "ssh_probe": ssh_banner_probe(),
        "uptime": run_cmd(["uptime"], 5),
        "df_home": run_cmd(["df", "-h", str(Path.home())], 5),
        "ip_brief": run_cmd(["ip", "-br", "addr"], 5),
        "ssh_active": run_cmd(["systemctl", "is-active", "ssh"], 5),
    }


def restart_ssh() -> dict[str, Any]:
    first = run_cmd(["sudo", "-n", "systemctl", "restart", "ssh"], 15)
    if first.get("rc") == 0:
        return {
            "attempts": [first],
            "ssh_probe": ssh_banner_probe(),
        }
    second = run_cmd(["sudo", "-n", "systemctl", "restart", "sshd"], 15)
    return {
        "attempts": [first, second],
        "ssh_probe": ssh_banner_probe(),
    }


def self_rescue() -> dict[str, Any]:
    first = run_cmd(["sudo", "-n", "/usr/local/sbin/ds4-sshd-watchdog", "--force"], 30)
    return {
        "attempts": [first],
        "ssh_probe": ssh_banner_probe(),
    }


def peer_rescue() -> dict[str, Any]:
    first = run_cmd(["sudo", "-n", "/usr/local/sbin/ds4-sshd-watchdog", "--peer-force"], 60)
    return {
        "attempts": [first],
        "ssh_probe": ssh_banner_probe(),
    }


class RescueHandler(http.server.BaseHTTPRequestHandler):
    server_version = "ds4-rescue/1"

    def log_message(self, fmt: str, *args: Any) -> None:
        line = {
            "ts": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
            "client": self.client_address[0],
            "message": fmt % args,
        }
        print(json.dumps(line, sort_keys=True), flush=True)

    def authorized(self) -> bool:
        got = self.headers.get("X-DS4-Rescue-Token", "")
        return hmac.compare_digest(got, self.server.token)  # type: ignore[attr-defined]

    def write_json(self, code: int, obj: dict[str, Any]) -> None:
        data = (json.dumps(obj, sort_keys=True) + "\n").encode("utf-8")
        self.send_response(code)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def guarded(self) -> bool:
        if self.authorized():
            return True
        self.write_json(403, {"ok": False, "error": "forbidden"})
        return False

    def do_GET(self) -> None:
        if self.path == "/health":
            self.write_json(200, {"ok": True, "host": socket.gethostname()})
            return
        if not self.guarded():
            return
        if self.path == "/status":
            self.write_json(200, {"ok": True, "status": status_payload()})
            return
        if self.path == "/ssh-probe":
            self.write_json(200, {"ok": True, "ssh_probe": ssh_banner_probe()})
            return
        self.write_json(404, {"ok": False, "error": "not found"})

    def do_POST(self) -> None:
        if not self.guarded():
            return
        length = int(self.headers.get("Content-Length", "0"))
        raw = self.rfile.read(min(length, 4096))
        try:
            req = json.loads(raw.decode("utf-8") or "{}")
        except json.JSONDecodeError as exc:
            self.write_json(400, {"ok": False, "error": repr(exc)})
            return
        action = str(req.get("action", ""))
        if self.path != "/action":
            self.write_json(404, {"ok": False, "error": "not found"})
            return
        if action == "restart_ssh":
            self.write_json(200, {"ok": True, "result": restart_ssh()})
            return
        if action == "self_rescue":
            self.write_json(200, {"ok": True, "result": self_rescue()})
            return
        if action == "peer_rescue":
            self.write_json(200, {"ok": True, "result": peer_rescue()})
            return
        if action == "status":
            self.write_json(200, {"ok": True, "status": status_payload()})
            return
        self.write_json(400, {"ok": False, "error": "unknown action"})


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--host", default="0.0.0.0")
    ap.add_argument("--port", default=25100, type=int)
    ap.add_argument("--token-file", default=str(Path.home() / ".ds4-rescue" / "token"))
    args = ap.parse_args()
    token = read_token(Path(args.token_file))
    httpd = http.server.ThreadingHTTPServer((args.host, args.port), RescueHandler)
    httpd.token = token  # type: ignore[attr-defined]
    print(json.dumps({"event": "ready", "host": args.host, "port": args.port, "ts": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())}), flush=True)
    httpd.serve_forever()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
