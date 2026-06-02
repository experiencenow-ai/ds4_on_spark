from __future__ import annotations

import concurrent.futures
import hashlib
import json
import os
import re
import subprocess
import threading
import time
from typing import Any


class CpuServiceError(Exception):
    pass


CPU_SERVICE_NAMES = ("json_validate", "regex_match", "sha256", "text_metrics", "diff_stats", "command")


def _env_int(name: str, default: int) -> int:
    value = os.environ.get(name)
    return default if value in (None, "") else int(value)


def _env_json(name: str, default: dict[str, Any]) -> dict[str, Any]:
    value = os.environ.get(name)
    return default if value in (None, "") else json.loads(value)


def _safe_text(value: Any) -> str:
    if value is None:
        return ""
    if isinstance(value, bytes):
        return value.decode("utf-8", "replace")
    return str(value)


def _text_payload(item: dict[str, Any], max_bytes: int) -> str:
    text = str(item.get("text", item.get("content", "")))
    if len(text.encode("utf-8")) > max_bytes:
        raise CpuServiceError(f"text payload exceeds CPU_SERVICE_MAX_TEXT_BYTES={max_bytes}")
    return text


def validate_cpu_submission(service: str, item_count: int, *, commands: dict[str, Any] | None = None) -> None:
    if service not in CPU_SERVICE_NAMES:
        raise CpuServiceError(f"unknown CPU service: {service}")
    max_items = _env_int("CPU_SERVICE_MAX_ITEMS", 1024)
    if item_count > max_items:
        raise CpuServiceError(f"CPU batch item count {item_count} exceeds CPU_SERVICE_MAX_ITEMS={max_items}")
    if service == "command":
        configured = commands if commands is not None else _env_json("CPU_SERVICE_COMMANDS_JSON", {})
        if not configured:
            raise CpuServiceError("CPU command service has no allowlisted commands")


class CpuBatchService:
    def __init__(self, *, commands: dict[str, Any] | None = None) -> None:
        cores = os.cpu_count() or 4
        default_workers = min(16, max(1, cores - 4))
        self.workers = max(1, _env_int("CPU_SERVICE_WORKERS", default_workers))
        self.max_items = _env_int("CPU_SERVICE_MAX_ITEMS", 1024)
        self.max_concurrency = max(1, _env_int("CPU_SERVICE_MAX_CONCURRENCY", self.workers))
        default_concurrency = _env_int(
            "CPU_SERVICE_DEFAULT_CONCURRENCY",
            min(4, self.max_concurrency),
        )
        self.default_concurrency = min(self.max_concurrency, max(1, default_concurrency))
        self.max_text_bytes = _env_int("CPU_SERVICE_MAX_TEXT_BYTES", 1024 * 1024)
        self.command_timeout = float(os.environ.get("CPU_SERVICE_COMMAND_TIMEOUT", "120"))
        self.command_output_bytes = _env_int("CPU_SERVICE_COMMAND_OUTPUT_BYTES", 65536)
        self.commands = dict(commands if commands is not None else _env_json("CPU_SERVICE_COMMANDS_JSON", {}))
        self.lock = threading.Lock()
        self.pending = 0
        self.active = 0
        self.completed = 0
        self.failed = 0
        self.pool: concurrent.futures.ThreadPoolExecutor | None = None
        self.services = {name: getattr(self, f"service_{name}") for name in CPU_SERVICE_NAMES}

    def _pool(self) -> concurrent.futures.ThreadPoolExecutor:
        if self.pool is None:
            self.pool = concurrent.futures.ThreadPoolExecutor(max_workers=self.workers, thread_name_prefix="ds4-cpu")
        return self.pool

    def close(self) -> None:
        if self.pool is not None:
            self.pool.shutdown(wait=False, cancel_futures=True)
            self.pool = None

    def __enter__(self) -> "CpuBatchService":
        return self

    def __exit__(self, exc_type, exc, tb) -> None:
        self.close()

    def __del__(self) -> None:
        try:
            self.close()
        except Exception:
            return

    def status(self) -> dict[str, Any]:
        with self.lock:
            queue = {
                "workers": self.workers,
                "pending": self.pending,
                "active": self.active,
                "completed": self.completed,
                "failed": self.failed,
                "max_items": self.max_items,
                "max_concurrency": self.max_concurrency,
                "default_concurrency": self.default_concurrency,
                "max_text_bytes": self.max_text_bytes,
            }
        return {
            "object": "ds4.cpu_services",
            "queue": queue,
            "services": sorted(self.services),
            "configured_commands": sorted(self.commands),
        }

    def normalize_batch(self, payload: dict[str, Any]) -> tuple[str, list[Any], int, float]:
        service = str(payload.get("service", ""))
        if service not in self.services:
            raise CpuServiceError(f"unknown CPU service: {service}")
        items = payload.get("items", payload.get("requests"))
        if not isinstance(items, list) or not items:
            raise CpuServiceError("CPU batch body must contain a non-empty items array")
        if len(items) > self.max_items:
            raise CpuServiceError(f"CPU batch item count {len(items)} exceeds CPU_SERVICE_MAX_ITEMS={self.max_items}")
        concurrency = int(payload.get("concurrency", self.default_concurrency))
        if concurrency < 1 or concurrency > self.max_concurrency:
            raise CpuServiceError(
                f"CPU batch concurrency {concurrency} exceeds allowed range 1..{self.max_concurrency}"
            )
        return service, items, concurrency, float(payload.get("timeout_s", 300))

    def run_batch(self, payload: dict[str, Any]) -> dict[str, Any]:
        started = time.time()
        service, items, concurrency, timeout_s = self.normalize_batch(payload)
        sem = threading.Semaphore(concurrency)
        with self.lock:
            self.pending += len(items)
        futures = [self._pool().submit(self._run_one, service, i, item, sem) for i, item in enumerate(items)]
        results: list[dict[str, Any] | None] = [None] * len(items)
        try:
            for future in concurrent.futures.as_completed(futures, timeout=timeout_s):
                index, result = future.result()
                results[index] = result
        except concurrent.futures.TimeoutError:
            for index, future in enumerate(futures):
                if results[index] is None:
                    if future.cancel():
                        with self.lock:
                            self.pending = max(0, self.pending - 1)
                    results[index] = {"index": index, "service": service, "ok": False, "error": "CPU batch timeout"}
        final = [result for result in results if result is not None]
        failed = sum(1 for result in final if not result.get("ok"))
        return {
            "ok": failed == 0,
            "object": "ds4.cpu_batch",
            "service": service,
            "count": len(final),
            "failed": failed,
            "duration_s": round(time.time() - started, 6),
            "results": final,
        }

    def _run_one(self, service: str, index: int, item: Any, sem: threading.Semaphore) -> tuple[int, dict[str, Any]]:
        custom_id = item.get("custom_id") if isinstance(item, dict) else None
        start = time.time()
        sem.acquire()
        with self.lock:
            self.pending -= 1
            self.active += 1
        try:
            request = dict(item.get("request", item)) if isinstance(item, dict) else {}
            for key in ("custom_id", "metadata", "request"):
                request.pop(key, None)
            response = self.services[service](request)
            ok = bool(response.pop("_ok", True))
            result = {"index": index, "custom_id": custom_id, "service": service, "ok": ok, "response": response}
        except Exception as exc:
            result = {"index": index, "custom_id": custom_id, "service": service, "ok": False, "error": str(exc)}
        finally:
            sem.release()
            with self.lock:
                self.active -= 1
                self.completed += 1
                if not result.get("ok"):
                    self.failed += 1
        result["elapsed_s"] = round(time.time() - start, 6)
        return index, result

    def service_json_validate(self, item: dict[str, Any]) -> dict[str, Any]:
        if "json" in item:
            obj = item["json"]
        else:
            try:
                obj = json.loads(_text_payload(item, self.max_text_bytes))
            except Exception as exc:
                return {"valid": False, "error": str(exc)}
        required = item.get("required_keys") or []
        missing = list(required) if required and not isinstance(obj, dict) else [
            key for key in required if key not in obj
        ]
        return {
            "valid": len(missing) == 0,
            "type": type(obj).__name__,
            "keys": sorted(obj) if isinstance(obj, dict) else [],
            "missing_keys": missing,
        }

    def service_regex_match(self, item: dict[str, Any]) -> dict[str, Any]:
        text = _text_payload(item, self.max_text_bytes)
        pattern = str(item.get("pattern", ""))
        if not pattern:
            raise CpuServiceError("regex_match requires pattern")
        flags = 0
        for flag in item.get("flags") or []:
            if flag == "i":
                flags |= re.IGNORECASE
            elif flag == "m":
                flags |= re.MULTILINE
            elif flag == "s":
                flags |= re.DOTALL
            else:
                raise CpuServiceError(f"unsupported regex flag: {flag}")
        regex = re.compile(pattern, flags)
        matches = [regex.fullmatch(text)] if item.get("fullmatch") else list(regex.finditer(text))
        matches = [match for match in matches if match is not None]
        limit = int(item.get("limit", 16))
        return {
            "matched": len(matches) != 0,
            "count": len(matches),
            "matches": [
                {"span": list(match.span()), "text": match.group(0), "groups": list(match.groups())}
                for match in matches[:limit]
            ],
        }

    def service_sha256(self, item: dict[str, Any]) -> dict[str, Any]:
        raw = _text_payload(item, self.max_text_bytes).encode("utf-8")
        return {"sha256": hashlib.sha256(raw).hexdigest(), "bytes": len(raw)}

    def service_text_metrics(self, item: dict[str, Any]) -> dict[str, Any]:
        text = _text_payload(item, self.max_text_bytes)
        raw = text.encode("utf-8")
        line_count = 0 if text == "" else text.count("\n") + (0 if text.endswith("\n") else 1)
        return {
            "bytes": len(raw),
            "chars": len(text),
            "lines": line_count,
            "words": len(re.findall(r"\S+", text)),
            "approx_tokens": max(1, (len(raw) + 3) // 4) if raw else 0,
            "sha256": hashlib.sha256(raw).hexdigest(),
        }

    def service_diff_stats(self, item: dict[str, Any]) -> dict[str, Any]:
        files: set[str] = set()
        additions = deletions = hunks = 0
        text = _text_payload(item, self.max_text_bytes)
        for line in text.splitlines():
            if line.startswith("diff --git "):
                parts = line.split()
                if len(parts) >= 4:
                    files.add(parts[3][2:] if parts[3].startswith("b/") else parts[3])
            elif line.startswith("@@"):
                hunks += 1
            elif line.startswith("+++ ") or line.startswith("--- "):
                path = line[4:].strip()
                if path not in ("", "/dev/null"):
                    files.add(path[2:] if path.startswith(("a/", "b/")) else path)
            elif line.startswith("+"):
                additions += 1
            elif line.startswith("-"):
                deletions += 1
        return {
            "files": sorted(files),
            "file_count": len(files),
            "additions": additions,
            "deletions": deletions,
            "changed_lines": additions + deletions,
            "hunks": hunks,
            "contains_evolve_block": "EVOLVE-BLOCK" in text,
        }

    def service_command(self, item: dict[str, Any]) -> dict[str, Any]:
        name = str(item.get("name") or item.get("command") or "")
        spec = self.commands.get(name)
        if not isinstance(spec, dict):
            raise CpuServiceError(f"unknown allowlisted command: {name}")
        argv = [str(part) for part in spec.get("argv", [])]
        if not argv:
            raise CpuServiceError(f"allowlisted command {name} has no argv")
        if item.get("args"):
            if not spec.get("allow_args"):
                raise CpuServiceError(f"allowlisted command {name} does not allow item args")
            argv.extend(str(part) for part in item["args"])
        stdin = str(item.get("stdin", "")) if "stdin" in item else None
        if stdin is not None and not spec.get("allow_stdin"):
            raise CpuServiceError(f"allowlisted command {name} does not allow stdin")
        env = os.environ.copy()
        env.update({str(key): str(value) for key, value in (spec.get("env") or {}).items()})
        timeout = min(float(item.get("timeout_s", spec.get("timeout_s", self.command_timeout))), self.command_timeout)
        try:
            proc = subprocess.run(
                argv,
                input=stdin,
                cwd=str(spec.get("cwd", os.getcwd())),
                env=env,
                text=True,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                timeout=timeout,
                check=False,
            )
            return {
                "_ok": proc.returncode == 0,
                "name": name,
                "returncode": proc.returncode,
                "stdout": _safe_text(proc.stdout)[-self.command_output_bytes:],
                "stderr": _safe_text(proc.stderr)[-self.command_output_bytes:],
            }
        except subprocess.TimeoutExpired as exc:
            return {
                "_ok": False,
                "name": name,
                "timeout_s": timeout,
                "stdout": _safe_text(exc.stdout)[-self.command_output_bytes:],
                "stderr": _safe_text(exc.stderr)[-self.command_output_bytes:],
            }
