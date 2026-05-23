#!/usr/bin/env python3
"""Strict Spark-local proposal client for diamond refinement."""

from __future__ import annotations

import json
import urllib.request
from dataclasses import dataclass
from typing import Any


class DiamondLocalModelError(RuntimeError):
    pass


@dataclass(frozen=True)
class DiamondLocalModelClient:
    endpoint: str
    timeout_seconds: float = 30.0

    def propose_refactor(self, source: str, candidate_kind: str) -> dict[str, Any]:
        if not self.endpoint:
            raise DiamondLocalModelError(
                "Spark-local endpoint is required; no fallback provider is allowed"
            )
        payload = json.dumps({
            "task": "diamond_refactor",
            "candidate_kind": candidate_kind,
            "source": source,
        }).encode("utf-8")
        request = urllib.request.Request(
            self.endpoint,
            data=payload,
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        with urllib.request.urlopen(request, timeout=self.timeout_seconds) as response:
            record = json.loads(response.read().decode("utf-8"))
        if not isinstance(record, dict) or not isinstance(record.get("candidate_source"), str):
            raise DiamondLocalModelError("Spark-local response must contain candidate_source")
        return record
