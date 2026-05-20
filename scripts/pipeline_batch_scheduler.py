#!/usr/bin/env python3
"""K-slot row-replacement scheduler for DS4 pipeline generation."""

from __future__ import annotations

import argparse
from collections import Counter, deque
from dataclasses import dataclass, field
import json
from pathlib import Path
import sys
import time
from typing import Any, Iterable, Protocol, Sequence


class PipelineBatchSchedulerError(ValueError):
	pass


@dataclass(frozen=True)
class PromptRequest:
	request_id: str
	prompt: str
	max_tokens: int


@dataclass(frozen=True)
class DecodeRow:
	row_index: int
	request_id: str
	prompt: str
	generated_token_ids: tuple[int, ...]
	max_tokens: int
	active: bool


@dataclass(frozen=True)
class DecodeToken:
	row_index: int
	token_id: int | None
	eos: bool = False
	text: str = ""


@dataclass(frozen=True)
class GenerationResult:
	request_id: str
	prompt: str
	max_tokens: int
	token_ids: tuple[int, ...]
	text: str
	row_index: int
	finish_reason: str
	start_wall_time: float
	end_wall_time: float


@dataclass(frozen=True)
class BatchRunSummary:
	k: int
	request_count: int
	generated_token_count: int
	decode_cycles: int
	aggregate_tok_s: float
	wall_seconds: float
	results: tuple[GenerationResult, ...]
	events_path: str
	row_admit_counts: dict[int, int] = field(default_factory=dict)

	def to_jsonable(self) -> dict[str, Any]:
		return {
			"k": self.k,
			"request_count": self.request_count,
			"generated_token_count": self.generated_token_count,
			"decode_cycles": self.decode_cycles,
			"aggregate_tok_s": self.aggregate_tok_s,
			"wall_seconds": self.wall_seconds,
			"events_path": self.events_path,
			"row_admit_counts": {str(k): v for k, v in sorted(self.row_admit_counts.items())},
			"results": [
				{
					"request_id": r.request_id,
					"prompt": r.prompt,
					"max_tokens": r.max_tokens,
					"token_ids": list(r.token_ids),
					"text": r.text,
					"row_index": r.row_index,
					"finish_reason": r.finish_reason,
					"start_wall_time": r.start_wall_time,
					"end_wall_time": r.end_wall_time,
				}
				for r in self.results
			],
		}


class PipelineBatchBackend(Protocol):
	def prefill_row(self, row_index: int, request: PromptRequest) -> None:
		...

	def decode_batch(self, rows: Sequence[DecodeRow]) -> Sequence[DecodeToken]:
		...

	def reset_row(self, row_index: int) -> None:
		...


@dataclass
class _SlotState:
	request: PromptRequest
	token_ids: list[int]
	text_parts: list[str]
	start_wall_time: float


class SchedulerEventWriter:
	def __init__(self, path: Path | None):
		self.path = path
		self._fh = None

	def __enter__(self) -> "SchedulerEventWriter":
		if self.path is not None:
			self.path.parent.mkdir(parents=True, exist_ok=True)
			self._fh = self.path.open("w", encoding="utf-8")
		return self

	def __exit__(self, exc_type: object, exc: object, tb: object) -> None:
		if self._fh is not None:
			self._fh.close()
			self._fh = None

	def write(self, event: dict[str, Any]) -> None:
		if self._fh is not None:
			self._fh.write(json.dumps(event, sort_keys=True, separators=(",", ":")) + "\n")
			self._fh.flush()


class PipelineBatchScheduler:
	def __init__(self, backend: PipelineBatchBackend, k: int):
		if k <= 0:
			raise PipelineBatchSchedulerError("k must be positive")
		self.backend = backend
		self.k = int(k)
		self._slots: list[_SlotState | None] = [None for _ in range(self.k)]

	def run(self, requests: Sequence[PromptRequest], events_path: Path | None) -> BatchRunSummary:
		checked = _validate_requests(requests)
		pending = deque(checked)
		results: list[GenerationResult] = []
		admit_counts: Counter[int] = Counter()
		decode_cycles = 0
		start_perf = time.perf_counter()
		with SchedulerEventWriter(events_path) as event_writer:
			self._admit_pending(pending, event_writer, admit_counts)
			while pending or any(slot is not None for slot in self._slots):
				rows = self._decode_rows()
				outputs = self.backend.decode_batch(rows)
				decode_cycles += 1
				finished_rows = self._apply_outputs(outputs, results, event_writer)
				for row_index in finished_rows:
					self.backend.reset_row(row_index)
					self._slots[row_index] = None
				self._admit_pending(pending, event_writer, admit_counts)
		wall = max(time.perf_counter() - start_perf, 0.0)
		total_tokens = sum(len(result.token_ids) for result in results)
		aggregate = (float(total_tokens) / wall) if wall > 0.0 else 0.0
		return BatchRunSummary(
			k=self.k,
			request_count=len(checked),
			generated_token_count=total_tokens,
			decode_cycles=decode_cycles,
			aggregate_tok_s=aggregate,
			wall_seconds=wall,
			results=tuple(results),
			events_path=str(events_path) if events_path is not None else "",
			row_admit_counts=dict(admit_counts),
		)

	def _admit_pending(
		self,
		pending: deque[PromptRequest],
		event_writer: SchedulerEventWriter,
		admit_counts: Counter[int],
	) -> None:
		for row_index, slot in enumerate(self._slots):
			if slot is not None or not pending:
				continue
			request = pending.popleft()
			self.backend.prefill_row(row_index, request)
			admit_counts[row_index] += 1
			now = time.time()
			self._slots[row_index] = _SlotState(
				request=request,
				token_ids=[],
				text_parts=[],
				start_wall_time=now,
			)
			event_writer.write(_event("admit", row_index, request.request_id, 0, len(pending)))

	def _decode_rows(self) -> list[DecodeRow]:
		rows: list[DecodeRow] = []
		for row_index, slot in enumerate(self._slots):
			if slot is None:
				rows.append(DecodeRow(row_index, "", "", tuple(), 0, False))
			else:
				rows.append(
					DecodeRow(
						row_index=row_index,
						request_id=slot.request.request_id,
						prompt=slot.request.prompt,
						generated_token_ids=tuple(slot.token_ids),
						max_tokens=slot.request.max_tokens,
						active=True,
					)
				)
		return rows

	def _apply_outputs(
		self,
		outputs: Sequence[DecodeToken],
		results: list[GenerationResult],
		event_writer: SchedulerEventWriter,
	) -> list[int]:
		output_by_row = _outputs_by_row(outputs, self.k)
		finished_rows: list[int] = []
		for row_index, slot in enumerate(self._slots):
			if slot is None:
				continue
			out = output_by_row.get(row_index)
			if out is None:
				raise PipelineBatchSchedulerError(f"active row {row_index} missing decode output")
			if out.token_id is not None:
				slot.token_ids.append(int(out.token_id))
			elif out.eos is False:
				raise PipelineBatchSchedulerError(f"active row {row_index} emitted neither token nor eos")
			if out.text:
				slot.text_parts.append(out.text)
			finish_reason = ""
			if out.eos:
				finish_reason = "eos"
			if len(slot.token_ids) >= slot.request.max_tokens:
				finish_reason = "max_tokens"
			if finish_reason:
				now = time.time()
				results.append(
					GenerationResult(
						request_id=slot.request.request_id,
						prompt=slot.request.prompt,
						max_tokens=slot.request.max_tokens,
						token_ids=tuple(slot.token_ids),
						text="".join(slot.text_parts),
						row_index=row_index,
						finish_reason=finish_reason,
						start_wall_time=slot.start_wall_time,
						end_wall_time=now,
					)
				)
				event_writer.write(
					_event(
						"evict",
						row_index,
						slot.request.request_id,
						len(slot.token_ids),
						0,
						finish_reason,
					)
				)
				finished_rows.append(row_index)
		return finished_rows


def _validate_requests(requests: Sequence[PromptRequest]) -> tuple[PromptRequest, ...]:
	if not requests:
		raise PipelineBatchSchedulerError("at least one request is required")
	seen: set[str] = set()
	checked: list[PromptRequest] = []
	for request in requests:
		if not isinstance(request.request_id, str) or request.request_id.strip() == "":
			raise PipelineBatchSchedulerError("request_id must be non-empty")
		if request.request_id in seen:
			raise PipelineBatchSchedulerError(f"duplicate request_id: {request.request_id}")
		if not isinstance(request.prompt, str) or request.prompt == "":
			raise PipelineBatchSchedulerError(f"{request.request_id}: prompt must be non-empty")
		if int(request.max_tokens) <= 0:
			raise PipelineBatchSchedulerError(f"{request.request_id}: max_tokens must be positive")
		seen.add(request.request_id)
		checked.append(PromptRequest(request.request_id, request.prompt, int(request.max_tokens)))
	return tuple(checked)


def _outputs_by_row(outputs: Sequence[DecodeToken], k: int) -> dict[int, DecodeToken]:
	result: dict[int, DecodeToken] = {}
	for out in outputs:
		if out.row_index < 0 or out.row_index >= k:
			raise PipelineBatchSchedulerError(f"decode output row out of range: {out.row_index}")
		if out.row_index in result:
			raise PipelineBatchSchedulerError(f"duplicate decode output for row: {out.row_index}")
		result[out.row_index] = out
	return result


def _event(
	event: str,
	row_index: int,
	request_id: str,
	generated_token_count: int,
	pending_count: int,
	finish_reason: str = "",
) -> dict[str, Any]:
	obj: dict[str, Any] = {
		"event": event,
		"row_index": row_index,
		"request_id": request_id,
		"wall_time": time.time(),
		"wall_time_ns": time.time_ns(),
		"generated_token_count": generated_token_count,
		"pending_count": pending_count,
	}
	if finish_reason:
		obj["finish_reason"] = finish_reason
	return obj


def load_requests(path: Path) -> list[PromptRequest]:
	obj = json.loads(path.read_text(encoding="utf-8"))
	if isinstance(obj, dict):
		raw_items = obj.get("requests")
	else:
		raw_items = obj
	if not isinstance(raw_items, list):
		raise PipelineBatchSchedulerError("request file must be a list or object with requests")
	requests: list[PromptRequest] = []
	for idx, item in enumerate(raw_items):
		if not isinstance(item, dict):
			raise PipelineBatchSchedulerError(f"request {idx} must be an object")
		requests.append(
			PromptRequest(
				request_id=str(item.get("request_id", item.get("id", f"req{idx}"))),
				prompt=str(item.get("prompt", "")),
				max_tokens=int(item.get("max_tokens", 0)),
			)
		)
	return list(_validate_requests(requests))


def write_summary(path: Path, summary: BatchRunSummary) -> None:
	path.parent.mkdir(parents=True, exist_ok=True)
	path.write_text(json.dumps(summary.to_jsonable(), indent=2, sort_keys=True) + "\n", encoding="utf-8")


def _backend_from_module(module_name: str, args: argparse.Namespace) -> PipelineBatchBackend:
	module = __import__(module_name, fromlist=["make_pipeline_batch_backend"])
	factory = getattr(module, "make_pipeline_batch_backend")
	return factory(args)


def build_parser() -> argparse.ArgumentParser:
	ap = argparse.ArgumentParser(description="Run K-slot row replacement over a DS4 pipeline backend.")
	ap.add_argument("--requests", required=True, help="JSON request list with request_id, prompt, max_tokens.")
	ap.add_argument("--out-dir", required=True)
	ap.add_argument("--k", type=int, required=True)
	ap.add_argument("--backend-module", required=True, help="Module exposing make_pipeline_batch_backend(args).")
	return ap


def main(argv: Iterable[str] | None = None) -> int:
	args = build_parser().parse_args(list(argv) if argv is not None else None)
	out_dir = Path(args.out_dir)
	requests = load_requests(Path(args.requests))
	backend = _backend_from_module(args.backend_module, args)
	events_path = out_dir / "scheduler_events.jsonl"
	summary = PipelineBatchScheduler(backend, args.k).run(requests, events_path)
	write_summary(out_dir / "batch_scheduler_summary.json", summary)
	print(json.dumps(summary.to_jsonable(), indent=2, sort_keys=True))
	return 0


if __name__ == "__main__":
	raise SystemExit(main())
