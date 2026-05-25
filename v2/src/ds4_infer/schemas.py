from __future__ import annotations
from dataclasses import dataclass
from typing import Any

REQUEST_FORMAT = "ds4-inference-request-v1"
RESULT_FORMAT = "ds4-inference-result-v1"
BATCH_MANIFEST_FORMAT = "ds4-inference-batch-manifest-v1"

@dataclass(frozen=True)
class InferenceRequest:
    request_id: str
    capability: str | None
    chat: bool
    immediate: bool
    job_class: str
    max_output_tokens: int
    thinking_budget_tokens: int
    temperature: float
    input: dict[str, Any]
    output_contract: dict[str, Any]
    model_pin: dict[str, Any] | None
    raw: dict[str, Any]

    @staticmethod
    def from_json(data: dict[str, Any]) -> "InferenceRequest":
        if data.get("format") != REQUEST_FORMAT:
            raise ValueError(f"unsupported request format: {data.get('format')!r}")
        required = ["request_id", "chat", "immediate", "job_class", "max_output_tokens", "thinking_budget_tokens", "input", "output_contract"]
        missing = [key for key in required if key not in data]
        if missing:
            raise ValueError(f"inference request missing fields: {missing}")
        max_output_tokens = int(data["max_output_tokens"])
        thinking_budget_tokens = int(data["thinking_budget_tokens"])
        if max_output_tokens < 1:
            raise ValueError("max_output_tokens must be positive")
        if thinking_budget_tokens < 0:
            raise ValueError("thinking_budget_tokens must be non-negative")
        return InferenceRequest(
            request_id=str(data["request_id"]),
            capability=data.get("capability"),
            chat=bool(data["chat"]),
            immediate=bool(data["immediate"]),
            job_class=str(data["job_class"]),
            max_output_tokens=max_output_tokens,
            thinking_budget_tokens=thinking_budget_tokens,
            temperature=float(data.get("temperature", 0.0)),
            input=dict(data["input"]),
            output_contract=dict(data["output_contract"]),
            model_pin=data.get("model_pin"),
            raw=dict(data),
        )

def make_result(*, request: InferenceRequest, profile_id: str, model_id: str, backend: str, text: str, status: str = "completed") -> dict[str, Any]:
    return {
        "format": RESULT_FORMAT,
        "request_id": request.request_id,
        "status": status,
        "selected_profile": {"profile_id": profile_id, "model_id": model_id, "backend": backend},
        "output": {"text": text},
        "usage": {"max_output_tokens": request.max_output_tokens, "thinking_budget_tokens": request.thinking_budget_tokens},
    }
