#!/usr/bin/env python3
from __future__ import annotations

import argparse
import dataclasses
import json
from dataclasses import dataclass
from typing import Sequence


@dataclass(frozen=True)
class StageTiming:
	label: str
	compute_ms: float
	transfer_ms: float

	@property
	def interval_ms(self) -> float:
		return self.compute_ms + self.transfer_ms


@dataclass(frozen=True)
class PipelineResult:
	microbatches: int
	stage_count: int
	single_spark_ms_per_microbatch: float
	pipeline_wall_ms: float
	serial_wall_ms: float
	bottleneck_stage: int
	bottleneck_interval_ms: float
	steady_state_microbatches_per_s: float
	actual_microbatches_per_s: float
	speedup_vs_serial: float
	bubble_overhead_ratio: float
	stage_balance_ratio: float
	stages: tuple[StageTiming, ...]

	def to_dict(self) -> dict[str, object]:
		return {
			"microbatches": self.microbatches,
			"stage_count": self.stage_count,
			"single_spark_ms_per_microbatch": self.single_spark_ms_per_microbatch,
			"pipeline_wall_ms": self.pipeline_wall_ms,
			"serial_wall_ms": self.serial_wall_ms,
			"bottleneck_stage": self.bottleneck_stage,
			"bottleneck_interval_ms": self.bottleneck_interval_ms,
			"steady_state_microbatches_per_s": self.steady_state_microbatches_per_s,
			"actual_microbatches_per_s": self.actual_microbatches_per_s,
			"speedup_vs_serial": self.speedup_vs_serial,
			"bubble_overhead_ratio": self.bubble_overhead_ratio,
			"stage_balance_ratio": self.stage_balance_ratio,
			"stages": [dataclasses.asdict(stage) for stage in self.stages],
		}


def parse_float_list(text: str) -> list[float]:
	items = [item.strip() for item in text.replace(" ", ",").split(",") if item.strip()]
	return [float(item) for item in items]


def parse_int_list(text: str) -> list[int]:
	items = [item.strip() for item in text.replace(" ", ",").split(",") if item.strip()]
	return [int(item) for item in items]


def normalize_transfers(stage_count: int, transfer_ms: Sequence[float]) -> list[float]:
	if len(transfer_ms) == 0:
		return [0.0 for _ in range(stage_count)]
	if len(transfer_ms) == stage_count - 1:
		return list(transfer_ms) + [0.0]
	if len(transfer_ms) == stage_count:
		return list(transfer_ms)
	raise ValueError("transfer-ms must have either stage_count-1 or stage_count values")


def build_stages(stage_compute_ms: Sequence[float], transfer_ms: Sequence[float]) -> tuple[StageTiming, ...]:
	if len(stage_compute_ms) == 0:
		raise ValueError("at least one stage is required")
	transfers = normalize_transfers(len(stage_compute_ms), transfer_ms)
	stages = []
	for i, compute_ms in enumerate(stage_compute_ms):
		if compute_ms <= 0.0:
			raise ValueError("stage compute times must be positive")
		if transfers[i] < 0.0:
			raise ValueError("transfer times must be non-negative")
		stages.append(StageTiming(label=f"stage{i}", compute_ms=float(compute_ms), transfer_ms=float(transfers[i])))
	return tuple(stages)


def simulate(stage_compute_ms: Sequence[float], transfer_ms: Sequence[float], microbatches: int) -> PipelineResult:
	if microbatches <= 0:
		raise ValueError("microbatches must be positive")
	stages = build_stages(stage_compute_ms, transfer_ms)
	intervals = [stage.interval_ms for stage in stages]
	single_ms = sum(intervals)
	bottleneck_ms = max(intervals)
	bottleneck_stage = intervals.index(bottleneck_ms)
	pipeline_wall_ms = single_ms + ((microbatches - 1) * bottleneck_ms)
	serial_wall_ms = single_ms * microbatches
	steady_state_mbs = 1000.0 / bottleneck_ms
	actual_mbs = (1000.0 * microbatches) / pipeline_wall_ms
	speedup = serial_wall_ms / pipeline_wall_ms
	bubble_ms = max(0.0, pipeline_wall_ms - (microbatches * bottleneck_ms))
	balance = bottleneck_ms / (sum(intervals) / len(intervals))
	return PipelineResult(
		microbatches=microbatches,
		stage_count=len(stages),
		single_spark_ms_per_microbatch=single_ms,
		pipeline_wall_ms=pipeline_wall_ms,
		serial_wall_ms=serial_wall_ms,
		bottleneck_stage=bottleneck_stage,
		bottleneck_interval_ms=bottleneck_ms,
		steady_state_microbatches_per_s=steady_state_mbs,
		actual_microbatches_per_s=actual_mbs,
		speedup_vs_serial=speedup,
		bubble_overhead_ratio=bubble_ms / pipeline_wall_ms,
		stage_balance_ratio=balance,
		stages=stages,
	)


def balanced_stage_ms(single_ms: float, stage_count: int) -> list[float]:
	if single_ms <= 0.0:
		raise ValueError("single-ms must be positive")
	if stage_count <= 0:
		raise ValueError("stage count must be positive")
	return [single_ms / stage_count for _ in range(stage_count)]


def sweep(stage_compute_ms: Sequence[float], transfer_ms: Sequence[float], microbatches: Sequence[int]) -> list[PipelineResult]:
	return [simulate(stage_compute_ms, transfer_ms, m) for m in microbatches]


def print_markdown(rows: Sequence[PipelineResult]) -> None:
	print("| stages | M | wall ms | bottleneck stage | bottleneck ms | actual mb/s | steady mb/s | speedup | bubble | balance |")
	print("| ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: |")
	for row in rows:
		print(
			f"| {row.stage_count} | {row.microbatches} | {row.pipeline_wall_ms:.3f} "
			f"| {row.bottleneck_stage} | {row.bottleneck_interval_ms:.3f} "
			f"| {row.actual_microbatches_per_s:.3f} | {row.steady_state_microbatches_per_s:.3f} "
			f"| {row.speedup_vs_serial:.3f}x | {row.bubble_overhead_ratio:.3f} "
			f"| {row.stage_balance_ratio:.3f} |"
		)


def main() -> int:
	parser = argparse.ArgumentParser(description="Simulate contiguous DS4 layer-stage pipeline throughput.")
	parser.add_argument("--stage-ms", default="", help="Comma/space separated per-stage compute milliseconds.")
	parser.add_argument("--transfer-ms", default="", help="Comma/space separated transfer ms after each stage.")
	parser.add_argument("--single-ms", type=float, default=0.0, help="Single-device ms to split evenly when sweeping stages.")
	parser.add_argument("--sweep-stages", default="", help="Stage counts for balanced sweep, e.g. '1,2,3'.")
	parser.add_argument("--microbatches", default="1,2,4,8,16,32", help="Microbatch counts to simulate.")
	parser.add_argument("--json", action="store_true", help="Emit JSON instead of Markdown.")
	args = parser.parse_args()
	microbatches = parse_int_list(args.microbatches)
	transfer_ms = parse_float_list(args.transfer_ms) if args.transfer_ms else []
	rows: list[PipelineResult] = []
	if args.sweep_stages:
		if args.single_ms <= 0.0:
			raise SystemExit("--single-ms is required with --sweep-stages")
		for stage_count in parse_int_list(args.sweep_stages):
			stage_ms = balanced_stage_ms(args.single_ms, stage_count)
			xfer = transfer_ms
			if len(xfer) == 1 and stage_count == 1:
				xfer = []
			elif len(xfer) == 1 and stage_count > 1:
				xfer = [xfer[0] for _ in range(stage_count - 1)]
			rows.extend(sweep(stage_ms, xfer, microbatches))
	else:
		if not args.stage_ms:
			raise SystemExit("--stage-ms or --single-ms with --sweep-stages is required")
		rows.extend(sweep(parse_float_list(args.stage_ms), transfer_ms, microbatches))
	if args.json:
		print(json.dumps({"ok": True, "rows": [row.to_dict() for row in rows]}, indent=2, sort_keys=True))
	else:
		print_markdown(rows)
	return 0


if __name__ == "__main__":
	raise SystemExit(main())
