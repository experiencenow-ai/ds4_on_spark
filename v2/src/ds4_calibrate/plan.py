from __future__ import annotations
from dataclasses import dataclass
import json
from typing import Any

@dataclass(frozen=True)
class CalibrationPoint:
    profile_id: str
    mode: str
    batch_size: int
    input_bucket: str
    output_bucket: str
    thinking_bucket: str
    def to_json(self) -> dict[str, Any]:
        return {"format": "ds4-calibration-point-v1", "profile_id": self.profile_id, "mode": self.mode, "batch_size": self.batch_size, "input_bucket": self.input_bucket, "output_bucket": self.output_bucket, "thinking_bucket": self.thinking_bucket}

def build_calibration_plan(*, profile_id: str, modes: list[str] | None = None, batch_sizes: list[int] | None = None, input_buckets: list[str] | None = None, output_buckets: list[str] | None = None, thinking_buckets: list[str] | None = None) -> list[CalibrationPoint]:
    modes = modes or ["completion", "chat"]
    batch_sizes = batch_sizes or [1, 2, 4, 8, 16, 32]
    input_buckets = input_buckets or ["0_1k", "1k_4k"]
    output_buckets = output_buckets or ["0_256", "256_768"]
    thinking_buckets = thinking_buckets or ["none"]
    return [CalibrationPoint(profile_id, mode, batch_size, input_bucket, output_bucket, thinking_bucket) for mode in modes for input_bucket in input_buckets for output_bucket in output_buckets for thinking_bucket in thinking_buckets for batch_size in batch_sizes]

def write_plan_jsonl(points: list[CalibrationPoint]) -> str:
    return "".join(json.dumps(point.to_json(), sort_keys=True) + "\n" for point in points)
