#!/usr/bin/env python3
from __future__ import annotations

import argparse
import os
import signal
import subprocess
import time
from dataclasses import dataclass


@dataclass(frozen=True)
class ProcessRow:
    pid: int
    ppid: int
    command: str


def main() -> int:
    args = _parse_args()
    rows = _process_rows()
    targets = _coordinator_targets(rows)
    if not targets:
        print("ds4 coordinator stop: no matching process")
        return 0
    print(f"ds4 coordinator stop: matched {len(targets)} process(es)")
    for row in targets:
        print(f"pid={row.pid} ppid={row.ppid} cmd={row.command}")
    if args.dry_run:
        return 0
    _signal_targets(targets, signal.SIGTERM)
    survivors = _wait_for_exit([row.pid for row in targets], timeout_s=args.timeout_s)
    if survivors and args.force:
        print(f"ds4 coordinator stop: SIGTERM left {len(survivors)} process(es); sending SIGKILL")
        _signal_pids(survivors, signal.SIGKILL)
        survivors = _wait_for_exit(survivors, timeout_s=args.kill_timeout_s)
    if survivors:
        print(f"ds4 coordinator stop: failed to stop pid(s): {','.join(str(pid) for pid in survivors)}")
        return 1
    print("ds4 coordinator stop: stopped")
    return 0


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Stop the spark0 DS4 coordinator API without self-matching shell patterns.")
    parser.add_argument("--timeout-s", type=float, default=8.0)
    parser.add_argument("--kill-timeout-s", type=float, default=4.0)
    parser.add_argument("--force", dest="force", action="store_true", default=True)
    parser.add_argument("--no-force", dest="force", action="store_false")
    parser.add_argument("--dry-run", action="store_true")
    return parser.parse_args()


def _process_rows() -> list[ProcessRow]:
    completed = subprocess.run(["ps", "-eo", "pid=,ppid=,command="], text=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE, check=False)
    if completed.returncode != 0:
        raise RuntimeError((completed.stderr or completed.stdout).strip())
    rows: list[ProcessRow] = []
    for line in completed.stdout.splitlines():
        parts = line.strip().split(None, 2)
        if len(parts) != 3:
            continue
        try:
            rows.append(ProcessRow(pid=int(parts[0]), ppid=int(parts[1]), command=parts[2]))
        except ValueError:
            continue
    return rows


def _coordinator_targets(rows: list[ProcessRow]) -> list[ProcessRow]:
    self_pid = os.getpid()
    rows_by_pid = {row.pid: row for row in rows}
    direct = [row for row in rows if row.pid != self_pid and _is_coordinator_command(row.command)]
    target_pids = {row.pid for row in direct}
    changed = True
    while changed:
        changed = False
        for row in rows:
            if row.pid not in target_pids and row.ppid in target_pids:
                target_pids.add(row.pid)
                changed = True
    return sorted((rows_by_pid[pid] for pid in target_pids if pid in rows_by_pid), key=lambda row: row.pid, reverse=True)


def _is_coordinator_command(command: str) -> bool:
    if "ds4_stop_coordinator_api.py" in command or "ds4_relaunch_coordinator_api.py" in command:
        return False
    if "ds4_infer.api" in command and " -m " in f" {command} ":
        return True
    if "ds4_coordinator_api.sh" in command and "scripts/" in command:
        return True
    return False


def _signal_targets(targets: list[ProcessRow], sig: signal.Signals) -> None:
    _signal_pids([row.pid for row in targets], sig)


def _signal_pids(pids: list[int], sig: signal.Signals) -> None:
    for pid in pids:
        try:
            os.kill(pid, sig)
        except ProcessLookupError:
            pass


def _wait_for_exit(pids: list[int], *, timeout_s: float) -> list[int]:
    deadline = time.time() + max(0.0, timeout_s)
    remaining = list(dict.fromkeys(pids))
    while remaining and time.time() < deadline:
        remaining = [pid for pid in remaining if _pid_exists(pid)]
        if remaining:
            time.sleep(0.1)
    return [pid for pid in remaining if _pid_exists(pid)]


def _pid_exists(pid: int) -> bool:
    try:
        os.kill(pid, 0)
        return True
    except ProcessLookupError:
        return False
    except PermissionError:
        return True


if __name__ == "__main__":
    raise SystemExit(main())
