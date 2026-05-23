#!/usr/bin/env python3
"""Strict Spark-local proposal client for diamond refinement."""

from __future__ import annotations

import json
import re
import urllib.request
from dataclasses import dataclass
from typing import Any, Callable
from urllib.parse import urlparse

from scripts import qualify_small_model as qualify


class DiamondLocalModelError(RuntimeError):
    pass


_CommandRunner = Callable[[list[str], float], dict[str, Any]]
_FRONTIER_HOST_MARKERS = (
    "api.anthropic.com",
    "api.openai.com",
    "generativelanguage.googleapis.com",
)


def _build_refactor_prompt(source: str, candidate_kind: str) -> str:
    return (
        "You are a local Spark2 code-refinement worker. Reduce the Python "
        "source below while preserving behavior exactly. Remove single-caller "
        "helpers when that makes the code shorter. Return only the complete "
        "replacement Python source, no prose.\n\n"
        f"Candidate kind: {candidate_kind}\n\n"
        "SOURCE:\n"
        f"{source}"
    )


def _extract_candidate_source(text: str) -> str:
    stripped = text.strip()
    fenced = re.search(r"```(?:python)?\s*(.*?)```", stripped, re.DOTALL)
    if fenced is not None:
        return fenced.group(1).strip() + "\n"
    return stripped + "\n"


def _validate_endpoint(endpoint: str) -> None:
    parsed = urlparse(endpoint)
    host = (parsed.hostname or "").lower()
    if not parsed.scheme or not host:
        raise DiamondLocalModelError("Spark-local endpoint must be an absolute HTTP URL")
    if parsed.scheme not in {"http", "https"}:
        raise DiamondLocalModelError("Spark-local endpoint must use HTTP")
    if any(host == marker or host.endswith("." + marker) for marker in _FRONTIER_HOST_MARKERS):
        raise DiamondLocalModelError("frontier endpoints are forbidden for diamond refinement")


@dataclass(frozen=True)
class DiamondLocalModelClient:
    endpoint: str
    provider_id: str = "spark2-local-small"
    timeout_seconds: float = 30.0

    def propose_refactor(self, source: str, candidate_kind: str) -> dict[str, Any]:
        if not self.endpoint:
            raise DiamondLocalModelError(
                "Spark-local endpoint is required; no fallback provider is allowed"
            )
        _validate_endpoint(self.endpoint)
        prompt = _build_refactor_prompt(source, candidate_kind)
        payload = {
            "task": "diamond_refactor",
            "candidate_kind": candidate_kind,
            "source": source,
            "prompt": prompt,
        }
        request = urllib.request.Request(
            self.endpoint,
            data=json.dumps(payload).encode("utf-8"),
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        with urllib.request.urlopen(request, timeout=self.timeout_seconds) as response:
            record = json.loads(response.read().decode("utf-8"))
        candidate = self._candidate_from_response(record)
        return {
            "provider_id": self.provider_id,
            "api_style": "custom",
            "candidate_kind": candidate_kind,
            "candidate_source": candidate,
            "raw_response": record,
        }

    def _candidate_from_response(self, record: dict[str, Any]) -> str:
        if not isinstance(record, dict):
            raise DiamondLocalModelError("Spark-local response must be a JSON object")
        candidate = record.get("candidate_source")
        if not isinstance(candidate, str):
            raise DiamondLocalModelError("Spark-local response must contain candidate_source")
        return _extract_candidate_source(candidate)


@dataclass(frozen=True)
class DiamondSshTransformersClient:
    host: str
    model_path: str
    provider_id: str = "spark2-transformers-local"
    python_executable: str = "python3"
    max_new_tokens: int = 512
    timeout_seconds: float = 180.0
    runner: _CommandRunner = qualify.default_command_runner

    def propose_refactor(self, source: str, candidate_kind: str) -> dict[str, Any]:
        if not self.host or not self.model_path:
            raise DiamondLocalModelError("Spark2 host and model path are required")
        prompt = _build_refactor_prompt(source, candidate_kind)
        command = self._command(prompt)
        result = self.runner(command, self.timeout_seconds)
        stderr = str(result.get("stderr") or "")
        if int(result.get("returncode") or 0) != 0:
            raise DiamondLocalModelError(
                f"Spark2 transformers command failed rc={int(result.get('returncode') or 0)} stderr={stderr[-1000:]}"
            )
        parsed = qualify.extract_transformers_result(str(result.get("stdout") or ""))
        candidate = _extract_candidate_source(str(parsed["generated_text"]))
        return {
            "provider_id": self.provider_id,
            "api_style": "spark-ssh-transformers",
            "candidate_kind": candidate_kind,
            "candidate_source": candidate,
            "generated_token_count": int(parsed.get("generated_token_count") or 0),
            "elapsed_seconds": float(result.get("elapsed_seconds") or 0.0),
        }

    def _command(self, prompt: str) -> list[str]:
        return qualify.build_transformers_command(
            self.host,
            self.python_executable,
            self.model_path,
            prompt,
            int(self.max_new_tokens),
            self.timeout_seconds,
        )
