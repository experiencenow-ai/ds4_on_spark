#!/usr/bin/env python3
"""Build a DS4 Spark access contract using the known-good Spark0 path first."""

from __future__ import annotations

import argparse
import json
import os
import re
import subprocess
import time
from pathlib import Path
from typing import Any

try:
    from validate_ds4_spark_access_contract import artifact_sha256
    from validate_ds4_spark_access_contract import validate_contract
except ModuleNotFoundError:
    from scripts.validate_ds4_spark_access_contract import artifact_sha256
    from scripts.validate_ds4_spark_access_contract import validate_contract


FORMAT = "ds4-spark-access-contract-v1"
PRIVATE_IPV4_RE = re.compile(r"\b(?:10(?:\.[0-9]{1,3}){3}|192\.168(?:\.[0-9]{1,3}){2}|172\.(?:1[6-9]|2[0-9]|3[0-1])(?:\.[0-9]{1,3}){2})\b")
SSH_KEY_RE = re.compile(r"\b(ssh-ed25519|ssh-rsa|ecdsa-sha2-nistp256) [A-Za-z0-9+/=]+")


def _redact(text: str) -> str:
    text = PRIVATE_IPV4_RE.sub("<private-ipv4>", text)
    text = SSH_KEY_RE.sub(r"\1 <known-host-key-redacted>", text)
    return text


def _sha256_text(text: str) -> str:
    import hashlib

    return "sha256:" + hashlib.sha256(text.encode("utf-8")).hexdigest()


def _clip(text: str, limit: int = 1200) -> dict[str, Any]:
    text = _redact(text.strip())
    if len(text) <= limit:
        return {"text": text, "truncated": False, "sha256": _sha256_text(text)}
    half = max(1, limit // 2)
    clipped = text[:half] + "\n<snip>\n" + text[-half:]
    return {"text": clipped, "truncated": True, "sha256": _sha256_text(text)}


def _run(command: list[str], timeout_s: float, env: dict[str, str] | None = None) -> dict[str, Any]:
    started = time.time()
    try:
        proc = subprocess.run(
            command,
            check=False,
            text=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            timeout=timeout_s,
            env=env,
        )
        stdout = _clip(proc.stdout)
        stderr = _clip(proc.stderr)
        return {
            "command": command,
            "returncode": proc.returncode,
            "status": "success" if proc.returncode == 0 else "failed",
            "stdout": stdout["text"],
            "stdout_sha256": stdout["sha256"],
            "stdout_truncated": stdout["truncated"],
            "stderr": stderr["text"],
            "stderr_sha256": stderr["sha256"],
            "stderr_truncated": stderr["truncated"],
            "elapsed_ms": round((time.time() - started) * 1000.0, 3),
            "error": "" if proc.returncode == 0 else (stderr["text"] or stdout["text"] or f"rc={proc.returncode}"),
        }
    except subprocess.TimeoutExpired as exc:
        stdout_text = exc.stdout if isinstance(exc.stdout, str) else ""
        stderr_text = exc.stderr if isinstance(exc.stderr, str) else ""
        stdout = _clip(stdout_text)
        stderr = _clip(stderr_text)
        return {
            "command": command,
            "returncode": None,
            "status": "timeout",
            "stdout": stdout["text"],
            "stdout_sha256": stdout["sha256"],
            "stdout_truncated": stdout["truncated"],
            "stderr": stderr["text"],
            "stderr_sha256": stderr["sha256"],
            "stderr_truncated": stderr["truncated"],
            "elapsed_ms": round((time.time() - started) * 1000.0, 3),
            "timeout": True,
            "error": "command timed out",
        }
    except OSError as exc:
        return {
            "command": command,
            "returncode": None,
            "status": "failed",
            "stdout": "",
            "stdout_sha256": _sha256_text(""),
            "stdout_truncated": False,
            "stderr": _redact(str(exc)),
            "stderr_sha256": _sha256_text(_redact(str(exc))),
            "stderr_truncated": False,
            "elapsed_ms": round((time.time() - started) * 1000.0, 3),
            "error": _redact(str(exc)),
        }


def _probe_env(args: argparse.Namespace) -> dict[str, str]:
    env = os.environ.copy()
    env["SPARK_SSH_USER"] = args.spark_ssh_user
    env["REDACT"] = "1"
    env["SPARK_KNOWN_HOSTS_PER_HOST"] = "1"
    return env


def build_contract(args: argparse.Namespace) -> dict[str, Any]:
    spark0_target = f"{args.spark_ssh_user}@{args.spark0_host}"
    ssh_command = ["ssh", spark0_target, "hostname"]
    probe_command = ["./scripts/spark_probe.sh", args.spark0_host]
    known_good_commands = [
        {"label": "spark0_known_good_ssh", "command": ssh_command},
        {
            "label": "spark0_spark_probe",
            "command": probe_command,
            "env": {"SPARK_SSH_USER": args.spark_ssh_user, "REDACT": "1", "SPARK_KNOWN_HOSTS_PER_HOST": "1"},
        },
    ]
    ssh_result = _run(ssh_command, args.ssh_timeout_s)
    probe_result = _run(probe_command, args.probe_timeout_s, env=_probe_env(args))
    ssh_ok = ssh_result["status"] == "success"
    probe_ok = probe_result["status"] == "success"
    access_ok = ssh_ok and probe_ok
    if access_ok:
        blocker_kind = "none"
        blocker_detail = "Known-good Spark0 SSH and spark_probe.sh access checks passed."
    elif not ssh_ok:
        blocker_kind = "known_good_ssh_failed"
        blocker_detail = f"Known-good SSH command failed: {ssh_result.get('error') or ssh_result.get('status')}"
    else:
        blocker_kind = "spark_probe_failed"
        blocker_detail = f"Known-good SSH passed, but spark_probe.sh failed: {probe_result.get('error') or probe_result.get('status')}"
    contract = {
        "format": FORMAT,
        "run_id": args.run_id or f"spark-access-contract-{int(time.time())}",
        "checked_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "access_mode": "known_good_ssh",
        "targets_checked": [spark0_target, args.spark0_host],
        "known_good_commands": known_good_commands,
        "ssh_results": {spark0_target: ssh_result},
        "probe_results": {"spark_probe_aitopatom_9ab9_local": probe_result},
        "discovery_results": {
            "random_local_discovery": {
                "status": "not_run",
                "command": [],
                "error": "Known-good Spark0 access path is authoritative for this probe; random .local discovery was not used as an access gate.",
            }
        },
        "access_ok": access_ok,
        "discovery_partial": False,
        "blocker_kind": blocker_kind,
        "blocker_detail": blocker_detail,
    }
    contract["artifact_sha256"] = artifact_sha256(contract)
    contract["artifact_hash"] = contract["artifact_sha256"]
    return contract


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--out", required=True)
    parser.add_argument("--run-id", default="")
    parser.add_argument("--spark0-host", default="aitopatom-9ab9.local")
    parser.add_argument("--spark-ssh-user", default=os.environ.get("SPARK_SSH_USER", "spark0"))
    parser.add_argument("--ssh-timeout-s", type=float, default=10.0)
    parser.add_argument("--probe-timeout-s", type=float, default=120.0)
    args = parser.parse_args()
    contract = build_contract(args)
    errors = validate_contract(contract)
    if errors:
        for error in errors:
            print(f"error: {error}")
        return 1
    out = Path(args.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(contract, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(json.dumps(contract, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
