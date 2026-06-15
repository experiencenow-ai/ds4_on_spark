from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass
import json
import os
from pathlib import Path
import socket
import subprocess
import time
from typing import Any


@dataclass(frozen=True)
class GpuResourceReading:
    node_id: str
    ok: bool
    temperature_c: float | None = None
    power_w: float | None = None
    utilization_pct: float | None = None
    memory_used_mib: float | None = None
    memory_total_mib: float | None = None
    host_memory_used_mib: float | None = None
    host_memory_total_mib: float | None = None
    host_memory_used_pct: float | None = None
    error: str | None = None

    def to_public_dict(self) -> dict[str, Any]:
        return {
            "node_id": self.node_id,
            "ok": self.ok,
            "temperature_c": self.temperature_c,
            "power_w": self.power_w,
            "utilization_pct": self.utilization_pct,
            "memory_used_mib": self.memory_used_mib,
            "memory_total_mib": self.memory_total_mib,
            "host_memory_used_mib": self.host_memory_used_mib,
            "host_memory_total_mib": self.host_memory_total_mib,
            "host_memory_used_pct": self.host_memory_used_pct,
            "error": self.error,
        }


@dataclass(frozen=True)
class GpuResourceDecision:
    allow_refill: bool
    sleep_s: float
    status: dict[str, Any]


class GpuResourceGovernor:
    def __init__(
        self,
        *,
        enabled: bool,
        nodes: tuple[str, ...],
        local_node_id: str,
        poll_s: float,
        ssh_timeout_s: float,
        sample_workers: int,
        temp_soft_c: float,
        temp_hard_c: float,
        power_soft_w: float,
        power_hard_w: float,
        total_power_soft_w: float,
        total_power_hard_w: float,
        host_memory_soft_pct: float,
        host_memory_hard_pct: float,
        throttle_step_s: float,
        throttle_max_s: float,
        sample_json: str = "",
    ) -> None:
        self.enabled = bool(enabled)
        self.nodes = tuple(dict.fromkeys(str(node) for node in nodes if str(node)))
        self.local_node_id = str(local_node_id or socket.gethostname())
        self.poll_s = max(0.1, float(poll_s))
        self.ssh_timeout_s = max(0.2, float(ssh_timeout_s))
        self.sample_workers = max(1, int(sample_workers))
        self.temp_soft_c = float(temp_soft_c)
        self.temp_hard_c = float(temp_hard_c)
        self.power_soft_w = float(power_soft_w)
        self.power_hard_w = float(power_hard_w)
        self.total_power_soft_w = float(total_power_soft_w)
        self.total_power_hard_w = float(total_power_hard_w)
        self.host_memory_soft_pct = float(host_memory_soft_pct)
        self.host_memory_hard_pct = float(host_memory_hard_pct)
        self.throttle_step_s = max(0.0, float(throttle_step_s))
        self.throttle_max_s = max(0.0, float(throttle_max_s))
        self.sample_json = sample_json
        self._last_sample_at = 0.0
        self._cooldown_until = 0.0
        self._cooldown_count = 0
        self._last_status = self._initial_status()

    @classmethod
    def from_env(cls, *, nodes: tuple[str, ...], local_node_id: str) -> "GpuResourceGovernor":
        explicit_local_node = os.environ.get("DS4_API_RESOURCE_LOCAL_NODE_ID")
        resolved_local_node = (
            explicit_local_node.strip()
            if explicit_local_node and explicit_local_node.strip()
            else socket.gethostname()
        )
        return cls(
            enabled=_env_bool("DS4_API_RESOURCE_GOVERNOR", False),
            nodes=nodes,
            local_node_id=resolved_local_node,
            poll_s=_env_float("DS4_API_RESOURCE_POLL_S", 2.0),
            ssh_timeout_s=_env_float("DS4_API_RESOURCE_SSH_TIMEOUT_S", 1.5),
            sample_workers=_env_int("DS4_API_RESOURCE_SAMPLE_WORKERS", min(16, max(1, len(nodes)))),
            temp_soft_c=_env_float("DS4_API_RESOURCE_TEMP_SOFT_C", 86.0),
            temp_hard_c=_env_float("DS4_API_RESOURCE_TEMP_HARD_C", 88.0),
            power_soft_w=_env_float("DS4_API_RESOURCE_POWER_SOFT_W", 115.0),
            power_hard_w=_env_float("DS4_API_RESOURCE_POWER_HARD_W", 140.0),
            total_power_soft_w=_env_float("DS4_API_RESOURCE_TOTAL_POWER_SOFT_W", 1350.0),
            total_power_hard_w=_env_float("DS4_API_RESOURCE_TOTAL_POWER_HARD_W", 1550.0),
            host_memory_soft_pct=_env_float("DS4_API_RESOURCE_HOST_MEMORY_SOFT_PCT", 90.0),
            host_memory_hard_pct=_env_float("DS4_API_RESOURCE_HOST_MEMORY_HARD_PCT", 94.0),
            throttle_step_s=_env_float("DS4_API_RESOURCE_THROTTLE_STEP_S", 0.5),
            throttle_max_s=_env_float("DS4_API_RESOURCE_THROTTLE_MAX_S", 4.0),
            sample_json=os.environ.get("DS4_API_RESOURCE_SAMPLE_JSON", ""),
        )

    def status(self) -> dict[str, Any]:
        status = dict(self._last_status)
        remaining = self.cooldown_remaining_s()
        status["throttle_active"] = remaining > 0.0
        status["throttle_sleep_remaining_s"] = round(remaining, 3)
        status["cooldown_until"] = self._cooldown_until if remaining > 0.0 else None
        status["cooldown_count"] = self._cooldown_count
        return status

    def cooldown_remaining_s(self, now: float | None = None) -> float:
        now = time.time() if now is None else float(now)
        return max(0.0, self._cooldown_until - now)

    def before_refill(self) -> GpuResourceDecision:
        now = time.time()
        remaining = self.cooldown_remaining_s(now)
        if not self.enabled:
            return GpuResourceDecision(True, 0.0, self.status())
        if remaining > 0.0:
            status = self.status()
            status["last_decision"] = "cooling"
            self._last_status = status
            return GpuResourceDecision(False, remaining, status)
        last_sample_was_hot = bool(self._last_status.get("throttle_reasons"))
        if not last_sample_was_hot and (now - self._last_sample_at) < self.poll_s:
            status = self.status()
            status["last_decision"] = "within_poll_interval"
            self._last_status = status
            return GpuResourceDecision(True, 0.0, status)
        readings = self._sample()
        self._last_sample_at = now
        status = self._status_from_readings(readings, sampled_at=now)
        sleep_s = self._sleep_for_status(status)
        if sleep_s > 0.0:
            self._cooldown_until = now + sleep_s
            self._cooldown_count += 1
            status["last_decision"] = "throttle"
            status["throttle_active"] = True
            status["throttle_sleep_s"] = round(sleep_s, 3)
            status["cooldown_until"] = self._cooldown_until
        else:
            status["last_decision"] = "allow"
            status["throttle_active"] = False
            status["throttle_sleep_s"] = 0.0
            status["cooldown_until"] = None
        status["cooldown_count"] = self._cooldown_count
        self._last_status = status
        return GpuResourceDecision(sleep_s <= 0.0, sleep_s, self.status())

    def _sample(self) -> list[GpuResourceReading]:
        if self.sample_json:
            return _readings_from_json(self.sample_json, self.nodes)
        if not self.nodes:
            return []
        workers = min(self.sample_workers, len(self.nodes))
        out: list[GpuResourceReading] = []
        with ThreadPoolExecutor(max_workers=workers, thread_name_prefix="ds4-resource-sample") as executor:
            futures = {executor.submit(self._sample_node, node): node for node in self.nodes}
            for future in as_completed(futures):
                try:
                    out.append(future.result())
                except Exception as exc:
                    out.append(GpuResourceReading(node_id=futures[future], ok=False, error=str(exc)))
        return sorted(out, key=lambda item: item.node_id)

    def _sample_node(self, node_id: str) -> GpuResourceReading:
        query = "temperature.gpu,power.draw,utilization.gpu,memory.used,memory.total"
        fmt = "csv,noheader,nounits"
        argv = ["nvidia-smi", f"--query-gpu={query}", f"--format={fmt}"]
        if node_id != self.local_node_id:
            argv = ["ssh", "-o", "BatchMode=yes", "-o", "ConnectTimeout=2", node_id] + argv
        try:
            proc = subprocess.run(argv, text=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE, timeout=self.ssh_timeout_s, check=False)
        except Exception as exc:
            return GpuResourceReading(node_id=node_id, ok=False, error=str(exc))
        if proc.returncode != 0:
            return GpuResourceReading(node_id=node_id, ok=False, error=proc.stderr.strip() or f"exit {proc.returncode}")
        rows = [line.strip() for line in proc.stdout.splitlines() if line.strip()]
        if not rows:
            return GpuResourceReading(node_id=node_id, ok=False, error="empty nvidia-smi output")
        parsed = [_parse_nvidia_smi_row(row) for row in rows]
        host_memory = self._sample_host_memory(node_id)
        return GpuResourceReading(
            node_id=node_id,
            ok=True,
            temperature_c=max(_values(parsed, "temperature_c"), default=None),
            power_w=max(_values(parsed, "power_w"), default=None),
            utilization_pct=max(_values(parsed, "utilization_pct"), default=None),
            memory_used_mib=max(_values(parsed, "memory_used_mib"), default=None),
            memory_total_mib=max(_values(parsed, "memory_total_mib"), default=None),
            host_memory_used_mib=host_memory.get("host_memory_used_mib"),
            host_memory_total_mib=host_memory.get("host_memory_total_mib"),
            host_memory_used_pct=host_memory.get("host_memory_used_pct"),
        )

    def _sample_host_memory(self, node_id: str) -> dict[str, float | None]:
        argv = ["free", "-m"]
        if node_id != self.local_node_id:
            argv = ["ssh", "-o", "BatchMode=yes", "-o", "ConnectTimeout=2", node_id] + argv
        try:
            proc = subprocess.run(argv, text=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE, timeout=self.ssh_timeout_s, check=False)
        except Exception:
            return {}
        if proc.returncode != 0:
            return {}
        return _parse_free_m(proc.stdout)

    def _status_from_readings(self, readings: list[GpuResourceReading], *, sampled_at: float) -> dict[str, Any]:
        ok = [reading for reading in readings if reading.ok]
        failed = [reading for reading in readings if not reading.ok]
        temps = [reading.temperature_c for reading in ok if reading.temperature_c is not None]
        powers = [reading.power_w for reading in ok if reading.power_w is not None]
        utils = [reading.utilization_pct for reading in ok if reading.utilization_pct is not None]
        host_mem_pcts = [reading.host_memory_used_pct for reading in ok if reading.host_memory_used_pct is not None]
        max_temp = max(temps, default=None)
        max_power = max(powers, default=None)
        max_host_mem_pct = max(host_mem_pcts, default=None)
        total_power = sum(powers)
        reasons: list[str] = []
        if max_temp is not None and self.temp_hard_c > 0 and max_temp >= self.temp_hard_c:
            reasons.append("temp_hard")
        elif max_temp is not None and self.temp_soft_c > 0 and max_temp >= self.temp_soft_c:
            reasons.append("temp_soft")
        if max_power is not None and self.power_hard_w > 0 and max_power >= self.power_hard_w:
            reasons.append("power_hard")
        elif max_power is not None and self.power_soft_w > 0 and max_power >= self.power_soft_w:
            reasons.append("power_soft")
        if powers and self.total_power_hard_w > 0 and total_power >= self.total_power_hard_w:
            reasons.append("total_power_hard")
        elif powers and self.total_power_soft_w > 0 and total_power >= self.total_power_soft_w:
            reasons.append("total_power_soft")
        if max_host_mem_pct is not None and self.host_memory_hard_pct > 0 and max_host_mem_pct >= self.host_memory_hard_pct:
            reasons.append("host_memory_hard")
        elif max_host_mem_pct is not None and self.host_memory_soft_pct > 0 and max_host_mem_pct >= self.host_memory_soft_pct:
            reasons.append("host_memory_soft")
        hottest = max((reading for reading in ok if reading.temperature_c is not None), key=lambda item: float(item.temperature_c), default=None)
        power_peak = max((reading for reading in ok if reading.power_w is not None), key=lambda item: float(item.power_w), default=None)
        host_mem_peak = max((reading for reading in ok if reading.host_memory_used_pct is not None), key=lambda item: float(item.host_memory_used_pct), default=None)
        return {
            "enabled": self.enabled,
            "node_count": len(self.nodes),
            "sampled_at": sampled_at,
            "sampled_nodes": len(ok),
            "failed_nodes": [reading.to_public_dict() for reading in failed],
            "max_temp_c": max_temp,
            "max_temp_node": hottest.node_id if hottest is not None else None,
            "max_power_w": max_power,
            "max_power_node": power_peak.node_id if power_peak is not None else None,
            "total_power_w": round(total_power, 3) if powers else None,
            "max_utilization_pct": max(utils, default=None),
            "max_host_memory_used_pct": round(max_host_mem_pct, 3) if max_host_mem_pct is not None else None,
            "max_host_memory_node": host_mem_peak.node_id if host_mem_peak is not None else None,
            "thresholds": {
                "temp_soft_c": self.temp_soft_c,
                "temp_hard_c": self.temp_hard_c,
                "power_soft_w": self.power_soft_w,
                "power_hard_w": self.power_hard_w,
                "total_power_soft_w": self.total_power_soft_w,
                "total_power_hard_w": self.total_power_hard_w,
                "host_memory_soft_pct": self.host_memory_soft_pct,
                "host_memory_hard_pct": self.host_memory_hard_pct,
            },
            "throttle_reasons": reasons,
            "readings": [reading.to_public_dict() for reading in readings],
        }

    def _sleep_for_status(self, status: dict[str, Any]) -> float:
        reasons = set(str(item) for item in status.get("throttle_reasons") or [])
        if not reasons:
            return 0.0
        multiplier = 1.0
        if any(reason.endswith("_hard") for reason in reasons):
            multiplier = 2.0
        sleep_s = self.throttle_step_s * multiplier
        return min(self.throttle_max_s, max(0.0, sleep_s))

    def _initial_status(self) -> dict[str, Any]:
        return {
            "enabled": self.enabled,
            "node_count": len(self.nodes),
            "sampled_at": None,
            "sampled_nodes": 0,
            "failed_nodes": [],
            "max_temp_c": None,
            "max_temp_node": None,
            "max_power_w": None,
            "max_power_node": None,
            "total_power_w": None,
            "max_utilization_pct": None,
            "max_host_memory_used_pct": None,
            "max_host_memory_node": None,
            "throttle_active": False,
            "throttle_sleep_s": 0.0,
            "throttle_sleep_remaining_s": 0.0,
            "throttle_reasons": [],
            "cooldown_until": None,
            "cooldown_count": 0,
            "last_decision": "disabled" if not self.enabled else "not_sampled",
            "readings": [],
        }


def topology_governor_nodes(topology: Any, *, active_service_ids: set[str] | None) -> tuple[str, ...]:
    node_ids: list[str] = []
    if getattr(topology, "pipeline_services", None):
        for service in topology.pipeline_services.values():
            if active_service_ids is not None and service.service_id not in active_service_ids:
                continue
            node_ids.extend(str(node_id) for node_id in service.node_ids)
    if not node_ids:
        node_ids.extend(str(node.node_id) for node in topology.nodes if "production" in node.roles)
    return tuple(dict.fromkeys(node_ids))


def _readings_from_json(raw: str, nodes: tuple[str, ...]) -> list[GpuResourceReading]:
    text = raw.strip()
    path = Path(raw)
    if text and text[0] not in "{[" and path.exists():
        raw = path.read_text(encoding="utf-8")
    parsed = json.loads(raw)
    source = parsed.get("nodes", parsed) if isinstance(parsed, dict) else parsed
    readings: list[GpuResourceReading] = []
    if isinstance(source, dict):
        items = source.items()
    elif isinstance(source, list):
        items = [(item.get("node_id", f"node{index}"), item) for index, item in enumerate(source) if isinstance(item, dict)]
    else:
        items = []
    wanted = set(nodes)
    for node_id, item in items:
        node = str(node_id)
        if wanted and node not in wanted:
            continue
        if not isinstance(item, dict):
            continue
        host_used = _optional_float(item.get("host_memory_used_mib", item.get("host_mem_used_mib")))
        host_total = _optional_float(item.get("host_memory_total_mib", item.get("host_mem_total_mib")))
        host_pct = _optional_float(item.get("host_memory_used_pct", item.get("host_mem_pct", item.get("mem_pct"))))
        if host_pct is None:
            host_pct = _host_memory_pct(host_used, host_total)
        readings.append(
            GpuResourceReading(
                node_id=node,
                ok=bool(item.get("ok", True)),
                temperature_c=_optional_float(item.get("temperature_c", item.get("temp_c"))),
                power_w=_optional_float(item.get("power_w")),
                utilization_pct=_optional_float(item.get("utilization_pct", item.get("gpu_util"))),
                memory_used_mib=_optional_float(item.get("memory_used_mib")),
                memory_total_mib=_optional_float(item.get("memory_total_mib")),
                host_memory_used_mib=host_used,
                host_memory_total_mib=host_total,
                host_memory_used_pct=host_pct,
                error=str(item.get("error")) if item.get("error") is not None else None,
            )
        )
    return readings


def _parse_free_m(text: str) -> dict[str, float | None]:
    for line in text.splitlines():
        parts = line.split()
        if len(parts) >= 3 and parts[0] == "Mem:":
            total = _optional_float(parts[1])
            used = _optional_float(parts[2])
            return {
                "host_memory_used_mib": used,
                "host_memory_total_mib": total,
                "host_memory_used_pct": _host_memory_pct(used, total),
            }
    return {}


def _host_memory_pct(used: float | None, total: float | None) -> float | None:
    if used is None or total is None or total <= 0:
        return None
    return (float(used) / float(total)) * 100.0


def _parse_nvidia_smi_row(row: str) -> dict[str, float | None]:
    parts = [part.strip() for part in row.split(",")]
    return {
        "temperature_c": _optional_float(parts[0] if len(parts) > 0 else None),
        "power_w": _optional_float(parts[1] if len(parts) > 1 else None),
        "utilization_pct": _optional_float(parts[2] if len(parts) > 2 else None),
        "memory_used_mib": _optional_float(parts[3] if len(parts) > 3 else None),
        "memory_total_mib": _optional_float(parts[4] if len(parts) > 4 else None),
    }


def _values(rows: list[dict[str, float | None]], key: str) -> list[float]:
    return [float(row[key]) for row in rows if row.get(key) is not None]


def _optional_float(value: Any) -> float | None:
    if value is None:
        return None
    text = str(value).strip()
    if not text or text.lower() in {"n/a", "nan", "none"}:
        return None
    try:
        return float(text)
    except ValueError:
        return None


def _env_bool(name: str, default: bool) -> bool:
    raw = os.environ.get(name)
    if raw is None:
        return bool(default)
    return raw.strip().lower() in {"1", "true", "yes", "on"}


def _env_int(name: str, default: int) -> int:
    try:
        return int(os.environ.get(name, str(default)))
    except (TypeError, ValueError):
        return int(default)


def _env_float(name: str, default: float) -> float:
    try:
        return float(os.environ.get(name, str(default)))
    except (TypeError, ValueError):
        return float(default)
