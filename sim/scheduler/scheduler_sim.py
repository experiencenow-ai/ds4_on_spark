#!/usr/bin/env python3
from __future__ import annotations

import argparse
import csv
import dataclasses
import enum
import heapq
import json
import math
import random
import statistics
import sys
from collections import deque
from dataclasses import dataclass
from typing import Deque, Dict, Iterable, List, Optional, Sequence, Tuple


class LatencyClass(str, enum.Enum):
    INTERACTIVE = "interactive"
    BATCH = "batch"


class MtpPhase(enum.IntEnum):
    NONE = 0
    DRAFT = 1
    VERIFY = 2


@dataclass(frozen=True)
class LayerRoute:
    candidates: Tuple[int, ...]
    k: Optional[int] = None
    scores: Optional[Tuple[float, ...]] = None
    cost_scale: Optional[float] = None


@dataclass(frozen=True)
class TokenRoute:
    t_ms: float
    cls: LatencyClass
    candidates: Tuple[int, ...]
    token_index: Optional[int] = None
    k: Optional[int] = None
    scores: Optional[Tuple[float, ...]] = None
    mtp_accept_len: Optional[int] = None
    accepted_mtp: Optional[int] = None
    rejected_mtp: Optional[int] = None
    dflash_accept_len: Optional[int] = None
    accepted_dflash: Optional[int] = None
    rejected_dflash: Optional[int] = None
    cost_scale: Optional[float] = None
    decode_ms: Optional[float] = None
    kv_tokens: Optional[int] = None
    expert_batch_size: Optional[int] = None
    layers: Optional[Tuple[LayerRoute, ...]] = None


@dataclass(frozen=True)
class TraceConfig:
    num_tokens: int
    num_experts: int
    num_candidates: int
    interactive_prob: float
    arrival_rate_tps: float
    burst_prob: float
    burst_scale: float
    zipf_alpha: float
    seed: int
    num_layers: int = 1
    synthetic_score_mode: str = "none"
    synthetic_cost_scale_mode: str = "none"
    synthetic_cost_scale_log_sigma: float = 0.5


@dataclass(frozen=True)
class HotsetTraceConfig:
    num_tokens: int
    num_experts: int
    num_candidates: int
    interactive_prob: float
    arrival_rate_tps: float
    burst_prob: float
    burst_scale: float
    hotset_size: int
    hotset_bias: float
    hotset_rotate_every_tokens: int
    seed: int
    num_layers: int = 1
    synthetic_score_mode: str = "none"
    synthetic_cost_scale_mode: str = "none"
    synthetic_cost_scale_log_sigma: float = 0.5


@dataclass(frozen=True)
class MarkovTraceConfig:
    num_tokens: int
    num_experts: int
    num_candidates: int
    interactive_prob: float
    arrival_rate_tps: float
    burst_prob: float
    burst_scale: float
    zipf_alpha: float
    stay_prob: float
    seed: int
    num_layers: int = 1
    synthetic_score_mode: str = "none"
    synthetic_cost_scale_mode: str = "none"
    synthetic_cost_scale_log_sigma: float = 0.5


@dataclass(frozen=True)
class TwoStreamTraceConfig:
    num_tokens: int
    num_experts: int
    num_candidates: int
    interactive_arrival_rate_tps: float
    batch_arrival_rate_tps: float
    interactive_burst_prob: float
    interactive_burst_scale: float
    batch_burst_prob: float
    batch_burst_scale: float
    zipf_alpha: float
    seed: int
    num_layers: int = 1
    synthetic_score_mode: str = "none"
    synthetic_cost_scale_mode: str = "none"
    synthetic_cost_scale_log_sigma: float = 0.5


@dataclass(frozen=True)
class AdaptiveKConfig:
    k_min_interactive: int
    k_max_interactive: int
    k_min_batch: int
    k_max_batch: int
    q_low: int
    q_high: int
    ema_alpha: float = 1.0
    update_ms: float = 0.0
    k_slew: int = 0


@dataclass(frozen=True)
class SimConfig:
    num_experts: int
    expert_parallelism: int
    expert_queue_max: int
    service_ms: float
    starvation_ms: float
    hi_burst: int
    promote_ms: float
    adaptive_k: AdaptiveKConfig
    expert_queue_reserve_interactive: int = 0
    k_mode: str = "controller"
    k_signal: str = "global"
    pending_units: str = "tasks"
    backpressure_units: str = "tasks"
    k_scope: str = "token"
    admit_policy: str = "ordered"
    pending_hist_max_depth: int = 2048
    sla_interactive_ms: float = 0.0
    sla_batch_ms: float = 0.0
    sim_seed: int = 1
    mtp_draft_len: int = 0
    mtp_accept_prob: float = 0.0
    mtp_accept_decay: float = 1.0
    mtp_draft_cost_scale: float = 0.25
    mtp_verify_per_draft_cost_scale: float = 0.0
    mtp_draft_attempt_policy: str = "full"
    batch_max_interactive: int = 1
    batch_max_batch: int = 1
    batch_wait_interactive_ms: float = 0.0
    batch_wait_batch_ms: float = 0.0
    service_base_ms: float = 0.0
    service_per_task_ms: float = -1.0


@dataclass
class Task:
    token_id: int
    cls: LatencyClass
    enqueue_ms: float
    cost_scale: float = 1.0
    mtp_phase: MtpPhase = MtpPhase.NONE
    start_ms: Optional[float] = None
    served_hi: bool = False


@dataclass(frozen=True)
class StagePlan:
    candidates: Tuple[int, ...]
    scores: Optional[Tuple[float, ...]]
    k: int
    cost_scale: float
    mtp_phase: MtpPhase
    is_verify: bool
    layer_index: int


@dataclass
class TokenState:
    cls: LatencyClass
    submit_ms: float
    chosen_k: int
    remaining: int
    done_ms: Optional[float] = None
    output_len: int = 1
    trace_decode_ms: Optional[float] = None
    trace_kv_tokens: Optional[int] = None
    trace_expert_batch_size: Optional[int] = None
    admitted_tasks_total: int = 0
    dropped_tasks_backpressure: int = 0
    skipped_stages_backpressure: int = 0
    skipped_stages_backpressure_verify: int = 0
    skipped_stages_backpressure_draft: int = 0
    mtp_verify_layer0_skipped_backpressure: bool = False
    mtp_accept_len_clamped_backpressure: bool = False
    stage_idx: int = 0
    stage_total: int = 1
    stages: Optional[Tuple[StagePlan, ...]] = None
    admitted_any: bool = False
    metrics_slot: int = -1
    admitted_verify_layer0: int = 0
    desired_verify_layer0: int = 0
    admitted_verify_total: int = 0
    partial_any_layer: bool = False
    mtp_accept_len: int = 1
    mtp_draft_attempt_len: int = 0
    mtp_accounted: bool = False


@dataclass
class ExpertQueue:
    hi: Deque[Task] = dataclasses.field(default_factory=deque)
    lo: Deque[Task] = dataclasses.field(default_factory=deque)
    in_flight: int = 0
    in_flight_tasks: int = 0
    in_flight_tasks_hi: int = 0
    in_flight_tasks_lo: int = 0
    queued_tasks_mtp_draft: int = 0
    queued_tasks_mtp_verify: int = 0
    in_flight_tasks_mtp_draft: int = 0
    in_flight_tasks_mtp_verify: int = 0
    pending_work_hi: float = 0.0
    pending_work_lo: float = 0.0
    in_flight_work_hi: float = 0.0
    in_flight_work_lo: float = 0.0
    hi_burst: int = 0
    hi_wakeup_ms: float = -1.0
    lo_wakeup_ms: float = -1.0

    def pending(self) -> int:
        return(len(self.hi) + len(self.lo) + self.in_flight_tasks)

    def pending_work(self) -> float:
        return(self.pending_work_hi + self.pending_work_lo + self.in_flight_work_hi + self.in_flight_work_lo)

    def pending_work_for_queue(self, cls: LatencyClass) -> float:
        if cls == LatencyClass.INTERACTIVE:
            return(self.pending_work_hi + self.in_flight_work_hi)
        return(self.pending_work_lo + self.in_flight_work_lo)

    def pending_mtp_draft(self) -> int:
        return(self.queued_tasks_mtp_draft + self.in_flight_tasks_mtp_draft)

    def pending_mtp_verify(self) -> int:
        return(self.queued_tasks_mtp_verify + self.in_flight_tasks_mtp_verify)


class EventKind(enum.IntEnum):
    TOKEN_ARRIVAL = 0
    TASK_DONE = 1
    EXPERT_WAKE = 2


@dataclass(order=True)
class Event:
    t_ms: float
    kind: EventKind
    seq: int
    expert_id: int = dataclasses.field(default=-1, compare=False)
    tasks: Optional[Tuple[Task, ...]] = dataclasses.field(default=None, compare=False)


@dataclass
class SimMetrics:
    num_tokens: int = 0
    makespan_ms: float = 0.0
    k_mode: str = "controller"
    pending_units: str = "tasks"
    backpressure_units: str = "tasks"
    tasks_started_per_expert: List[int] = dataclasses.field(default_factory=list)
    starved_tasks_started_per_expert: List[int] = dataclasses.field(default_factory=list)
    max_task_queue_wait_ms_per_expert: List[float] = dataclasses.field(default_factory=list)
    service_batch_size_interactive: List[float] = dataclasses.field(default_factory=list)
    service_batch_size_batch: List[float] = dataclasses.field(default_factory=list)
    trace_decode_ms_interactive: List[float] = dataclasses.field(default_factory=list)
    trace_decode_ms_batch: List[float] = dataclasses.field(default_factory=list)
    trace_decode_error_ms_interactive: List[float] = dataclasses.field(default_factory=list)
    trace_decode_error_ms_batch: List[float] = dataclasses.field(default_factory=list)
    trace_kv_tokens_interactive: List[float] = dataclasses.field(default_factory=list)
    trace_kv_tokens_batch: List[float] = dataclasses.field(default_factory=list)
    trace_expert_batch_size_interactive: List[float] = dataclasses.field(default_factory=list)
    trace_expert_batch_size_batch: List[float] = dataclasses.field(default_factory=list)
    token_lat_ms_interactive: List[float] = dataclasses.field(default_factory=list)
    token_lat_ms_batch: List[float] = dataclasses.field(default_factory=list)
    output_token_lat_ms_interactive: List[float] = dataclasses.field(default_factory=list)
    output_token_lat_ms_batch: List[float] = dataclasses.field(default_factory=list)
    token_sla_violations_interactive: int = 0
    token_sla_violations_batch: int = 0
    admitted_tokens: int = 0
    admitted_tokens_interactive: int = 0
    admitted_tokens_batch: int = 0
    dropped_tokens_backpressure: int = 0
    dropped_tokens_backpressure_interactive: int = 0
    dropped_tokens_backpressure_batch: int = 0
    task_queue_wait_ms_interactive: List[float] = dataclasses.field(default_factory=list)
    task_queue_wait_ms_batch: List[float] = dataclasses.field(default_factory=list)
    task_queue_wait_ms_mtp_draft: List[float] = dataclasses.field(default_factory=list)
    task_queue_wait_ms_mtp_verify: List[float] = dataclasses.field(default_factory=list)
    chosen_k_interactive: List[int] = dataclasses.field(default_factory=list)
    chosen_k_batch: List[int] = dataclasses.field(default_factory=list)
    chosen_k_total_interactive: List[int] = dataclasses.field(default_factory=list)
    chosen_k_total_batch: List[int] = dataclasses.field(default_factory=list)
    pending_signal_interactive: List[float] = dataclasses.field(default_factory=list)
    pending_signal_batch: List[float] = dataclasses.field(default_factory=list)
    k_updates_interactive: int = 0
    k_updates_batch: int = 0
    k_changes_interactive: int = 0
    k_changes_batch: int = 0
    effective_k_interactive: List[int] = dataclasses.field(default_factory=list)
    effective_k_batch: List[int] = dataclasses.field(default_factory=list)
    effective_k_total_interactive: List[int] = dataclasses.field(default_factory=list)
    effective_k_total_batch: List[int] = dataclasses.field(default_factory=list)
    partial_admit_tokens: int = 0
    partial_admit_tokens_interactive: int = 0
    partial_admit_tokens_batch: int = 0
    partial_admit_any_layer_tokens: int = 0
    partial_admit_any_layer_tokens_interactive: int = 0
    partial_admit_any_layer_tokens_batch: int = 0
    skipped_stages_backpressure: int = 0
    skipped_stages_backpressure_interactive: int = 0
    skipped_stages_backpressure_batch: int = 0
    skipped_stages_backpressure_verify: int = 0
    skipped_stages_backpressure_draft: int = 0
    stages_total: int = 0
    stages_total_interactive: int = 0
    stages_total_batch: int = 0
    stages_total_verify: int = 0
    stages_total_draft: int = 0
    admitted_tasks: int = 0
    admitted_tasks_interactive: int = 0
    admitted_tasks_batch: int = 0
    dropped_tasks_backpressure: int = 0
    dropped_tasks_backpressure_interactive: int = 0
    dropped_tasks_backpressure_batch: int = 0
    starved_tasks: int = 0
    starved_tasks_interactive: int = 0
    starved_tasks_batch: int = 0
    tasks_started_mtp_draft: int = 0
    tasks_started_mtp_verify: int = 0
    starved_tasks_mtp_draft: int = 0
    starved_tasks_mtp_verify: int = 0
    promoted_tasks: int = 0
    forced_batch_starts: int = 0
    max_pending_per_expert: List[int] = dataclasses.field(default_factory=list)
    mean_pending_per_expert: List[float] = dataclasses.field(default_factory=list)
    max_pending_work_per_expert: List[float] = dataclasses.field(default_factory=list)
    mean_pending_work_per_expert: List[float] = dataclasses.field(default_factory=list)
    mean_utilization_per_expert: List[float] = dataclasses.field(default_factory=list)
    saturated_time_frac_per_expert: List[float] = dataclasses.field(default_factory=list)
    pending_depth_hist: List[float] = dataclasses.field(default_factory=list)
    pending_depth_hist_overflow: float = 0.0
    hi_queue_depth_hist: List[float] = dataclasses.field(default_factory=list)
    hi_queue_depth_hist_overflow: float = 0.0
    lo_queue_depth_hist: List[float] = dataclasses.field(default_factory=list)
    lo_queue_depth_hist_overflow: float = 0.0
    pending_work_depth_hist: List[float] = dataclasses.field(default_factory=list)
    pending_work_depth_hist_overflow: float = 0.0
    hi_queue_work_depth_hist: List[float] = dataclasses.field(default_factory=list)
    hi_queue_work_depth_hist_overflow: float = 0.0
    lo_queue_work_depth_hist: List[float] = dataclasses.field(default_factory=list)
    lo_queue_work_depth_hist_overflow: float = 0.0
    pending_depth_hist_mtp_draft: List[float] = dataclasses.field(default_factory=list)
    pending_depth_hist_mtp_draft_overflow: float = 0.0
    pending_depth_hist_mtp_verify: List[float] = dataclasses.field(default_factory=list)
    pending_depth_hist_mtp_verify_overflow: float = 0.0
    work_units_total: float = 0.0
    work_units_interactive: float = 0.0
    work_units_batch: float = 0.0
    work_units_mtp_draft: float = 0.0
    work_units_mtp_verify: float = 0.0
    service_batches_started: int = 0
    service_base_ms_total: float = 0.0
    service_task_ms_total: float = 0.0
    service_slot_ms_total: float = 0.0
    service_slot_ms_interactive: float = 0.0
    service_slot_ms_batch: float = 0.0
    service_slot_ms_mtp_draft: float = 0.0
    service_slot_ms_mtp_verify: float = 0.0
    mtp_output_tokens: int = 0
    mtp_verify_steps: int = 0
    mtp_draft_len: int = 0
    mtp_accept_prob: float = 0.0
    mtp_accept_decay: float = 1.0
    mtp_draft_attempt_policy: str = "full"
    mtp_draft_tokens_total: int = 0
    mtp_draft_tokens_accepted: int = 0
    mtp_draft_tokens_rejected: int = 0
    mtp_bonus_tokens: int = 0
    mtp_accept_len_per_step: List[int] = dataclasses.field(default_factory=list)
    mtp_draft_attempt_len_per_step: List[int] = dataclasses.field(default_factory=list)
    mtp_pos_attempted: List[int] = dataclasses.field(default_factory=list)
    mtp_pos_accepted: List[int] = dataclasses.field(default_factory=list)
    mtp_verify_layer0_skipped_backpressure: int = 0
    mtp_accept_len_clamped_backpressure: int = 0
    dflash_steps: int = 0
    dflash_output_tokens: int = 0
    dflash_draft_tokens_total: int = 0
    dflash_draft_tokens_accepted: int = 0
    dflash_draft_tokens_rejected: int = 0
    dflash_bonus_tokens: int = 0
    dflash_accept_len_per_step: List[int] = dataclasses.field(default_factory=list)
    dflash_accepted_per_step: List[int] = dataclasses.field(default_factory=list)
    dflash_rejected_per_step: List[int] = dataclasses.field(default_factory=list)

    def to_jsonable(self) -> Dict[str, object]:
        def percentile(xs_sorted: Sequence[float], p: float) -> float:
            if len(xs_sorted) == 0:
                return(0.0)
            if len(xs_sorted) == 1:
                return(float(xs_sorted[0]))
            if p <= 0.0:
                return(float(xs_sorted[0]))
            if p >= 1.0:
                return(float(xs_sorted[-1]))
            x = (p * float(len(xs_sorted) - 1))
            i0 = int(math.floor(x))
            i1 = int(math.ceil(x))
            if i0 == i1:
                return(float(xs_sorted[i0]))
            frac = (x - float(i0))
            return(float(xs_sorted[i0]) * (1.0 - frac) + (float(xs_sorted[i1]) * frac))

        def summarize(xs: Sequence[float]) -> Dict[str, float]:
            if len(xs) == 0:
                return({"count": 0})
            xs_sorted = sorted(xs)
            p50 = percentile(xs_sorted, 0.50)
            p95 = percentile(xs_sorted, 0.95)
            p99 = percentile(xs_sorted, 0.99)
            return(
                {
                    "count": len(xs),
                    "mean": statistics.fmean(xs),
                    "p50": p50,
                    "p95": p95,
                    "p99": p99,
                    "max": max(xs),
                }
            )

        def summarize_ints(xs: Sequence[int]) -> Dict[str, float]:
            if len(xs) == 0:
                return({"count": 0})
            xs_f = [float(x) for x in xs]
            return(summarize(xs_f))

        def summarize_experts(xs: Sequence[float]) -> Dict[str, float]:
            if len(xs) == 0:
                return({"count": 0})
            xs_sorted = sorted(xs)
            return(
                {
                    "count": len(xs_sorted),
                    "p50": percentile(xs_sorted, 0.50),
                    "p95": percentile(xs_sorted, 0.95),
                    "max": float(xs_sorted[-1]),
                }
            )

        def hist_int_percentile(hist_time_ms: Sequence[float], overflow_time_ms: float, p: float) -> int:
            if p <= 0.0:
                return(0)
            if p >= 1.0:
                if overflow_time_ms > 0.0:
                    return(len(hist_time_ms))
                if len(hist_time_ms) == 0:
                    return(0)
                return(len(hist_time_ms) - 1)
            total = float(sum(hist_time_ms)) + float(overflow_time_ms)
            if total <= 0.0:
                return(0)
            target = (p * total)
            acc = 0.0
            for d, t in enumerate(hist_time_ms):
                acc += float(t)
                if acc >= target:
                    return(int(d))
            if overflow_time_ms > 0.0:
                return(len(hist_time_ms))
            if len(hist_time_ms) == 0:
                return(0)
            return(len(hist_time_ms) - 1)

        output_tokens = float(self.mtp_output_tokens) if self.mtp_draft_len > 0 else float(self.admitted_tokens)
        return(
            {
                "sim": {
                    "num_tokens": self.num_tokens,
                    "makespan_ms": self.makespan_ms,
                    "backpressure_units": self.backpressure_units,
                    "token_throughput_tps": (float(self.num_tokens) * 1000.0 / self.makespan_ms) if self.makespan_ms > 0.0 else 0.0,
                    "task_throughput_tps": (float(self.admitted_tasks) * 1000.0 / self.makespan_ms) if self.makespan_ms > 0.0 else 0.0,
                },
                "work": {
                    "batches_started": self.service_batches_started,
                    "batch_size": {
                        "interactive": summarize(self.service_batch_size_interactive),
                        "batch": summarize(self.service_batch_size_batch),
                    },
                    "work_units_total": self.work_units_total,
                    "work_units_interactive": self.work_units_interactive,
                    "work_units_batch": self.work_units_batch,
                    "work_units_per_output_token": (float(self.work_units_total) / output_tokens) if output_tokens > 0.0 else 0.0,
                    "service_base_ms_total": self.service_base_ms_total,
                    "service_task_ms_total": self.service_task_ms_total,
                    "service_slot_ms_total": self.service_slot_ms_total,
                    "service_slot_ms_interactive": self.service_slot_ms_interactive,
                    "service_slot_ms_batch": self.service_slot_ms_batch,
                    "service_slot_ms_mtp_draft": self.service_slot_ms_mtp_draft,
                    "service_slot_ms_mtp_verify": self.service_slot_ms_mtp_verify,
                    "service_slot_ms_per_output_token": (float(self.service_slot_ms_total) / output_tokens) if output_tokens > 0.0 else 0.0,
                    "mtp_work_units_draft": self.work_units_mtp_draft,
                    "mtp_work_units_verify": self.work_units_mtp_verify,
                    "mtp_work_units_draft_frac": (float(self.work_units_mtp_draft) / float(self.work_units_total)) if self.work_units_total > 0.0 else 0.0,
                },
                "trace": {
                    "k_mode": self.k_mode,
                    "pending_units": self.pending_units,
                    "decode_ms": {
                        "interactive": summarize(self.trace_decode_ms_interactive),
                        "batch": summarize(self.trace_decode_ms_batch),
                    },
                    "decode_error_ms": {
                        "interactive": summarize(self.trace_decode_error_ms_interactive),
                        "batch": summarize(self.trace_decode_error_ms_batch),
                    },
                    "kv_tokens": {
                        "interactive": summarize(self.trace_kv_tokens_interactive),
                        "batch": summarize(self.trace_kv_tokens_batch),
                    },
                    "expert_batch_size": {
                        "interactive": summarize(self.trace_expert_batch_size_interactive),
                        "batch": summarize(self.trace_expert_batch_size_batch),
                    },
                },
                "mtp": {
                    "enabled": self.mtp_draft_len > 0,
                    "output_tokens": self.mtp_output_tokens,
                    "output_token_throughput_tps": (float(self.mtp_output_tokens) * 1000.0 / self.makespan_ms) if self.makespan_ms > 0.0 else 0.0,
                    "verify_steps": self.mtp_verify_steps,
                    "draft_len": self.mtp_draft_len,
                    "accept_prob": self.mtp_accept_prob,
                    "accept_decay": self.mtp_accept_decay,
                    "draft_attempt_policy": self.mtp_draft_attempt_policy,
                    "service_slot_ms": {
                        "draft": float(self.service_slot_ms_mtp_draft),
                        "verify": float(self.service_slot_ms_mtp_verify),
                    },
                    "service_slot_frac": {
                        "draft": (float(self.service_slot_ms_mtp_draft) / float(self.service_slot_ms_total)) if self.service_slot_ms_total > 0.0 else 0.0,
                        "verify": (float(self.service_slot_ms_mtp_verify) / float(self.service_slot_ms_total)) if self.service_slot_ms_total > 0.0 else 0.0,
                    },
                    "draft_tokens_total": self.mtp_draft_tokens_total,
                    "draft_tokens_accepted": self.mtp_draft_tokens_accepted,
                    "draft_tokens_rejected": self.mtp_draft_tokens_rejected,
                    "bonus_tokens": self.mtp_bonus_tokens,
                    "verify_layer0_skipped_backpressure": self.mtp_verify_layer0_skipped_backpressure,
                    "accept_len_clamped_backpressure": self.mtp_accept_len_clamped_backpressure,
                    "tasks_started": {
                        "draft": self.tasks_started_mtp_draft,
                        "verify": self.tasks_started_mtp_verify,
                    },
                    "task_queue_wait_ms": {
                        "draft": summarize(self.task_queue_wait_ms_mtp_draft),
                        "verify": summarize(self.task_queue_wait_ms_mtp_verify),
                    },
                    "starved_tasks": {
                        "draft": self.starved_tasks_mtp_draft,
                        "verify": self.starved_tasks_mtp_verify,
                    },
                    "starved_task_frac": {
                        "draft": (float(self.starved_tasks_mtp_draft) / float(self.tasks_started_mtp_draft)) if self.tasks_started_mtp_draft != 0 else 0.0,
                        "verify": (float(self.starved_tasks_mtp_verify) / float(self.tasks_started_mtp_verify)) if self.tasks_started_mtp_verify != 0 else 0.0,
                    },
                    "pending_depth_time_weighted": {
                        "draft": {
                            "max_depth": (len(self.pending_depth_hist_mtp_draft) - 1) if len(self.pending_depth_hist_mtp_draft) != 0 else 0,
                            "overflow_time_ms": self.pending_depth_hist_mtp_draft_overflow,
                            "p50": hist_int_percentile(self.pending_depth_hist_mtp_draft, self.pending_depth_hist_mtp_draft_overflow, 0.50),
                            "p95": hist_int_percentile(self.pending_depth_hist_mtp_draft, self.pending_depth_hist_mtp_draft_overflow, 0.95),
                            "p99": hist_int_percentile(self.pending_depth_hist_mtp_draft, self.pending_depth_hist_mtp_draft_overflow, 0.99),
                        },
                        "verify": {
                            "max_depth": (len(self.pending_depth_hist_mtp_verify) - 1) if len(self.pending_depth_hist_mtp_verify) != 0 else 0,
                            "overflow_time_ms": self.pending_depth_hist_mtp_verify_overflow,
                            "p50": hist_int_percentile(self.pending_depth_hist_mtp_verify, self.pending_depth_hist_mtp_verify_overflow, 0.50),
                            "p95": hist_int_percentile(self.pending_depth_hist_mtp_verify, self.pending_depth_hist_mtp_verify_overflow, 0.95),
                            "p99": hist_int_percentile(self.pending_depth_hist_mtp_verify, self.pending_depth_hist_mtp_verify_overflow, 0.99),
                        },
                    },
                    "accept_len": summarize_ints(self.mtp_accept_len_per_step),
                    "draft_attempt_len": summarize_ints(self.mtp_draft_attempt_len_per_step),
                    "accept_rate": (float(self.mtp_draft_tokens_accepted) / float(self.mtp_draft_tokens_total)) if self.mtp_draft_tokens_total != 0 else 0.0,
                    "per_pos_accept_rate_conditional": [
                        (float(a) / float(t)) if t != 0 else 0.0
                        for t, a in zip(self.mtp_pos_attempted, self.mtp_pos_accepted)
                    ],
                },
                "dflash": {
                    "present": self.dflash_steps > 0,
                    "steps": self.dflash_steps,
                    "output_tokens": self.dflash_output_tokens,
                    "output_token_throughput_tps": (float(self.dflash_output_tokens) * 1000.0 / self.makespan_ms) if self.makespan_ms > 0.0 else 0.0,
                    "draft_tokens_total": self.dflash_draft_tokens_total,
                    "draft_tokens_accepted": self.dflash_draft_tokens_accepted,
                    "draft_tokens_rejected": self.dflash_draft_tokens_rejected,
                    "bonus_tokens": self.dflash_bonus_tokens,
                    "accept_rate": (float(self.dflash_draft_tokens_accepted) / float(self.dflash_draft_tokens_total)) if self.dflash_draft_tokens_total != 0 else 0.0,
                    "accept_len": summarize_ints([al for al in self.dflash_accept_len_per_step if al > 0]),
                    "accepted": summarize_ints([a for a in self.dflash_accepted_per_step if a >= 0]),
                    "rejected": summarize_ints([r for r in self.dflash_rejected_per_step if r >= 0]),
                },
                "token_latency_ms": {
                    "interactive": summarize(self.token_lat_ms_interactive),
                    "batch": summarize(self.token_lat_ms_batch),
                },
                "output_token_latency_ms": {
                    "interactive": summarize(self.output_token_lat_ms_interactive),
                    "batch": summarize(self.output_token_lat_ms_batch),
                },
                "sla": {
                    "token_violations_interactive": self.token_sla_violations_interactive,
                    "token_violations_batch": self.token_sla_violations_batch,
                    "token_violation_frac_interactive": (float(self.token_sla_violations_interactive) / float(self.admitted_tokens_interactive)) if self.admitted_tokens_interactive != 0 else 0.0,
                    "token_violation_frac_batch": (float(self.token_sla_violations_batch) / float(self.admitted_tokens_batch)) if self.admitted_tokens_batch != 0 else 0.0,
                },
                "tokens": {
                    "admitted": self.admitted_tokens,
                    "admitted_interactive": self.admitted_tokens_interactive,
                    "admitted_batch": self.admitted_tokens_batch,
                    "dropped_backpressure_all": self.dropped_tokens_backpressure,
                    "dropped_backpressure_all_interactive": self.dropped_tokens_backpressure_interactive,
                    "dropped_backpressure_all_batch": self.dropped_tokens_backpressure_batch,
                    "partial_admit": self.partial_admit_tokens,
                    "partial_admit_interactive": self.partial_admit_tokens_interactive,
                    "partial_admit_batch": self.partial_admit_tokens_batch,
                    "partial_admit_any_layer": self.partial_admit_any_layer_tokens,
                    "partial_admit_any_layer_interactive": self.partial_admit_any_layer_tokens_interactive,
                    "partial_admit_any_layer_batch": self.partial_admit_any_layer_tokens_batch,
                },
                "stages": {
                    "total": int(self.stages_total),
                    "total_interactive": int(self.stages_total_interactive),
                    "total_batch": int(self.stages_total_batch),
                    "total_verify": int(self.stages_total_verify),
                    "total_draft": int(self.stages_total_draft),
                    "skipped_backpressure": self.skipped_stages_backpressure,
                    "skipped_backpressure_interactive": self.skipped_stages_backpressure_interactive,
                    "skipped_backpressure_batch": self.skipped_stages_backpressure_batch,
                    "skipped_backpressure_verify": self.skipped_stages_backpressure_verify,
                    "skipped_backpressure_draft": self.skipped_stages_backpressure_draft,
                },
                "task_queue_wait_ms": {
                    "interactive": summarize(self.task_queue_wait_ms_interactive),
                    "batch": summarize(self.task_queue_wait_ms_batch),
                },
                "chosen_k": {
                    "interactive": {
                        "count": len(self.chosen_k_interactive),
                        "mean": statistics.fmean(self.chosen_k_interactive) if len(self.chosen_k_interactive) != 0 else 0.0,
                        "min": min(self.chosen_k_interactive) if len(self.chosen_k_interactive) != 0 else 0,
                        "max": max(self.chosen_k_interactive) if len(self.chosen_k_interactive) != 0 else 0,
                        "controller_updates": self.k_updates_interactive,
                        "controller_changes": self.k_changes_interactive,
                    },
                    "batch": {
                        "count": len(self.chosen_k_batch),
                        "mean": statistics.fmean(self.chosen_k_batch) if len(self.chosen_k_batch) != 0 else 0.0,
                        "min": min(self.chosen_k_batch) if len(self.chosen_k_batch) != 0 else 0,
                        "max": max(self.chosen_k_batch) if len(self.chosen_k_batch) != 0 else 0,
                        "controller_updates": self.k_updates_batch,
                        "controller_changes": self.k_changes_batch,
                    },
                },
                "chosen_k_total": {
                    "interactive": summarize_ints(self.chosen_k_total_interactive),
                    "batch": summarize_ints(self.chosen_k_total_batch),
                },
                "pending_signal": {
                    "interactive": summarize(self.pending_signal_interactive),
                    "batch": summarize(self.pending_signal_batch),
                },
                "effective_k": {
                    "interactive": summarize_ints(self.effective_k_interactive),
                    "batch": summarize_ints(self.effective_k_batch),
                },
                "effective_k_total": {
                    "interactive": summarize_ints(self.effective_k_total_interactive),
                    "batch": summarize_ints(self.effective_k_total_batch),
                },
                "tasks": {
                    "admitted": self.admitted_tasks,
                    "admitted_interactive": self.admitted_tasks_interactive,
                    "admitted_batch": self.admitted_tasks_batch,
                    "dropped_backpressure": self.dropped_tasks_backpressure,
                    "dropped_backpressure_interactive": self.dropped_tasks_backpressure_interactive,
                    "dropped_backpressure_batch": self.dropped_tasks_backpressure_batch,
                    "starved": self.starved_tasks,
                    "starved_interactive": self.starved_tasks_interactive,
                    "starved_batch": self.starved_tasks_batch,
                    "promoted": self.promoted_tasks,
                    "forced_batch_starts": self.forced_batch_starts,
                },
                "expert_queue": {
                    "num_experts": len(self.max_pending_per_expert),
                    "max_pending_p50": statistics.median(self.max_pending_per_expert) if len(self.max_pending_per_expert) != 0 else 0,
                    "max_pending_max": max(self.max_pending_per_expert) if len(self.max_pending_per_expert) != 0 else 0,
                    "mean_pending_p50": statistics.median(self.mean_pending_per_expert) if len(self.mean_pending_per_expert) != 0 else 0.0,
                    "mean_pending_max": max(self.mean_pending_per_expert) if len(self.mean_pending_per_expert) != 0 else 0.0,
                    "tasks_started_total": int(sum(self.tasks_started_per_expert)) if len(self.tasks_started_per_expert) != 0 else 0,
                    "tasks_started_top1_frac": (
                        (float(max(self.tasks_started_per_expert)) / float(sum(self.tasks_started_per_expert)))
                        if len(self.tasks_started_per_expert) != 0 and sum(self.tasks_started_per_expert) != 0
                        else 0.0
                    ),
                    "tasks_started_gini": _gini_nonneg([float(v) for v in self.tasks_started_per_expert]),
                    "utilization_gini": _gini_nonneg([float(v) for v in self.mean_utilization_per_expert]),
                    "starvation_task_frac": summarize_experts(
                        [
                            (float(self.starved_tasks_started_per_expert[i]) / float(self.tasks_started_per_expert[i])) if self.tasks_started_per_expert[i] != 0 else 0.0
                            for i in range(len(self.tasks_started_per_expert))
                        ]
                    ),
                    "max_task_queue_wait_ms": summarize_experts(self.max_task_queue_wait_ms_per_expert),
                    "work": {
                        "max_pending_p50": statistics.median(self.max_pending_work_per_expert) if len(self.max_pending_work_per_expert) != 0 else 0.0,
                        "max_pending_max": max(self.max_pending_work_per_expert) if len(self.max_pending_work_per_expert) != 0 else 0.0,
                        "mean_pending_p50": statistics.median(self.mean_pending_work_per_expert) if len(self.mean_pending_work_per_expert) != 0 else 0.0,
                        "mean_pending_max": max(self.mean_pending_work_per_expert) if len(self.mean_pending_work_per_expert) != 0 else 0.0,
                    },
                    "pending_depth_time_weighted": {
                        "max_depth": (len(self.pending_depth_hist) - 1) if len(self.pending_depth_hist) != 0 else 0,
                        "overflow_time_ms": self.pending_depth_hist_overflow,
                        "p50": hist_int_percentile(self.pending_depth_hist, self.pending_depth_hist_overflow, 0.50),
                        "p95": hist_int_percentile(self.pending_depth_hist, self.pending_depth_hist_overflow, 0.95),
                        "p99": hist_int_percentile(self.pending_depth_hist, self.pending_depth_hist_overflow, 0.99),
                    },
                    "hi_queue_depth_time_weighted": {
                        "max_depth": (len(self.hi_queue_depth_hist) - 1) if len(self.hi_queue_depth_hist) != 0 else 0,
                        "overflow_time_ms": self.hi_queue_depth_hist_overflow,
                        "p50": hist_int_percentile(self.hi_queue_depth_hist, self.hi_queue_depth_hist_overflow, 0.50),
                        "p95": hist_int_percentile(self.hi_queue_depth_hist, self.hi_queue_depth_hist_overflow, 0.95),
                        "p99": hist_int_percentile(self.hi_queue_depth_hist, self.hi_queue_depth_hist_overflow, 0.99),
                    },
                    "lo_queue_depth_time_weighted": {
                        "max_depth": (len(self.lo_queue_depth_hist) - 1) if len(self.lo_queue_depth_hist) != 0 else 0,
                        "overflow_time_ms": self.lo_queue_depth_hist_overflow,
                        "p50": hist_int_percentile(self.lo_queue_depth_hist, self.lo_queue_depth_hist_overflow, 0.50),
                        "p95": hist_int_percentile(self.lo_queue_depth_hist, self.lo_queue_depth_hist_overflow, 0.95),
                        "p99": hist_int_percentile(self.lo_queue_depth_hist, self.lo_queue_depth_hist_overflow, 0.99),
                    },
                    "pending_work_depth_time_weighted": {
                        "max_depth": (len(self.pending_work_depth_hist) - 1) if len(self.pending_work_depth_hist) != 0 else 0,
                        "overflow_time_ms": self.pending_work_depth_hist_overflow,
                        "p50": hist_int_percentile(self.pending_work_depth_hist, self.pending_work_depth_hist_overflow, 0.50),
                        "p95": hist_int_percentile(self.pending_work_depth_hist, self.pending_work_depth_hist_overflow, 0.95),
                        "p99": hist_int_percentile(self.pending_work_depth_hist, self.pending_work_depth_hist_overflow, 0.99),
                    },
                    "hi_queue_work_depth_time_weighted": {
                        "max_depth": (len(self.hi_queue_work_depth_hist) - 1) if len(self.hi_queue_work_depth_hist) != 0 else 0,
                        "overflow_time_ms": self.hi_queue_work_depth_hist_overflow,
                        "p50": hist_int_percentile(self.hi_queue_work_depth_hist, self.hi_queue_work_depth_hist_overflow, 0.50),
                        "p95": hist_int_percentile(self.hi_queue_work_depth_hist, self.hi_queue_work_depth_hist_overflow, 0.95),
                        "p99": hist_int_percentile(self.hi_queue_work_depth_hist, self.hi_queue_work_depth_hist_overflow, 0.99),
                    },
                    "lo_queue_work_depth_time_weighted": {
                        "max_depth": (len(self.lo_queue_work_depth_hist) - 1) if len(self.lo_queue_work_depth_hist) != 0 else 0,
                        "overflow_time_ms": self.lo_queue_work_depth_hist_overflow,
                        "p50": hist_int_percentile(self.lo_queue_work_depth_hist, self.lo_queue_work_depth_hist_overflow, 0.50),
                        "p95": hist_int_percentile(self.lo_queue_work_depth_hist, self.lo_queue_work_depth_hist_overflow, 0.95),
                        "p99": hist_int_percentile(self.lo_queue_work_depth_hist, self.lo_queue_work_depth_hist_overflow, 0.99),
                    },
                },
                "expert_utilization": summarize_experts(self.mean_utilization_per_expert),
                "expert_saturation": summarize_experts(self.saturated_time_frac_per_expert),
            }
        )


def _promote_aged_batch(now_ms: float, cfg: SimConfig, eq: ExpertQueue, metrics: SimMetrics) -> None:
    if cfg.promote_ms <= 0.0:
        return
    while len(eq.lo) != 0:
        t0 = eq.lo[0]
        if t0.cls != LatencyClass.BATCH:
            break
        if (now_ms - t0.enqueue_ms) < cfg.promote_ms:
            break
        eq.lo.popleft()
        eq.pending_work_lo -= float(t0.cost_scale)
        eq.hi.append(t0)
        eq.pending_work_hi += float(t0.cost_scale)
        metrics.promoted_tasks += 1


def _zipf_weights(num_experts: int, alpha: float) -> List[float]:
    weights: List[float] = []
    for i in range(num_experts):
        weights.append(1.0 / math.pow(float(i + 1), alpha))
    return(weights)


def _sample_unique_ordered(rng: random.Random, population_size: int, weights: Sequence[float], k: int) -> Tuple[int, ...]:
    chosen: List[int] = []
    chosen_set = set()
    tries = 0
    while len(chosen) < k and tries < (k * 50):
        idx = rng.choices(range(population_size), weights=weights, k=1)[0]
        if idx not in chosen_set:
            chosen.append(idx)
            chosen_set.add(idx)
        tries += 1
    if len(chosen) != k:
        for idx in range(population_size):
            if idx not in chosen_set:
                chosen.append(idx)
                if len(chosen) == k:
                    break
    return(tuple(chosen[:k]))


def _generate_arrival_times_ms(rng: random.Random, num_tokens: int, arrival_rate_tps: float, burst_prob: float, burst_scale: float) -> List[float]:
    t_ms = 0.0
    times: List[float] = []
    mean_interarrival_ms = (1000.0 / arrival_rate_tps)
    for _i in range(num_tokens):
        if rng.random() < burst_prob:
            interarrival_ms = rng.expovariate(1.0 / (mean_interarrival_ms / burst_scale))
        else:
            interarrival_ms = rng.expovariate(1.0 / mean_interarrival_ms)
        t_ms += interarrival_ms
        times.append(t_ms)
    return(times)


def _hotset_for_token(perm: List[int], hotset_size: int, hotset_rotate_every_tokens: int, token_index: int) -> List[int]:
    if hotset_size <= 0:
        return([])
    if hotset_rotate_every_tokens <= 0:
        return(perm[:hotset_size])
    phase = (token_index // hotset_rotate_every_tokens)
    offset = ((phase * hotset_size) % len(perm))
    rotated = perm[offset:] + perm[:offset]
    return(rotated[:hotset_size])


def _sample_hotset_candidates(rng: random.Random, num_experts: int, hotset: Sequence[int], hotset_bias: float, k: int) -> Tuple[int, ...]:
    if k <= 0:
        return(())
    chosen: List[int] = []
    chosen_set = set()
    tries = 0
    while len(chosen) < k and tries < (k * 200):
        if len(hotset) != 0 and rng.random() < hotset_bias:
            idx = hotset[rng.randrange(0, len(hotset))]
        else:
            idx = rng.randrange(0, num_experts)
        if idx not in chosen_set:
            chosen.append(idx)
            chosen_set.add(idx)
        tries += 1
    if len(chosen) != k:
        for idx in range(num_experts):
            if idx not in chosen_set:
                chosen.append(idx)
                if len(chosen) == k:
                    break
    return(tuple(chosen[:k]))


def _union_candidates_for_layers(layer_candidates: Sequence[Tuple[int, ...]]) -> Tuple[int, ...]:
    union: List[int] = []
    seen = set()
    for lcands in layer_candidates:
        for c in lcands:
            if c not in seen:
                union.append(int(c))
                seen.add(int(c))
    return(tuple(union))


def _synthetic_scores_for_candidates(rng: random.Random, candidates: Tuple[int, ...], mode: str) -> Tuple[Tuple[int, ...], Optional[Tuple[float, ...]]]:
    if mode == "none":
        return(candidates, None)
    if mode not in ("random", "router_desc"):
        raise ValueError("synthetic_score_mode must be one of: none, random, router_desc")
    scores = [rng.random() for _i in range(len(candidates))]
    if mode == "router_desc":
        ranked = [(-float(scores[i]), i, int(candidates[i])) for i in range(len(candidates))]
        ranked.sort()
        c_out = [c for _s, _i, c in ranked]
        s_out = [float(scores[i]) for _s, i, _c in ranked]
        return(tuple(c_out), tuple(s_out))
    return(candidates, tuple(float(s) for s in scores))


def _synthetic_cost_scale(rng: random.Random, mode: str, log_sigma: float) -> Optional[float]:
    if mode == "none":
        return(None)
    if mode != "lognormal":
        raise ValueError("synthetic_cost_scale_mode must be one of: none, lognormal")
    if log_sigma <= 0.0:
        raise ValueError("synthetic_cost_scale_log_sigma must be > 0 for lognormal cost_scale")
    return(float(math.exp(rng.gauss(0.0, float(log_sigma)))))


def generate_synthetic_trace(cfg: TraceConfig) -> List[TokenRoute]:
    if cfg.num_experts <= 0:
        raise ValueError("num_experts must be > 0")
    if cfg.num_candidates <= 0:
        raise ValueError("num_candidates must be > 0")
    if cfg.num_candidates > cfg.num_experts:
        raise ValueError("num_candidates must be <= num_experts")
    if cfg.num_tokens <= 0:
        raise ValueError("num_tokens must be > 0")
    if cfg.arrival_rate_tps <= 0.0:
        raise ValueError("arrival_rate_tps must be > 0")
    if cfg.interactive_prob < 0.0 or cfg.interactive_prob > 1.0:
        raise ValueError("interactive_prob must be within [0,1]")
    if cfg.burst_prob < 0.0 or cfg.burst_prob > 1.0:
        raise ValueError("burst_prob must be within [0,1]")
    if cfg.burst_scale <= 0.0:
        raise ValueError("burst_scale must be > 0")
    if cfg.zipf_alpha <= 0.0:
        raise ValueError("zipf_alpha must be > 0")
    if cfg.num_layers <= 0:
        raise ValueError("num_layers must be > 0")
    if cfg.synthetic_score_mode not in ("none", "random", "router_desc"):
        raise ValueError("synthetic_score_mode must be one of: none, random, router_desc")
    if cfg.synthetic_cost_scale_mode not in ("none", "lognormal"):
        raise ValueError("synthetic_cost_scale_mode must be one of: none, lognormal")
    if cfg.synthetic_cost_scale_mode != "none" and cfg.synthetic_cost_scale_log_sigma <= 0.0:
        raise ValueError("synthetic_cost_scale_log_sigma must be > 0 when synthetic_cost_scale_mode != none")

    rng = random.Random(cfg.seed)
    weights = _zipf_weights(cfg.num_experts, cfg.zipf_alpha)
    routes: List[TokenRoute] = []

    arrivals = _generate_arrival_times_ms(rng, cfg.num_tokens, cfg.arrival_rate_tps, cfg.burst_prob, cfg.burst_scale)
    for t_ms in arrivals:
        cls = LatencyClass.INTERACTIVE if rng.random() < cfg.interactive_prob else LatencyClass.BATCH
        cost_scale = _synthetic_cost_scale(rng, cfg.synthetic_cost_scale_mode, cfg.synthetic_cost_scale_log_sigma)
        if cfg.num_layers <= 1:
            candidates = _sample_unique_ordered(rng, cfg.num_experts, weights, cfg.num_candidates)
            candidates, scores = _synthetic_scores_for_candidates(rng, candidates, cfg.synthetic_score_mode)
            routes.append(TokenRoute(t_ms=t_ms, cls=cls, candidates=candidates, scores=scores, cost_scale=cost_scale))
        else:
            layer_candidates: List[Tuple[int, ...]] = []
            layer_scores: List[Optional[Tuple[float, ...]]] = []
            for _li in range(cfg.num_layers):
                lc = _sample_unique_ordered(rng, cfg.num_experts, weights, cfg.num_candidates)
                lc, ls = _synthetic_scores_for_candidates(rng, lc, cfg.synthetic_score_mode)
                layer_candidates.append(lc)
                layer_scores.append(ls)
            union = _union_candidates_for_layers(layer_candidates)
            layers: List[LayerRoute] = []
            for lc, ls in zip(layer_candidates, layer_scores):
                layers.append(LayerRoute(candidates=lc, scores=ls))
            routes.append(TokenRoute(t_ms=t_ms, cls=cls, candidates=union, layers=tuple(layers), cost_scale=cost_scale))

    routes.sort(key=lambda r: r.t_ms)
    return(routes)


def generate_hotset_trace(cfg: HotsetTraceConfig) -> List[TokenRoute]:
    if cfg.num_experts <= 0:
        raise ValueError("num_experts must be > 0")
    if cfg.num_candidates <= 0:
        raise ValueError("num_candidates must be > 0")
    if cfg.num_candidates > cfg.num_experts:
        raise ValueError("num_candidates must be <= num_experts")
    if cfg.num_tokens <= 0:
        raise ValueError("num_tokens must be > 0")
    if cfg.arrival_rate_tps <= 0.0:
        raise ValueError("arrival_rate_tps must be > 0")
    if cfg.interactive_prob < 0.0 or cfg.interactive_prob > 1.0:
        raise ValueError("interactive_prob must be within [0,1]")
    if cfg.burst_prob < 0.0 or cfg.burst_prob > 1.0:
        raise ValueError("burst_prob must be within [0,1]")
    if cfg.burst_scale <= 0.0:
        raise ValueError("burst_scale must be > 0")
    if cfg.hotset_size <= 0 or cfg.hotset_size > cfg.num_experts:
        raise ValueError("hotset_size must be within [1,num_experts]")
    if cfg.hotset_bias < 0.0 or cfg.hotset_bias > 1.0:
        raise ValueError("hotset_bias must be within [0,1]")
    if cfg.num_layers <= 0:
        raise ValueError("num_layers must be > 0")
    if cfg.synthetic_score_mode not in ("none", "random", "router_desc"):
        raise ValueError("synthetic_score_mode must be one of: none, random, router_desc")
    if cfg.synthetic_cost_scale_mode not in ("none", "lognormal"):
        raise ValueError("synthetic_cost_scale_mode must be one of: none, lognormal")
    if cfg.synthetic_cost_scale_mode != "none" and cfg.synthetic_cost_scale_log_sigma <= 0.0:
        raise ValueError("synthetic_cost_scale_log_sigma must be > 0 when synthetic_cost_scale_mode != none")

    rng = random.Random(cfg.seed)
    perm = list(range(cfg.num_experts))
    rng.shuffle(perm)

    arrivals = _generate_arrival_times_ms(rng, cfg.num_tokens, cfg.arrival_rate_tps, cfg.burst_prob, cfg.burst_scale)
    routes: List[TokenRoute] = []
    for i, t_ms in enumerate(arrivals):
        hotset = _hotset_for_token(perm, cfg.hotset_size, cfg.hotset_rotate_every_tokens, i)
        cls = LatencyClass.INTERACTIVE if rng.random() < cfg.interactive_prob else LatencyClass.BATCH
        cost_scale = _synthetic_cost_scale(rng, cfg.synthetic_cost_scale_mode, cfg.synthetic_cost_scale_log_sigma)
        if cfg.num_layers <= 1:
            candidates = _sample_hotset_candidates(rng, cfg.num_experts, hotset, cfg.hotset_bias, cfg.num_candidates)
            candidates, scores = _synthetic_scores_for_candidates(rng, candidates, cfg.synthetic_score_mode)
            routes.append(TokenRoute(t_ms=t_ms, cls=cls, candidates=candidates, scores=scores, cost_scale=cost_scale))
        else:
            layer_candidates: List[Tuple[int, ...]] = []
            layer_scores: List[Optional[Tuple[float, ...]]] = []
            for _li in range(cfg.num_layers):
                lc = _sample_hotset_candidates(rng, cfg.num_experts, hotset, cfg.hotset_bias, cfg.num_candidates)
                lc, ls = _synthetic_scores_for_candidates(rng, lc, cfg.synthetic_score_mode)
                layer_candidates.append(lc)
                layer_scores.append(ls)
            union = _union_candidates_for_layers(layer_candidates)
            layers: List[LayerRoute] = []
            for lc, ls in zip(layer_candidates, layer_scores):
                layers.append(LayerRoute(candidates=lc, scores=ls))
            routes.append(TokenRoute(t_ms=t_ms, cls=cls, candidates=union, layers=tuple(layers), cost_scale=cost_scale))

    routes.sort(key=lambda r: r.t_ms)
    return(routes)


def _sample_unique_ordered_excluding(rng: random.Random, population_size: int, weights: Sequence[float], k: int, excluded: Sequence[int]) -> Tuple[int, ...]:
    if k <= 0:
        return(())
    excluded_set = set(excluded)
    chosen: List[int] = []
    chosen_set = set(excluded_set)
    tries = 0
    while len(chosen) < k and tries < (k * 100):
        idx = rng.choices(range(population_size), weights=weights, k=1)[0]
        if idx not in chosen_set:
            chosen.append(idx)
            chosen_set.add(idx)
        tries += 1
    if len(chosen) != k:
        for idx in range(population_size):
            if idx not in chosen_set:
                chosen.append(idx)
                chosen_set.add(idx)
                if len(chosen) == k:
                    break
    return(tuple(chosen[:k]))


def generate_markov_trace(cfg: MarkovTraceConfig) -> List[TokenRoute]:
    if cfg.num_experts <= 0:
        raise ValueError("num_experts must be > 0")
    if cfg.num_candidates <= 0:
        raise ValueError("num_candidates must be > 0")
    if cfg.num_candidates > cfg.num_experts:
        raise ValueError("num_candidates must be <= num_experts")
    if cfg.num_tokens <= 0:
        raise ValueError("num_tokens must be > 0")
    if cfg.arrival_rate_tps <= 0.0:
        raise ValueError("arrival_rate_tps must be > 0")
    if cfg.interactive_prob < 0.0 or cfg.interactive_prob > 1.0:
        raise ValueError("interactive_prob must be within [0,1]")
    if cfg.burst_prob < 0.0 or cfg.burst_prob > 1.0:
        raise ValueError("burst_prob must be within [0,1]")
    if cfg.burst_scale <= 0.0:
        raise ValueError("burst_scale must be > 0")
    if cfg.zipf_alpha <= 0.0:
        raise ValueError("zipf_alpha must be > 0")
    if cfg.stay_prob < 0.0 or cfg.stay_prob > 1.0:
        raise ValueError("stay_prob must be within [0,1]")
    if cfg.num_layers <= 0:
        raise ValueError("num_layers must be > 0")
    if cfg.synthetic_score_mode not in ("none", "random", "router_desc"):
        raise ValueError("synthetic_score_mode must be one of: none, random, router_desc")
    if cfg.synthetic_cost_scale_mode not in ("none", "lognormal"):
        raise ValueError("synthetic_cost_scale_mode must be one of: none, lognormal")
    if cfg.synthetic_cost_scale_mode != "none" and cfg.synthetic_cost_scale_log_sigma <= 0.0:
        raise ValueError("synthetic_cost_scale_log_sigma must be > 0 when synthetic_cost_scale_mode != none")

    rng = random.Random(cfg.seed)
    weights = _zipf_weights(cfg.num_experts, cfg.zipf_alpha)
    arrivals = _generate_arrival_times_ms(rng, cfg.num_tokens, cfg.arrival_rate_tps, cfg.burst_prob, cfg.burst_scale)
    routes: List[TokenRoute] = []

    primary = rng.randrange(0, cfg.num_experts)
    for t_ms in arrivals:
        if rng.random() > cfg.stay_prob:
            primary = rng.choices(range(cfg.num_experts), weights=weights, k=1)[0]
        cls = LatencyClass.INTERACTIVE if rng.random() < cfg.interactive_prob else LatencyClass.BATCH
        cost_scale = _synthetic_cost_scale(rng, cfg.synthetic_cost_scale_mode, cfg.synthetic_cost_scale_log_sigma)
        if cfg.num_layers <= 1:
            others = _sample_unique_ordered_excluding(rng, cfg.num_experts, weights, cfg.num_candidates - 1, excluded=(primary,))
            candidates = (primary,) + others
            candidates, scores = _synthetic_scores_for_candidates(rng, candidates, cfg.synthetic_score_mode)
            routes.append(TokenRoute(t_ms=t_ms, cls=cls, candidates=candidates, scores=scores, cost_scale=cost_scale))
        else:
            layer_candidates: List[Tuple[int, ...]] = []
            layer_scores: List[Optional[Tuple[float, ...]]] = []
            for _li in range(cfg.num_layers):
                others = _sample_unique_ordered_excluding(rng, cfg.num_experts, weights, cfg.num_candidates - 1, excluded=(primary,))
                lc = (primary,) + others
                lc, ls = _synthetic_scores_for_candidates(rng, lc, cfg.synthetic_score_mode)
                layer_candidates.append(lc)
                layer_scores.append(ls)
            union = _union_candidates_for_layers(layer_candidates)
            layers: List[LayerRoute] = []
            for lc, ls in zip(layer_candidates, layer_scores):
                layers.append(LayerRoute(candidates=lc, scores=ls))
            routes.append(TokenRoute(t_ms=t_ms, cls=cls, candidates=union, layers=tuple(layers), cost_scale=cost_scale))

    routes.sort(key=lambda r: r.t_ms)
    return(routes)


def generate_twostream_trace(cfg: TwoStreamTraceConfig) -> List[TokenRoute]:
    if cfg.num_experts <= 0:
        raise ValueError("num_experts must be > 0")
    if cfg.num_candidates <= 0:
        raise ValueError("num_candidates must be > 0")
    if cfg.num_candidates > cfg.num_experts:
        raise ValueError("num_candidates must be <= num_experts")
    if cfg.num_tokens <= 0:
        raise ValueError("num_tokens must be > 0")
    if cfg.interactive_arrival_rate_tps < 0.0:
        raise ValueError("interactive_arrival_rate_tps must be >= 0")
    if cfg.batch_arrival_rate_tps < 0.0:
        raise ValueError("batch_arrival_rate_tps must be >= 0")
    if cfg.interactive_burst_prob < 0.0 or cfg.interactive_burst_prob > 1.0:
        raise ValueError("interactive_burst_prob must be within [0,1]")
    if cfg.batch_burst_prob < 0.0 or cfg.batch_burst_prob > 1.0:
        raise ValueError("batch_burst_prob must be within [0,1]")
    if cfg.interactive_burst_scale <= 0.0:
        raise ValueError("interactive_burst_scale must be > 0")
    if cfg.batch_burst_scale <= 0.0:
        raise ValueError("batch_burst_scale must be > 0")
    if cfg.zipf_alpha <= 0.0:
        raise ValueError("zipf_alpha must be > 0")
    if cfg.num_layers <= 0:
        raise ValueError("num_layers must be > 0")
    if cfg.synthetic_score_mode not in ("none", "random", "router_desc"):
        raise ValueError("synthetic_score_mode must be one of: none, random, router_desc")
    if cfg.synthetic_cost_scale_mode not in ("none", "lognormal"):
        raise ValueError("synthetic_cost_scale_mode must be one of: none, lognormal")
    if cfg.synthetic_cost_scale_mode != "none" and cfg.synthetic_cost_scale_log_sigma <= 0.0:
        raise ValueError("synthetic_cost_scale_log_sigma must be > 0 when synthetic_cost_scale_mode != none")

    total_rate = float(cfg.interactive_arrival_rate_tps) + float(cfg.batch_arrival_rate_tps)
    if total_rate <= 0.0:
        raise ValueError("interactive_arrival_rate_tps + batch_arrival_rate_tps must be > 0")

    num_hi = int(round(float(cfg.num_tokens) * float(cfg.interactive_arrival_rate_tps) / total_rate))
    num_hi = max(0, min(cfg.num_tokens, num_hi))
    num_lo = int(cfg.num_tokens - num_hi)

    rng = random.Random(cfg.seed)
    rng_hi = random.Random((cfg.seed ^ 0xC0DEC0DE) & 0xFFFFFFFF)
    rng_lo = random.Random((cfg.seed ^ 0xBADC0FFE) & 0xFFFFFFFF)

    weights = _zipf_weights(cfg.num_experts, cfg.zipf_alpha)
    routes: List[TokenRoute] = []

    arrivals_hi: List[float] = []
    arrivals_lo: List[float] = []
    if num_hi > 0:
        if cfg.interactive_arrival_rate_tps <= 0.0:
            raise ValueError("interactive_arrival_rate_tps must be > 0 when interactive tokens are generated")
        arrivals_hi = _generate_arrival_times_ms(rng_hi, num_hi, cfg.interactive_arrival_rate_tps, cfg.interactive_burst_prob, cfg.interactive_burst_scale)
    if num_lo > 0:
        if cfg.batch_arrival_rate_tps <= 0.0:
            raise ValueError("batch_arrival_rate_tps must be > 0 when batch tokens are generated")
        arrivals_lo = _generate_arrival_times_ms(rng_lo, num_lo, cfg.batch_arrival_rate_tps, cfg.batch_burst_prob, cfg.batch_burst_scale)

    def emit_token(t_ms: float, cls: LatencyClass) -> None:
        cost_scale = _synthetic_cost_scale(rng, cfg.synthetic_cost_scale_mode, cfg.synthetic_cost_scale_log_sigma)
        if cfg.num_layers <= 1:
            candidates = _sample_unique_ordered(rng, cfg.num_experts, weights, cfg.num_candidates)
            candidates, scores = _synthetic_scores_for_candidates(rng, candidates, cfg.synthetic_score_mode)
            routes.append(TokenRoute(t_ms=t_ms, cls=cls, candidates=candidates, scores=scores, cost_scale=cost_scale))
            return
        layer_candidates: List[Tuple[int, ...]] = []
        layer_scores: List[Optional[Tuple[float, ...]]] = []
        for _li in range(cfg.num_layers):
            lc = _sample_unique_ordered(rng, cfg.num_experts, weights, cfg.num_candidates)
            lc, ls = _synthetic_scores_for_candidates(rng, lc, cfg.synthetic_score_mode)
            layer_candidates.append(lc)
            layer_scores.append(ls)
        union = _union_candidates_for_layers(layer_candidates)
        layers: List[LayerRoute] = []
        for lc, ls in zip(layer_candidates, layer_scores):
            layers.append(LayerRoute(candidates=lc, scores=ls))
        routes.append(TokenRoute(t_ms=t_ms, cls=cls, candidates=union, layers=tuple(layers), cost_scale=cost_scale))

    for t_ms in arrivals_hi:
        emit_token(t_ms, LatencyClass.INTERACTIVE)
    for t_ms in arrivals_lo:
        emit_token(t_ms, LatencyClass.BATCH)

    routes.sort(key=lambda r: r.t_ms)
    return(routes)


def load_trace_jsonl(
    path: str,
    time_mode: str = "t_ms",
    meta_out: Optional[Dict[str, object]] = None,
    non_route_policy: str = "error",
    input_format: str = "strict",
    route_type: str = "",
    default_cls: str = "",
) -> List[TokenRoute]:
    if time_mode not in ("t_ms", "dt_ms"):
        raise ValueError("time_mode must be 't_ms' or 'dt_ms'")
    if non_route_policy not in ("error", "skip"):
        raise ValueError("non_route_policy must be 'error' or 'skip'")
    if input_format not in ("strict", "runtime"):
        raise ValueError("input_format must be 'strict' or 'runtime'")
    routes: List[TokenRoute] = []
    t_ms_accum = 0.0
    display_path = path if path != "-" else "<stdin>"

    def merge_meta(payload: object, lineno: int) -> None:
        if meta_out is None:
            return
        if not isinstance(payload, dict):
            raise ValueError(f"{display_path}:{lineno}: meta payload must be a JSON object")
        for k, v in payload.items():
            if not isinstance(k, str):
                raise ValueError(f"{display_path}:{lineno}: meta keys must be strings")
            meta_out[k] = v

    f = sys.stdin if path == "-" else open(path, "r", encoding="utf-8")
    try:
        for lineno, line in enumerate(f, 1):
            line = line.strip()
            if line == "":
                continue
            if line.startswith("#"):
                continue
            try:
                obj_raw = json.loads(line)
            except json.JSONDecodeError:
                if non_route_policy == "skip":
                    continue
                raise ValueError(f"{display_path}:{lineno}: invalid JSON")
            if not isinstance(obj_raw, dict):
                if non_route_policy == "skip":
                    continue
                raise ValueError(f"{display_path}:{lineno}: expected JSON object")
            obj: Dict[str, object] = obj_raw

            if "type" in obj and obj["type"] in ("meta", "trace_meta"):
                payload = obj.get("meta", {k: v for k, v in obj.items() if k != "type"})
                merge_meta(payload, lineno)
                continue
            if "meta" in obj and "cls" not in obj and "candidates" not in obj and "layers" not in obj and "t_ms" not in obj and "dt_ms" not in obj:
                merge_meta(obj["meta"], lineno)
                continue

            if input_format == "runtime":
                from sim.scheduler import trace_extract

                rec = trace_extract.extract_route_record(obj, route_type=route_type, default_cls=default_cls)
                if rec is None:
                    if non_route_policy == "skip":
                        continue
                    raise ValueError(f"{display_path}:{lineno}: could not extract route record (try --trace-non-route skip)")
                obj = rec
            else:
                if non_route_policy == "skip":
                    if "type" in obj and obj.get("type") not in ("meta", "trace_meta"):
                        if "cls" not in obj or ("candidates" not in obj and "layers" not in obj):
                            continue

            if time_mode == "t_ms":
                if "dt_ms" in obj and obj["dt_ms"] is not None:
                    raise ValueError(f"{display_path}:{lineno}: dt_ms is only valid with time_mode=dt_ms")
                if "t_ms" not in obj:
                    raise ValueError(f"{display_path}:{lineno}: missing t_ms")
            else:
                if "t_ms" in obj and obj["t_ms"] is not None:
                    raise ValueError(f"{display_path}:{lineno}: t_ms is not valid with time_mode=dt_ms")
                if "dt_ms" not in obj:
                    raise ValueError(f"{display_path}:{lineno}: missing dt_ms")
            if "cls" not in obj and default_cls.strip() != "":
                obj["cls"] = default_cls.strip().lower()
            if "cls" not in obj:
                if non_route_policy == "skip" and "type" in obj and obj.get("type") not in ("meta", "trace_meta"):
                    continue
                raise ValueError(f"{display_path}:{lineno}: missing cls")
            if "candidates" not in obj and "layers" not in obj:
                if non_route_policy == "skip" and "type" in obj and obj.get("type") not in ("meta", "trace_meta"):
                    continue
                raise ValueError(f"{display_path}:{lineno}: missing candidates (or layers)")

            token_index: Optional[int] = None
            if "token_index" in obj and obj["token_index"] is not None:
                ti_raw = obj["token_index"]
                if not isinstance(ti_raw, int):
                    raise ValueError(f"{display_path}:{lineno}: token_index must be an integer")
                if ti_raw < 0:
                    raise ValueError(f"{display_path}:{lineno}: token_index must be >= 0")
                token_index = int(ti_raw)

            if time_mode == "t_ms":
                t_ms = float(obj["t_ms"])
                if t_ms < 0.0:
                    raise ValueError(f"{display_path}:{lineno}: t_ms must be >= 0")
            else:
                dt_ms = float(obj["dt_ms"])
                if dt_ms < 0.0:
                    raise ValueError(f"{display_path}:{lineno}: dt_ms must be >= 0")
                t_ms_accum += dt_ms
                t_ms = t_ms_accum

            cls_raw = obj["cls"]
            if not isinstance(cls_raw, str):
                raise ValueError(f"{display_path}:{lineno}: cls must be a string")
            cls_norm = cls_raw.strip().lower()
            if cls_norm == "interactive":
                cls = LatencyClass.INTERACTIVE
            elif cls_norm == "batch":
                cls = LatencyClass.BATCH
            else:
                raise ValueError(f"{display_path}:{lineno}: cls must be 'interactive' or 'batch'")

            layers: Optional[Tuple[LayerRoute, ...]] = None
            candidates: List[int] = []
            if "layers" in obj and obj["layers"] is not None:
                layers_raw = obj["layers"]
                if not isinstance(layers_raw, list):
                    raise ValueError(f"{display_path}:{lineno}: layers must be a JSON list")
                layer_routes: List[LayerRoute] = []
                union: List[int] = []
                seen_union: set[int] = set()
                for li, lobj in enumerate(layers_raw):
                    if not isinstance(lobj, dict):
                        raise ValueError(f"{display_path}:{lineno}: layers[{li}] must be a JSON object")
                    if "candidates" not in lobj:
                        raise ValueError(f"{display_path}:{lineno}: layers[{li}] missing candidates")
                    lcand_raw = lobj["candidates"]
                    if not isinstance(lcand_raw, list):
                        raise ValueError(f"{display_path}:{lineno}: layers[{li}].candidates must be a JSON list")
                    lcands: List[int] = []
                    for c in lcand_raw:
                        if not isinstance(c, int):
                            raise ValueError(f"{display_path}:{lineno}: layers[{li}].candidates must be integers")
                        if c < 0:
                            raise ValueError(f"{display_path}:{lineno}: layers[{li}].candidates must be >= 0")
                        lcands.append(int(c))
                    if len(lcands) == 0:
                        raise ValueError(f"{display_path}:{lineno}: layers[{li}].candidates must be non-empty")
                    if len(set(lcands)) != len(lcands):
                        raise ValueError(f"{display_path}:{lineno}: layers[{li}].candidates must be unique")

                    layer_k: Optional[int] = None
                    if "k" in lobj and lobj["k"] is not None:
                        lk_raw = lobj["k"]
                        if not isinstance(lk_raw, int):
                            raise ValueError(f"{display_path}:{lineno}: layers[{li}].k must be an integer")
                        if lk_raw <= 0:
                            raise ValueError(f"{display_path}:{lineno}: layers[{li}].k must be > 0")
                        layer_k = int(lk_raw)

                    layer_scores: Optional[Tuple[float, ...]] = None
                    if "scores" in lobj and lobj["scores"] is not None:
                        ls_raw = lobj["scores"]
                        if not isinstance(ls_raw, list):
                            raise ValueError(f"{display_path}:{lineno}: layers[{li}].scores must be a JSON list")
                        if len(ls_raw) != len(lcands):
                            raise ValueError(f"{display_path}:{lineno}: layers[{li}].scores must have same length as candidates")
                        out_scores: List[float] = []
                        for s in ls_raw:
                            if not isinstance(s, (int, float)):
                                raise ValueError(f"{display_path}:{lineno}: layers[{li}].scores must be numbers")
                            out_scores.append(float(s))
                        layer_scores = tuple(out_scores)

                    layer_cost_scale: Optional[float] = None
                    if "cost_scale" in lobj and lobj["cost_scale"] is not None:
                        lcs_raw = lobj["cost_scale"]
                        if not isinstance(lcs_raw, (int, float)):
                            raise ValueError(f"{display_path}:{lineno}: layers[{li}].cost_scale must be a number")
                        if float(lcs_raw) <= 0.0:
                            raise ValueError(f"{display_path}:{lineno}: layers[{li}].cost_scale must be > 0")
                        layer_cost_scale = float(lcs_raw)

                    layer_routes.append(LayerRoute(candidates=tuple(lcands), k=layer_k, scores=layer_scores, cost_scale=layer_cost_scale))
                    for c in lcands:
                        if c not in seen_union:
                            union.append(c)
                            seen_union.add(c)

                if len(layer_routes) == 0:
                    raise ValueError(f"{display_path}:{lineno}: layers must be non-empty")

                if "scores" in obj and obj["scores"] is not None:
                    raise ValueError(f"{display_path}:{lineno}: scores is not valid when layers are present (use layers[].scores)")

                if "candidates" in obj and obj["candidates"] is not None:
                    cand_raw = obj["candidates"]
                    if not isinstance(cand_raw, list):
                        raise ValueError(f"{display_path}:{lineno}: candidates must be a JSON list")
                    top_candidates: List[int] = []
                    for c in cand_raw:
                        if not isinstance(c, int):
                            raise ValueError(f"{display_path}:{lineno}: candidates must be integers")
                        if c < 0:
                            raise ValueError(f"{display_path}:{lineno}: candidates must be >= 0")
                        top_candidates.append(int(c))
                    if len(top_candidates) == 0:
                        raise ValueError(f"{display_path}:{lineno}: candidates must be non-empty")
                    if len(set(top_candidates)) != len(top_candidates):
                        raise ValueError(f"{display_path}:{lineno}: candidates must be unique")
                    if top_candidates != union:
                        raise ValueError(f"{display_path}:{lineno}: candidates must equal the union of layers[].candidates when layers are present")
                    candidates = top_candidates
                else:
                    candidates = union
                layers = tuple(layer_routes)
            else:
                cand_raw = obj["candidates"]
                if not isinstance(cand_raw, list):
                    raise ValueError(f"{display_path}:{lineno}: candidates must be a JSON list")
                for c in cand_raw:
                    if not isinstance(c, int):
                        raise ValueError(f"{display_path}:{lineno}: candidates must be integers")
                    if c < 0:
                        raise ValueError(f"{display_path}:{lineno}: candidates must be >= 0")
                    candidates.append(int(c))
                if len(candidates) == 0:
                    raise ValueError(f"{display_path}:{lineno}: candidates must be non-empty")
                if len(set(candidates)) != len(candidates):
                    raise ValueError(f"{display_path}:{lineno}: candidates must be unique")

            k: Optional[int] = None
            if "k" in obj and obj["k"] is not None:
                k_raw = obj["k"]
                if not isinstance(k_raw, int):
                    raise ValueError(f"{display_path}:{lineno}: k must be an integer")
                if k_raw <= 0:
                    raise ValueError(f"{display_path}:{lineno}: k must be > 0")
                k = int(k_raw)

            scores: Optional[Tuple[float, ...]] = None
            if layers is None and "scores" in obj and obj["scores"] is not None:
                scores_raw = obj["scores"]
                if not isinstance(scores_raw, list):
                    raise ValueError(f"{display_path}:{lineno}: scores must be a JSON list")
                if len(scores_raw) != len(candidates):
                    raise ValueError(f"{display_path}:{lineno}: scores must have same length as candidates")
                scores_list: List[float] = []
                for s in scores_raw:
                    if not isinstance(s, (int, float)):
                        raise ValueError(f"{display_path}:{lineno}: scores must be numbers")
                    scores_list.append(float(s))
                scores = tuple(scores_list)

            mtp_accept_len: Optional[int] = None
            if "mtp_accept_len" in obj and obj["mtp_accept_len"] is not None:
                al_raw = obj["mtp_accept_len"]
                if not isinstance(al_raw, int):
                    raise ValueError(f"{display_path}:{lineno}: mtp_accept_len must be an integer")
                if al_raw < 1:
                    raise ValueError(f"{display_path}:{lineno}: mtp_accept_len must be >= 1")
                mtp_accept_len = int(al_raw)

            accepted_mtp: Optional[int] = None
            if "accepted_mtp" in obj and obj["accepted_mtp"] is not None:
                am_raw = obj["accepted_mtp"]
                if not isinstance(am_raw, int):
                    raise ValueError(f"{display_path}:{lineno}: accepted_mtp must be an integer")
                if am_raw < 0:
                    raise ValueError(f"{display_path}:{lineno}: accepted_mtp must be >= 0")
                accepted_mtp = int(am_raw)

            rejected_mtp: Optional[int] = None
            if "rejected_mtp" in obj and obj["rejected_mtp"] is not None:
                rm_raw = obj["rejected_mtp"]
                if not isinstance(rm_raw, int):
                    raise ValueError(f"{display_path}:{lineno}: rejected_mtp must be an integer")
                if rm_raw < 0:
                    raise ValueError(f"{display_path}:{lineno}: rejected_mtp must be >= 0")
                rejected_mtp = int(rm_raw)

            dflash_accept_len: Optional[int] = None
            if "dflash_accept_len" in obj and obj["dflash_accept_len"] is not None:
                dal_raw = obj["dflash_accept_len"]
                if not isinstance(dal_raw, int):
                    raise ValueError(f"{display_path}:{lineno}: dflash_accept_len must be an integer")
                if dal_raw < 1:
                    raise ValueError(f"{display_path}:{lineno}: dflash_accept_len must be >= 1")
                dflash_accept_len = int(dal_raw)

            accepted_dflash: Optional[int] = None
            if "accepted_dflash" in obj and obj["accepted_dflash"] is not None:
                ad_raw = obj["accepted_dflash"]
                if not isinstance(ad_raw, int):
                    raise ValueError(f"{display_path}:{lineno}: accepted_dflash must be an integer")
                if ad_raw < 0:
                    raise ValueError(f"{display_path}:{lineno}: accepted_dflash must be >= 0")
                accepted_dflash = int(ad_raw)

            rejected_dflash: Optional[int] = None
            if "rejected_dflash" in obj and obj["rejected_dflash"] is not None:
                rd_raw = obj["rejected_dflash"]
                if not isinstance(rd_raw, int):
                    raise ValueError(f"{display_path}:{lineno}: rejected_dflash must be an integer")
                if rd_raw < 0:
                    raise ValueError(f"{display_path}:{lineno}: rejected_dflash must be >= 0")
                rejected_dflash = int(rd_raw)

            cost_scale: Optional[float] = None
            if "cost_scale" in obj and obj["cost_scale"] is not None:
                cs_raw = obj["cost_scale"]
                if not isinstance(cs_raw, (int, float)):
                    raise ValueError(f"{display_path}:{lineno}: cost_scale must be a number")
                if float(cs_raw) <= 0.0:
                    raise ValueError(f"{display_path}:{lineno}: cost_scale must be > 0")
                cost_scale = float(cs_raw)

            decode_ms: Optional[float] = None
            if "decode_ms" in obj and obj["decode_ms"] is not None:
                dm_raw = obj["decode_ms"]
                if not isinstance(dm_raw, (int, float)):
                    raise ValueError(f"{display_path}:{lineno}: decode_ms must be a number")
                if float(dm_raw) < 0.0:
                    raise ValueError(f"{display_path}:{lineno}: decode_ms must be >= 0")
                decode_ms = float(dm_raw)

            kv_tokens: Optional[int] = None
            if "kv_tokens" in obj and obj["kv_tokens"] is not None:
                kv_raw = obj["kv_tokens"]
                if not isinstance(kv_raw, int):
                    raise ValueError(f"{display_path}:{lineno}: kv_tokens must be an integer")
                if kv_raw < 0:
                    raise ValueError(f"{display_path}:{lineno}: kv_tokens must be >= 0")
                kv_tokens = int(kv_raw)

            expert_batch_size: Optional[int] = None
            if "expert_batch_size" in obj and obj["expert_batch_size"] is not None:
                bs_raw = obj["expert_batch_size"]
                if not isinstance(bs_raw, int):
                    raise ValueError(f"{display_path}:{lineno}: expert_batch_size must be an integer")
                if bs_raw < 0:
                    raise ValueError(f"{display_path}:{lineno}: expert_batch_size must be >= 0")
                expert_batch_size = int(bs_raw)

            routes.append(
                TokenRoute(
                    t_ms=t_ms,
                    token_index=token_index,
                    cls=cls,
                    candidates=tuple(candidates),
                    k=k,
                    scores=scores,
                    mtp_accept_len=mtp_accept_len,
                    accepted_mtp=accepted_mtp,
                    rejected_mtp=rejected_mtp,
                    dflash_accept_len=dflash_accept_len,
                    accepted_dflash=accepted_dflash,
                    rejected_dflash=rejected_dflash,
                    cost_scale=cost_scale,
                    decode_ms=decode_ms,
                    kv_tokens=kv_tokens,
                    expert_batch_size=expert_batch_size,
                    layers=layers,
                )
            )
    finally:
        if path != "-":
            f.close()

    routes.sort(key=lambda r: r.t_ms)
    return(routes)


def load_trace_csv(path: str, time_mode: str = "t_ms") -> List[TokenRoute]:
    if time_mode not in ("t_ms", "dt_ms"):
        raise ValueError("time_mode must be 't_ms' or 'dt_ms'")

    def parse_optional_int(cell: str, key: str, lineno: int) -> Optional[int]:
        s = cell.strip()
        if s == "":
            return(None)
        try:
            v = int(s)
        except ValueError:
            raise ValueError(f"{path}:{lineno}: {key} must be an integer")
        return(v)

    def parse_optional_float(cell: str, key: str, lineno: int) -> Optional[float]:
        s = cell.strip()
        if s == "":
            return(None)
        try:
            v = float(s)
        except ValueError:
            raise ValueError(f"{path}:{lineno}: {key} must be a number")
        return(v)

    def parse_int_list(cell: str, key: str, lineno: int) -> List[int]:
        s = cell.strip()
        if s == "":
            raise ValueError(f"{path}:{lineno}: {key} must be non-empty")
        if s.startswith("["):
            obj = json.loads(s)
            if not isinstance(obj, list):
                raise ValueError(f"{path}:{lineno}: {key} must be a JSON list")
            out: List[int] = []
            for c in obj:
                if not isinstance(c, int):
                    raise ValueError(f"{path}:{lineno}: {key} must be integers")
                out.append(int(c))
            return(out)
        # Allow a simple delimiter format: "1 2 3" or "1,2,3" or "1;2;3".
        cleaned = s.replace(",", " ").replace(";", " ")
        parts = [p for p in cleaned.split() if p != ""]
        out = []
        for p in parts:
            try:
                out.append(int(p))
            except ValueError:
                raise ValueError(f"{path}:{lineno}: {key} list element '{p}' must be an integer")
        return(out)

    def parse_optional_float_list(cell: str, key: str, lineno: int) -> Optional[Tuple[float, ...]]:
        s = cell.strip()
        if s == "":
            return(None)
        if s.startswith("["):
            obj = json.loads(s)
            if not isinstance(obj, list):
                raise ValueError(f"{path}:{lineno}: {key} must be a JSON list")
            out: List[float] = []
            for v in obj:
                if not isinstance(v, (int, float)):
                    raise ValueError(f"{path}:{lineno}: {key} must be numbers")
                out.append(float(v))
            return(tuple(out))
        cleaned = s.replace(",", " ").replace(";", " ")
        parts = [p for p in cleaned.split() if p != ""]
        out = []
        for p in parts:
            try:
                out.append(float(p))
            except ValueError:
                raise ValueError(f"{path}:{lineno}: {key} list element '{p}' must be a number")
        return(tuple(out))

    routes: List[TokenRoute] = []
    t_ms_accum = 0.0
    with open(path, "r", encoding="utf-8", newline="") as f:
        reader = csv.DictReader(f)
        if reader.fieldnames is None:
            raise ValueError(f"{path}: missing CSV header")

        for lineno0, row in enumerate(reader, 2):
            if row is None:
                continue
            # Treat completely empty rows as ignorable.
            if all((v or "").strip() == "" for v in row.values()):
                continue

            if time_mode == "t_ms":
                if "dt_ms" in row and (row["dt_ms"] or "").strip() != "":
                    raise ValueError(f"{path}:{lineno0}: dt_ms is only valid with time_mode=dt_ms")
                if "t_ms" not in row:
                    raise ValueError(f"{path}:{lineno0}: missing t_ms")
            else:
                if "t_ms" in row and (row["t_ms"] or "").strip() != "":
                    raise ValueError(f"{path}:{lineno0}: t_ms is not valid with time_mode=dt_ms")
                if "dt_ms" not in row:
                    raise ValueError(f"{path}:{lineno0}: missing dt_ms")
            if "cls" not in row:
                raise ValueError(f"{path}:{lineno0}: missing cls")
            if "candidates" not in row and "layers" not in row:
                raise ValueError(f"{path}:{lineno0}: missing candidates (or layers)")

            token_index = parse_optional_int(row.get("token_index", "") or "", "token_index", lineno0)
            if token_index is not None and token_index < 0:
                raise ValueError(f"{path}:{lineno0}: token_index must be >= 0")

            if time_mode == "t_ms":
                t_raw = (row.get("t_ms", "") or "").strip()
                if t_raw == "":
                    raise ValueError(f"{path}:{lineno0}: missing t_ms")
                t_ms = float(t_raw)
                if t_ms < 0.0:
                    raise ValueError(f"{path}:{lineno0}: t_ms must be >= 0")
            else:
                dt_raw = (row.get("dt_ms", "") or "").strip()
                if dt_raw == "":
                    raise ValueError(f"{path}:{lineno0}: missing dt_ms")
                dt_ms = float(dt_raw)
                if dt_ms < 0.0:
                    raise ValueError(f"{path}:{lineno0}: dt_ms must be >= 0")
                t_ms_accum += dt_ms
                t_ms = t_ms_accum

            cls_raw = (row.get("cls", "") or "").strip()
            cls_norm = cls_raw.lower()
            if cls_norm == "interactive":
                cls = LatencyClass.INTERACTIVE
            elif cls_norm == "batch":
                cls = LatencyClass.BATCH
            else:
                raise ValueError(f"{path}:{lineno0}: cls must be 'interactive' or 'batch'")

            layers: Optional[Tuple[LayerRoute, ...]] = None
            candidates: List[int] = []
            layers_cell = (row.get("layers", "") or "").strip()
            if layers_cell != "":
                try:
                    layers_obj = json.loads(layers_cell)
                except json.JSONDecodeError:
                    raise ValueError(f"{path}:{lineno0}: layers must be valid JSON")
                if not isinstance(layers_obj, list):
                    raise ValueError(f"{path}:{lineno0}: layers must be a JSON list")
                layer_routes: List[LayerRoute] = []
                union: List[int] = []
                seen_union: set[int] = set()
                for li, lobj in enumerate(layers_obj):
                    if not isinstance(lobj, dict):
                        raise ValueError(f"{path}:{lineno0}: layers[{li}] must be a JSON object")
                    if "candidates" not in lobj:
                        raise ValueError(f"{path}:{lineno0}: layers[{li}] missing candidates")
                    lcand_raw = lobj["candidates"]
                    if not isinstance(lcand_raw, list):
                        raise ValueError(f"{path}:{lineno0}: layers[{li}].candidates must be a JSON list")
                    lcands: List[int] = []
                    for c in lcand_raw:
                        if not isinstance(c, int):
                            raise ValueError(f"{path}:{lineno0}: layers[{li}].candidates must be integers")
                        if c < 0:
                            raise ValueError(f"{path}:{lineno0}: layers[{li}].candidates must be >= 0")
                        lcands.append(int(c))
                    if len(lcands) == 0:
                        raise ValueError(f"{path}:{lineno0}: layers[{li}].candidates must be non-empty")
                    if len(set(lcands)) != len(lcands):
                        raise ValueError(f"{path}:{lineno0}: layers[{li}].candidates must be unique")

                    layer_k: Optional[int] = None
                    if "k" in lobj and lobj["k"] is not None:
                        lk_raw = lobj["k"]
                        if not isinstance(lk_raw, int):
                            raise ValueError(f"{path}:{lineno0}: layers[{li}].k must be an integer")
                        if lk_raw <= 0:
                            raise ValueError(f"{path}:{lineno0}: layers[{li}].k must be > 0")
                        layer_k = int(lk_raw)

                    layer_scores: Optional[Tuple[float, ...]] = None
                    if "scores" in lobj and lobj["scores"] is not None:
                        ls_raw = lobj["scores"]
                        if not isinstance(ls_raw, list):
                            raise ValueError(f"{path}:{lineno0}: layers[{li}].scores must be a JSON list")
                        if len(ls_raw) != len(lcands):
                            raise ValueError(f"{path}:{lineno0}: layers[{li}].scores must have same length as candidates")
                        out_scores: List[float] = []
                        for s in ls_raw:
                            if not isinstance(s, (int, float)):
                                raise ValueError(f"{path}:{lineno0}: layers[{li}].scores must be numbers")
                            out_scores.append(float(s))
                        layer_scores = tuple(out_scores)

                    layer_cost_scale: Optional[float] = None
                    if "cost_scale" in lobj and lobj["cost_scale"] is not None:
                        lcs_raw = lobj["cost_scale"]
                        if not isinstance(lcs_raw, (int, float)):
                            raise ValueError(f"{path}:{lineno0}: layers[{li}].cost_scale must be a number")
                        if float(lcs_raw) <= 0.0:
                            raise ValueError(f"{path}:{lineno0}: layers[{li}].cost_scale must be > 0")
                        layer_cost_scale = float(lcs_raw)

                    layer_routes.append(LayerRoute(candidates=tuple(lcands), k=layer_k, scores=layer_scores, cost_scale=layer_cost_scale))
                    for c in lcands:
                        if c not in seen_union:
                            union.append(c)
                            seen_union.add(c)

                if len(layer_routes) == 0:
                    raise ValueError(f"{path}:{lineno0}: layers must be non-empty")
                if (row.get("scores", "") or "").strip() != "":
                    raise ValueError(f"{path}:{lineno0}: scores is not valid when layers are present (use layers[].scores)")

                cand_cell = (row.get("candidates", "") or "").strip()
                if cand_cell != "":
                    candidates = parse_int_list(cand_cell, "candidates", lineno0)
                    if len(candidates) == 0:
                        raise ValueError(f"{path}:{lineno0}: candidates must be non-empty")
                    for c in candidates:
                        if c < 0:
                            raise ValueError(f"{path}:{lineno0}: candidates must be >= 0")
                    if len(set(candidates)) != len(candidates):
                        raise ValueError(f"{path}:{lineno0}: candidates must be unique")
                    if candidates != union:
                        raise ValueError(f"{path}:{lineno0}: candidates must equal the union of layers[].candidates when layers are present")
                else:
                    candidates = union
                layers = tuple(layer_routes)
            else:
                if "candidates" not in row:
                    raise ValueError(f"{path}:{lineno0}: missing candidates")
                candidates = parse_int_list(row.get("candidates", "") or "", "candidates", lineno0)
                if len(candidates) == 0:
                    raise ValueError(f"{path}:{lineno0}: candidates must be non-empty")
                for c in candidates:
                    if c < 0:
                        raise ValueError(f"{path}:{lineno0}: candidates must be >= 0")
                if len(set(candidates)) != len(candidates):
                    raise ValueError(f"{path}:{lineno0}: candidates must be unique")

            k = parse_optional_int(row.get("k", "") or "", "k", lineno0)
            if k is not None and k <= 0:
                raise ValueError(f"{path}:{lineno0}: k must be > 0")

            scores = parse_optional_float_list(row.get("scores", "") or "", "scores", lineno0) if layers is None else None
            if scores is not None:
                if len(scores) != len(candidates):
                    raise ValueError(f"{path}:{lineno0}: scores length must match candidates length")

            mtp_accept_len = parse_optional_int(row.get("mtp_accept_len", "") or "", "mtp_accept_len", lineno0)
            if mtp_accept_len is not None and mtp_accept_len < 1:
                raise ValueError(f"{path}:{lineno0}: mtp_accept_len must be >= 1")
            accepted_mtp = parse_optional_int(row.get("accepted_mtp", "") or "", "accepted_mtp", lineno0)
            if accepted_mtp is not None and accepted_mtp < 0:
                raise ValueError(f"{path}:{lineno0}: accepted_mtp must be >= 0")
            rejected_mtp = parse_optional_int(row.get("rejected_mtp", "") or "", "rejected_mtp", lineno0)
            if rejected_mtp is not None and rejected_mtp < 0:
                raise ValueError(f"{path}:{lineno0}: rejected_mtp must be >= 0")

            dflash_accept_len = parse_optional_int(row.get("dflash_accept_len", "") or "", "dflash_accept_len", lineno0)
            if dflash_accept_len is not None and dflash_accept_len < 1:
                raise ValueError(f"{path}:{lineno0}: dflash_accept_len must be >= 1")
            accepted_dflash = parse_optional_int(row.get("accepted_dflash", "") or "", "accepted_dflash", lineno0)
            if accepted_dflash is not None and accepted_dflash < 0:
                raise ValueError(f"{path}:{lineno0}: accepted_dflash must be >= 0")
            rejected_dflash = parse_optional_int(row.get("rejected_dflash", "") or "", "rejected_dflash", lineno0)
            if rejected_dflash is not None and rejected_dflash < 0:
                raise ValueError(f"{path}:{lineno0}: rejected_dflash must be >= 0")

            cost_scale = parse_optional_float(row.get("cost_scale", "") or "", "cost_scale", lineno0)
            if cost_scale is not None and cost_scale <= 0.0:
                raise ValueError(f"{path}:{lineno0}: cost_scale must be > 0")
            decode_ms = parse_optional_float(row.get("decode_ms", "") or "", "decode_ms", lineno0)
            if decode_ms is not None and decode_ms < 0.0:
                raise ValueError(f"{path}:{lineno0}: decode_ms must be >= 0")
            kv_tokens = parse_optional_int(row.get("kv_tokens", "") or "", "kv_tokens", lineno0)
            if kv_tokens is not None and kv_tokens < 0:
                raise ValueError(f"{path}:{lineno0}: kv_tokens must be >= 0")
            expert_batch_size = parse_optional_int(row.get("expert_batch_size", "") or "", "expert_batch_size", lineno0)
            if expert_batch_size is not None and expert_batch_size < 0:
                raise ValueError(f"{path}:{lineno0}: expert_batch_size must be >= 0")

            routes.append(
                TokenRoute(
                    t_ms=t_ms,
                    cls=cls,
                    candidates=tuple(candidates),
                    token_index=token_index,
                    k=k,
                    scores=scores,
                    mtp_accept_len=mtp_accept_len,
                    accepted_mtp=accepted_mtp,
                    rejected_mtp=rejected_mtp,
                    dflash_accept_len=dflash_accept_len,
                    accepted_dflash=accepted_dflash,
                    rejected_dflash=rejected_dflash,
                    cost_scale=cost_scale,
                    decode_ms=decode_ms,
                    kv_tokens=kv_tokens,
                    expert_batch_size=expert_batch_size,
                    layers=layers,
                )
            )

    routes.sort(key=lambda r: r.t_ms)
    return(routes)


def write_trace_csv(path: str, trace: Sequence[TokenRoute]) -> None:
    if path.strip() == "":
        raise ValueError("path must be non-empty")
    with open(path, "w", encoding="utf-8", newline="") as f:
        fieldnames = [
            "t_ms",
            "cls",
            "candidates",
            "layers",
            "token_index",
            "k",
            "scores",
            "mtp_accept_len",
            "accepted_mtp",
            "rejected_mtp",
            "dflash_accept_len",
            "accepted_dflash",
            "rejected_dflash",
            "cost_scale",
            "decode_ms",
            "kv_tokens",
            "expert_batch_size",
        ]
        w = csv.DictWriter(f, fieldnames=fieldnames)
        w.writeheader()
        for r in trace:
            layers_cell = ""
            if r.layers is not None and len(r.layers) != 0:
                layers_json: List[Dict[str, object]] = []
                for lr in r.layers:
                    lobj: Dict[str, object] = {"candidates": list(lr.candidates)}
                    if lr.k is not None:
                        lobj["k"] = int(lr.k)
                    if lr.scores is not None:
                        lobj["scores"] = list(lr.scores)
                    if lr.cost_scale is not None:
                        lobj["cost_scale"] = float(lr.cost_scale)
                    layers_json.append(lobj)
                layers_cell = json.dumps(layers_json, sort_keys=True)
            row: Dict[str, str] = {
                "t_ms": str(float(r.t_ms)),
                "cls": str(r.cls.value),
                "candidates": json.dumps(list(r.candidates)),
                "layers": layers_cell,
                "token_index": "" if r.token_index is None else str(int(r.token_index)),
                "k": "" if r.k is None else str(int(r.k)),
                "scores": "" if r.scores is None else json.dumps(list(r.scores)),
                "mtp_accept_len": "" if r.mtp_accept_len is None else str(int(r.mtp_accept_len)),
                "accepted_mtp": "" if r.accepted_mtp is None else str(int(r.accepted_mtp)),
                "rejected_mtp": "" if r.rejected_mtp is None else str(int(r.rejected_mtp)),
                "dflash_accept_len": "" if r.dflash_accept_len is None else str(int(r.dflash_accept_len)),
                "accepted_dflash": "" if r.accepted_dflash is None else str(int(r.accepted_dflash)),
                "rejected_dflash": "" if r.rejected_dflash is None else str(int(r.rejected_dflash)),
                "cost_scale": "" if r.cost_scale is None else str(float(r.cost_scale)),
                "decode_ms": "" if r.decode_ms is None else str(float(r.decode_ms)),
                "kv_tokens": "" if r.kv_tokens is None else str(int(r.kv_tokens)),
                "expert_batch_size": "" if r.expert_batch_size is None else str(int(r.expert_batch_size)),
            }
            w.writerow(row)


def write_trace_jsonl(path: str, trace: Sequence[TokenRoute]) -> None:
    if path.strip() == "":
        raise ValueError("path must be non-empty")
    f = sys.stdout if path == "-" else open(path, "w", encoding="utf-8")
    try:
        for r in trace:
            obj: Dict[str, object] = {
                "t_ms": float(r.t_ms),
                "cls": str(r.cls.value),
                "candidates": list(r.candidates),
            }
            if r.layers is not None and len(r.layers) != 0:
                layers_json: List[Dict[str, object]] = []
                for lr in r.layers:
                    lobj: Dict[str, object] = {"candidates": list(lr.candidates)}
                    if lr.k is not None:
                        lobj["k"] = int(lr.k)
                    if lr.scores is not None:
                        lobj["scores"] = list(lr.scores)
                    if lr.cost_scale is not None:
                        lobj["cost_scale"] = float(lr.cost_scale)
                    layers_json.append(lobj)
                obj["layers"] = layers_json
            if r.token_index is not None:
                obj["token_index"] = int(r.token_index)
            if r.k is not None:
                obj["k"] = int(r.k)
            if r.scores is not None:
                obj["scores"] = list(r.scores)
            if r.mtp_accept_len is not None:
                obj["mtp_accept_len"] = int(r.mtp_accept_len)
            if r.accepted_mtp is not None:
                obj["accepted_mtp"] = int(r.accepted_mtp)
            if r.rejected_mtp is not None:
                obj["rejected_mtp"] = int(r.rejected_mtp)
            if r.dflash_accept_len is not None:
                obj["dflash_accept_len"] = int(r.dflash_accept_len)
            if r.accepted_dflash is not None:
                obj["accepted_dflash"] = int(r.accepted_dflash)
            if r.rejected_dflash is not None:
                obj["rejected_dflash"] = int(r.rejected_dflash)
            if r.cost_scale is not None:
                obj["cost_scale"] = float(r.cost_scale)
            if r.decode_ms is not None:
                obj["decode_ms"] = float(r.decode_ms)
            if r.kv_tokens is not None:
                obj["kv_tokens"] = int(r.kv_tokens)
            if r.expert_batch_size is not None:
                obj["expert_batch_size"] = int(r.expert_batch_size)
            f.write(json.dumps(obj, sort_keys=True))
            f.write("\n")
    finally:
        if path != "-":
            f.close()


def write_sim_jsonl(path: str, trace: Sequence[TokenRoute], tokens: Sequence[TokenState], cfg: SimConfig, meta: Optional[Dict[str, object]] = None) -> None:
    if path.strip() == "":
        raise ValueError("path must be non-empty")
    if len(trace) != len(tokens):
        raise ValueError("trace/tokens length mismatch")

    meta_out: Dict[str, object] = {"sim_token_dump": True, "num_tokens": int(len(trace)), "sim_cfg": dataclasses.asdict(cfg)}
    if meta is not None and len(meta) != 0:
        meta_out["trace_meta"] = dict(meta)

    f = sys.stdout if path == "-" else open(path, "w", encoding="utf-8")
    try:
        f.write(json.dumps({"type": "meta", "meta": meta_out}, sort_keys=True))
        f.write("\n")
        for i, (r, ts) in enumerate(zip(trace, tokens)):
            obj: Dict[str, object] = {
                "type": "sim_token",
                "i": int(i),
                "t_ms": float(ts.submit_ms),
                "cls": str(ts.cls.value),
                "chosen_k": int(ts.chosen_k),
                "done_ms": None if ts.done_ms is None else float(ts.done_ms),
                "lat_ms": None if ts.done_ms is None else float(float(ts.done_ms) - float(ts.submit_ms)),
                "admitted_any": bool(ts.admitted_any),
                "admitted_tasks_total": int(ts.admitted_tasks_total),
                "dropped_tasks_backpressure": int(ts.dropped_tasks_backpressure),
                "skipped_stages_backpressure": int(ts.skipped_stages_backpressure),
                "skipped_stages_backpressure_verify": int(ts.skipped_stages_backpressure_verify),
                "skipped_stages_backpressure_draft": int(ts.skipped_stages_backpressure_draft),
                "effective_k_layer0": int(ts.admitted_verify_layer0),
                "effective_k_total": int(ts.admitted_verify_total),
                "desired_verify_layer0": int(ts.desired_verify_layer0),
                "partial_any_layer": bool(ts.partial_any_layer),
                    "output_len": int(ts.output_len),
                    "mtp_accept_len": int(ts.mtp_accept_len),
                    "mtp_draft_attempt_len": int(ts.mtp_draft_attempt_len),
                    "mtp_verify_layer0_skipped_backpressure": bool(ts.mtp_verify_layer0_skipped_backpressure),
                    "mtp_accept_len_clamped_backpressure": bool(ts.mtp_accept_len_clamped_backpressure),
                    "trace_decode_ms": ts.trace_decode_ms,
                    "trace_kv_tokens": ts.trace_kv_tokens,
                    "trace_expert_batch_size": ts.trace_expert_batch_size,
                    "stage_total": int(ts.stage_total),
                }
            if r.token_index is not None:
                obj["token_index"] = int(r.token_index)
            if r.decode_ms is not None and ts.trace_decode_ms is None:
                obj["trace_decode_ms"] = float(r.decode_ms)
            if r.kv_tokens is not None and ts.trace_kv_tokens is None:
                obj["trace_kv_tokens"] = int(r.kv_tokens)
            if r.expert_batch_size is not None and ts.trace_expert_batch_size is None:
                obj["trace_expert_batch_size"] = int(r.expert_batch_size)
            f.write(json.dumps(obj, sort_keys=True))
            f.write("\n")
    finally:
        if path != "-":
            f.close()


def _derive_mtp_accept_len(route: TokenRoute, mtp_draft_len: int) -> Optional[int]:
    if route.mtp_accept_len is not None:
        return(int(route.mtp_accept_len))
    if route.accepted_mtp is not None:
        return(int(route.accepted_mtp) + 1)
    if route.rejected_mtp is not None and mtp_draft_len > 0:
        return((int(mtp_draft_len) - int(route.rejected_mtp)) + 1)
    return(None)


def _derive_dflash_accept_len(route: TokenRoute) -> Optional[int]:
    if route.dflash_accept_len is not None:
        return(int(route.dflash_accept_len))
    if route.accepted_dflash is not None:
        al = (int(route.accepted_dflash) + 1)
        if al < 1:
            return(None)
        return(int(al))
    return(None)


def write_trace_jsonl_canonical(path: str, trace: Sequence[TokenRoute], meta: Optional[Dict[str, object]] = None) -> None:
    if path.strip() == "":
        raise ValueError("path must be non-empty")
    meta_out: Dict[str, object] = {} if meta is None else dict(meta)
    meta_out["canonicalized_trace"] = True

    inferred_num_experts = infer_num_experts_from_trace(trace, meta)
    if inferred_num_experts is not None and "num_experts" not in meta_out:
        meta_out["num_experts"] = int(inferred_num_experts)
    inferred_mtp_draft_len = infer_mtp_draft_len_from_trace(trace, meta)
    if inferred_mtp_draft_len is not None and "mtp_draft_len" not in meta_out:
        meta_out["mtp_draft_len"] = int(inferred_mtp_draft_len)

    mtp_draft_len = 0
    if isinstance(meta_out.get("mtp_draft_len"), int):
        mtp_draft_len = int(meta_out["mtp_draft_len"])

    f = sys.stdout if path == "-" else open(path, "w", encoding="utf-8")
    try:
        f.write(json.dumps({"type": "meta", "meta": meta_out}, sort_keys=True))
        f.write("\n")
        for r in trace:
            obj: Dict[str, object] = {
                "t_ms": float(r.t_ms),
                "cls": str(r.cls.value),
                "candidates": list(r.candidates),
            }
            if r.layers is not None and len(r.layers) != 0:
                layers_json: List[Dict[str, object]] = []
                for lr in r.layers:
                    lobj: Dict[str, object] = {"candidates": list(lr.candidates)}
                    if lr.k is not None:
                        lobj["k"] = int(lr.k)
                    if lr.scores is not None:
                        lobj["scores"] = list(lr.scores)
                    if lr.cost_scale is not None:
                        lobj["cost_scale"] = float(lr.cost_scale)
                    layers_json.append(lobj)
                obj["layers"] = layers_json
            if r.token_index is not None:
                obj["token_index"] = int(r.token_index)
            if r.k is not None:
                obj["k"] = int(r.k)
            if r.scores is not None:
                obj["scores"] = list(r.scores)
            mtp_accept_len = _derive_mtp_accept_len(r, mtp_draft_len)
            if mtp_accept_len is not None:
                obj["mtp_accept_len"] = int(mtp_accept_len)
            if r.accepted_mtp is not None:
                obj["accepted_mtp"] = int(r.accepted_mtp)
            if r.rejected_mtp is not None:
                obj["rejected_mtp"] = int(r.rejected_mtp)
            dflash_accept_len = _derive_dflash_accept_len(r)
            if dflash_accept_len is not None:
                obj["dflash_accept_len"] = int(dflash_accept_len)
            if r.accepted_dflash is not None:
                obj["accepted_dflash"] = int(r.accepted_dflash)
            if r.rejected_dflash is not None:
                obj["rejected_dflash"] = int(r.rejected_dflash)
            if r.cost_scale is not None:
                obj["cost_scale"] = float(r.cost_scale)
            if r.decode_ms is not None:
                obj["decode_ms"] = float(r.decode_ms)
            if r.kv_tokens is not None:
                obj["kv_tokens"] = int(r.kv_tokens)
            if r.expert_batch_size is not None:
                obj["expert_batch_size"] = int(r.expert_batch_size)
            f.write(json.dumps(obj, sort_keys=True))
            f.write("\n")
    finally:
        if path != "-":
            f.close()


def trace_summary_jsonable(trace: Sequence[TokenRoute], mtp_draft_len: int = 0, meta: Optional[Dict[str, object]] = None) -> Dict[str, object]:
    def summarize(xs: Sequence[float]) -> Dict[str, object]:
        if len(xs) == 0:
            return({"count": 0})
        xs_sorted = sorted(xs)
        idx50 = int(math.floor(0.50 * float(len(xs_sorted) - 1)))
        idx95 = int(math.floor(0.95 * float(len(xs_sorted) - 1)))
        idx99 = int(math.floor(0.99 * float(len(xs_sorted) - 1)))
        return(
            {
                "count": len(xs_sorted),
                "mean": statistics.fmean(xs_sorted),
                "min": float(xs_sorted[0]),
                "p50": float(xs_sorted[idx50]),
                "p95": float(xs_sorted[idx95]),
                "p99": float(xs_sorted[idx99]),
                "max": float(xs_sorted[-1]),
            }
        )

    num_i = 0
    num_b = 0
    t_ms: List[float] = []
    token_index_vals: List[float] = []
    cand_lens: List[float] = []
    layer_counts: List[float] = []
    layer_cand_lens: List[float] = []
    k_vals: List[float] = []
    accept_lens: List[float] = []
    dflash_accept_lens: List[float] = []
    decode_ms: List[float] = []
    kv_tokens: List[float] = []
    expert_batch_size: List[float] = []
    min_expert: Optional[int] = None
    max_expert: Optional[int] = None

    present_token_index = 0
    present_k = 0
    present_scores = 0
    present_layers = 0
    present_layer_scores = 0
    present_layer_cost_scale = 0
    present_accept_len = 0
    present_accepted_mtp = 0
    present_rejected_mtp = 0
    present_dflash_accept_len = 0
    present_accepted_dflash = 0
    present_rejected_dflash = 0
    present_cost_scale = 0
    present_decode_ms = 0
    present_kv_tokens = 0
    present_expert_batch_size = 0

    for r in trace:
        if r.cls == LatencyClass.INTERACTIVE:
            num_i += 1
        else:
            num_b += 1
        t_ms.append(float(r.t_ms))
        if r.token_index is not None:
            present_token_index += 1
            token_index_vals.append(float(r.token_index))
        cand_lens.append(float(len(r.candidates)))
        if r.layers is not None:
            present_layers += 1
        layers = _route_layers(r)
        layer_counts.append(float(len(layers)))
        for lr in layers:
            layer_cand_lens.append(float(len(lr.candidates)))
            if lr.scores is not None:
                present_layer_scores += 1
            if lr.cost_scale is not None:
                present_layer_cost_scale += 1
        if len(r.candidates) != 0:
            lo = min(r.candidates)
            hi = max(r.candidates)
            min_expert = lo if min_expert is None else min(min_expert, lo)
            max_expert = hi if max_expert is None else max(max_expert, hi)

        if r.k is not None:
            present_k += 1
            k_vals.append(float(r.k))
        if r.scores is not None:
            present_scores += 1
        if r.mtp_accept_len is not None:
            present_accept_len += 1
            accept_lens.append(float(r.mtp_accept_len))
        elif r.accepted_mtp is not None:
            present_accepted_mtp += 1
            accept_lens.append(float(int(r.accepted_mtp) + 1))
        elif r.rejected_mtp is not None:
            present_rejected_mtp += 1
            if mtp_draft_len > 0:
                accept_lens.append(float((mtp_draft_len - int(r.rejected_mtp)) + 1))
        if r.dflash_accept_len is not None:
            present_dflash_accept_len += 1
            dflash_accept_lens.append(float(r.dflash_accept_len))
        elif r.accepted_dflash is not None:
            present_accepted_dflash += 1
            dflash_accept_lens.append(float(int(r.accepted_dflash) + 1))
        elif r.rejected_dflash is not None:
            present_rejected_dflash += 1
        if r.cost_scale is not None:
            present_cost_scale += 1
        if r.decode_ms is not None:
            present_decode_ms += 1
            decode_ms.append(float(r.decode_ms))
        if r.kv_tokens is not None:
            present_kv_tokens += 1
            kv_tokens.append(float(r.kv_tokens))
        if r.expert_batch_size is not None:
            present_expert_batch_size += 1
            expert_batch_size.append(float(r.expert_batch_size))

    out: Dict[str, object] = {
        "tokens": {"count": len(trace), "interactive": num_i, "batch": num_b},
        "t_ms": summarize(t_ms),
        "candidates_len": summarize(cand_lens),
        "layers_count": summarize(layer_counts),
        "layer_candidates_len": summarize(layer_cand_lens),
        "optional_fields_present": {
            "token_index": present_token_index,
            "k": present_k,
            "scores": present_scores,
            "layers": present_layers,
            "layer_scores": present_layer_scores,
            "layer_cost_scale": present_layer_cost_scale,
            "mtp_accept_len": present_accept_len,
            "accepted_mtp": present_accepted_mtp,
            "rejected_mtp": present_rejected_mtp,
            "dflash_accept_len": present_dflash_accept_len,
            "accepted_dflash": present_accepted_dflash,
            "rejected_dflash": present_rejected_dflash,
            "cost_scale": present_cost_scale,
            "decode_ms": present_decode_ms,
            "kv_tokens": present_kv_tokens,
            "expert_batch_size": present_expert_batch_size,
        },
    }
    if meta is not None and len(meta) != 0:
        out["meta"] = meta
    if min_expert is not None and max_expert is not None:
        out["expert_id_range"] = {"min": int(min_expert), "max": int(max_expert)}
    if len(k_vals) != 0:
        out["k"] = summarize(k_vals)
    if len(accept_lens) != 0:
        out["mtp_accept_len_derived"] = summarize(accept_lens)
    if len(dflash_accept_lens) != 0:
        out["dflash_accept_len_derived"] = summarize(dflash_accept_lens)
    if len(decode_ms) != 0:
        out["decode_ms"] = summarize(decode_ms)
    if len(token_index_vals) != 0:
        out["token_index"] = summarize(token_index_vals)
    if len(kv_tokens) != 0:
        out["kv_tokens"] = summarize(kv_tokens)
    if len(expert_batch_size) != 0:
        out["expert_batch_size"] = summarize(expert_batch_size)
    inferred: Dict[str, object] = {}
    inferred_num_experts = infer_num_experts_from_trace(trace, meta)
    if inferred_num_experts is not None:
        inferred["num_experts"] = int(inferred_num_experts)
    inferred_mtp_draft_len = infer_mtp_draft_len_from_trace(trace, meta)
    if inferred_mtp_draft_len is not None:
        inferred["mtp_draft_len"] = int(inferred_mtp_draft_len)
    if len(inferred) != 0:
        out["inferred"] = inferred
    return(out)


def infer_num_experts_from_trace(trace: Sequence[TokenRoute], meta: Optional[Dict[str, object]] = None) -> Optional[int]:
    if meta is not None:
        v = meta.get("num_experts")
        if isinstance(v, int) and v > 0:
            return(int(v))

    max_expert: Optional[int] = None
    for r in trace:
        for lr in _route_layers(r):
            for e in lr.candidates:
                max_expert = int(e) if max_expert is None else max(max_expert, int(e))
    if max_expert is None:
        return(None)
    return(int(max_expert) + 1)


def infer_mtp_draft_len_from_trace(trace: Sequence[TokenRoute], meta: Optional[Dict[str, object]] = None) -> Optional[int]:
    if meta is not None:
        v = meta.get("mtp_draft_len")
        if isinstance(v, int) and v >= 0:
            return(int(v))

    gamma: Optional[int] = None
    for r in trace:
        if r.accepted_mtp is None or r.rejected_mtp is None:
            continue
        g = (int(r.accepted_mtp) + int(r.rejected_mtp))
        if gamma is None:
            gamma = g
        elif gamma != g:
            return(None)
    return(gamma)


def _clamp_i32(v: int, lo: int, hi: int) -> int:
    if v < lo:
        return(lo)
    if v > hi:
        return(hi)
    return(v)


@dataclass
class KControllerState:
    last_update_ms: float = -1.0
    ema_pending: float = 0.0
    k: int = 0


def expected_mtp_accept_len(mtp_draft_len: int, mtp_accept_prob: float, mtp_accept_decay: float) -> float:
    if mtp_draft_len <= 0:
        return(1.0)
    if mtp_accept_prob <= 0.0:
        return(1.0)
    if mtp_accept_decay <= 0.0:
        return(1.0)

    exp_len = 1.0
    p_prod = 1.0
    for i in range(mtp_draft_len):
        p = (mtp_accept_prob * (mtp_accept_decay ** float(i)))
        if p < 0.0:
            p = 0.0
        if p > 1.0:
            p = 1.0
        p_prod *= p
        exp_len += p_prod
    return(exp_len)


def arrival_rate_steps_tps(arrival_rate_tps: float, arrival_units: str, mtp_draft_len: int, mtp_accept_prob: float, mtp_accept_decay: float) -> float:
    units = arrival_units.strip().lower()
    if units == "steps":
        return(arrival_rate_tps)
    if units == "output_tokens":
        exp_len = expected_mtp_accept_len(mtp_draft_len, mtp_accept_prob, mtp_accept_decay)
        if exp_len <= 0.0:
            exp_len = 1.0
        return(arrival_rate_tps / exp_len)
    raise ValueError("arrival_units must be 'steps' or 'output_tokens'")


def expert_pending_for_class(eq: ExpertQueue, cls: LatencyClass) -> int:
    if cls == LatencyClass.INTERACTIVE:
        return(eq.in_flight_tasks_hi + len(eq.hi))
    return(eq.in_flight_tasks_lo + len(eq.lo))


def choose_k(adapt: AdaptiveKConfig, cls: LatencyClass, pending: float) -> int:
    if cls == LatencyClass.INTERACTIVE:
        k_min, k_max = adapt.k_min_interactive, adapt.k_max_interactive
    else:
        k_min, k_max = adapt.k_min_batch, adapt.k_max_batch

    if pending <= float(adapt.q_low):
        return(k_max)
    if pending >= float(adapt.q_high):
        return(k_min)

    span_q = (adapt.q_high - adapt.q_low)
    if span_q <= 0:
        return(_clamp_i32(k_min, k_min, k_max))
    frac = (pending - float(adapt.q_low)) / float(span_q)
    k = int(round(float(k_max) - (frac * float(k_max - k_min))))
    return(_clamp_i32(k, k_min, k_max))


def _route_layers(route: TokenRoute) -> Tuple[LayerRoute, ...]:
    if route.layers is None or len(route.layers) == 0:
        return((LayerRoute(candidates=route.candidates, k=route.k, scores=route.scores, cost_scale=None),))
    return(route.layers)


def _validate_trace_expert_ids(trace: Sequence[TokenRoute], num_experts: int) -> None:
    if num_experts <= 0:
        return
    for i, r in enumerate(trace):
        token_index = r.token_index
        token_tag = f"trace[{i}]"
        if token_index is not None:
            token_tag += f" token_index={int(token_index)}"
        token_tag += f" t_ms={float(r.t_ms)}"

        if r.layers is not None:
            for li, lr in enumerate(_route_layers(r)):
                for e in lr.candidates:
                    if e < 0 or e >= num_experts:
                        raise ValueError(f"{token_tag}: layers[{li}].candidates expert_id={int(e)} out of range for num_experts={int(num_experts)}")
        else:
            for e in r.candidates:
                if e < 0 or e >= num_experts:
                    raise ValueError(f"{token_tag}: candidates expert_id={int(e)} out of range for num_experts={int(num_experts)}")


def _expert_queue_pending_limit(cfg: SimConfig, cls: LatencyClass) -> int:
    if cls == LatencyClass.INTERACTIVE:
        return(int(cfg.expert_queue_max))
    limit = (int(cfg.expert_queue_max) - int(cfg.expert_queue_reserve_interactive))
    if limit < 0:
        return(0)
    return(limit)


def _expert_queue_pending_limit_units(cfg: SimConfig, cls: LatencyClass, backpressure_units: str) -> float:
    if backpressure_units == "tasks":
        return(float(_expert_queue_pending_limit(cfg, cls)))

    if cls == LatencyClass.INTERACTIVE:
        return(float(cfg.expert_queue_max))
    limit = (float(cfg.expert_queue_max) - float(cfg.expert_queue_reserve_interactive))
    if limit < 0.0:
        return(0.0)
    return(float(limit))


def _candidate_order_for_layer(admit_policy: str, experts: Sequence[ExpertQueue], candidates: Sequence[int], scores: Optional[Sequence[float]]) -> Sequence[int]:
    if admit_policy == "ordered":
        return(candidates)
    if admit_policy == "least_pending":
        ranked = [(experts[e].pending(), i, e) for i, e in enumerate(candidates)]
        ranked.sort()
        return([e for _p, _i, e in ranked])
    if admit_policy == "score_desc":
        if scores is None:
            raise ValueError("admit_policy score_desc requires per-candidate scores")
        ranked = [(-float(scores[i]), i, e) for i, e in enumerate(candidates)]
        ranked.sort()
        return([e for _s, _i, e in ranked])
    raise ValueError("admit_policy must be 'ordered', 'least_pending', or 'score_desc'")


def _candidate_order(admit_policy: str, experts: Sequence[ExpertQueue], route: TokenRoute) -> Sequence[int]:
    return(_candidate_order_for_layer(admit_policy, experts, route.candidates, route.scores))


def _service_time_ms(cfg: SimConfig, batch_size: int) -> float:
    per_task_ms = cfg.service_per_task_ms if cfg.service_per_task_ms >= 0.0 else cfg.service_ms
    return(cfg.service_base_ms + (per_task_ms * float(batch_size)))


def _service_time_tasks_ms(cfg: SimConfig, tasks: Sequence[Task]) -> float:
    per_task_ms = cfg.service_per_task_ms if cfg.service_per_task_ms >= 0.0 else cfg.service_ms
    work = 0.0
    for t in tasks:
        work += float(t.cost_scale)
    return(cfg.service_base_ms + (per_task_ms * work))


def _start_tasks(now_ms: float, cfg: SimConfig, eq: ExpertQueue, expert_id: int, evq: List[Event], seq_ref: List[int], metrics: SimMetrics) -> None:
    _promote_aged_batch(now_ms, cfg, eq, metrics)
    while eq.in_flight < cfg.expert_parallelism:
        q: Optional[Deque[Task]] = None
        batch_max = 1
        serving_hi = False

        if len(eq.hi) != 0:
            if cfg.hi_burst > 0 and eq.hi_burst >= cfg.hi_burst and len(eq.lo) != 0:
                q = eq.lo
                batch_max = cfg.batch_max_batch
                eq.hi_burst = 0
                metrics.forced_batch_starts += 1
            else:
                q = eq.hi
                batch_max = cfg.batch_max_interactive
                serving_hi = True
        elif len(eq.lo) != 0:
            q = eq.lo
            batch_max = cfg.batch_max_batch
            eq.hi_burst = 0
        else:
            break

        if q is None:
            break
        if batch_max <= 0:
            raise RuntimeError("batch_max must be > 0")

        batch_wait_ms = cfg.batch_wait_interactive_ms if serving_hi else cfg.batch_wait_batch_ms
        if batch_wait_ms < 0.0:
            raise RuntimeError("batch_wait_ms must be >= 0")

        if batch_max > 1 and batch_wait_ms > 0.0 and len(q) < batch_max:
            due_ms = (q[0].enqueue_ms + batch_wait_ms)
            if due_ms > now_ms:
                prev_due = eq.hi_wakeup_ms if serving_hi else eq.lo_wakeup_ms
                if prev_due < 0.0 or due_ms < (prev_due - 1e-12):
                    if serving_hi:
                        eq.hi_wakeup_ms = due_ms
                    else:
                        eq.lo_wakeup_ms = due_ms
                    seq_ref[0] += 1
                    heapq.heappush(evq, Event(t_ms=due_ms, kind=EventKind.EXPERT_WAKE, seq=seq_ref[0], expert_id=expert_id))
                break

        n = min(batch_max, len(q))
        tasks: List[Task] = []
        for _i in range(n):
            t = q.popleft()
            tasks.append(t)
            if t.mtp_phase == MtpPhase.DRAFT:
                if eq.queued_tasks_mtp_draft <= 0:
                    raise RuntimeError("queued_tasks_mtp_draft underflow")
                eq.queued_tasks_mtp_draft -= 1
            elif t.mtp_phase == MtpPhase.VERIFY:
                if eq.queued_tasks_mtp_verify <= 0:
                    raise RuntimeError("queued_tasks_mtp_verify underflow")
                eq.queued_tasks_mtp_verify -= 1
            if serving_hi:
                eq.pending_work_hi -= float(t.cost_scale)
            else:
                eq.pending_work_lo -= float(t.cost_scale)
        if len(tasks) == 0:
            break

        if serving_hi:
            metrics.service_batch_size_interactive.append(float(len(tasks)))
        else:
            metrics.service_batch_size_batch.append(float(len(tasks)))

        if serving_hi:
            eq.hi_wakeup_ms = -1.0
        else:
            eq.lo_wakeup_ms = -1.0

        if serving_hi:
            eq.hi_burst += len(tasks)
        else:
            eq.hi_burst = 0

        for task in tasks:
            wait_ms = (now_ms - task.enqueue_ms)
            metrics.tasks_started_per_expert[expert_id] += 1
            if wait_ms > metrics.max_task_queue_wait_ms_per_expert[expert_id]:
                metrics.max_task_queue_wait_ms_per_expert[expert_id] = wait_ms
            if task.mtp_phase == MtpPhase.DRAFT:
                metrics.tasks_started_mtp_draft += 1
                metrics.task_queue_wait_ms_mtp_draft.append(wait_ms)
            elif task.mtp_phase == MtpPhase.VERIFY:
                metrics.tasks_started_mtp_verify += 1
                metrics.task_queue_wait_ms_mtp_verify.append(wait_ms)
            if wait_ms >= cfg.starvation_ms:
                metrics.starved_tasks += 1
                metrics.starved_tasks_started_per_expert[expert_id] += 1
                if task.mtp_phase == MtpPhase.DRAFT:
                    metrics.starved_tasks_mtp_draft += 1
                elif task.mtp_phase == MtpPhase.VERIFY:
                    metrics.starved_tasks_mtp_verify += 1
                if task.cls == LatencyClass.INTERACTIVE:
                    metrics.starved_tasks_interactive += 1
                else:
                    metrics.starved_tasks_batch += 1
            if task.cls == LatencyClass.INTERACTIVE:
                metrics.task_queue_wait_ms_interactive.append(wait_ms)
            else:
                metrics.task_queue_wait_ms_batch.append(wait_ms)
            task.start_ms = now_ms
            task.served_hi = serving_hi

        per_task_ms = cfg.service_per_task_ms if cfg.service_per_task_ms >= 0.0 else cfg.service_ms
        work_units_total = 0.0
        work_units_draft = 0.0
        work_units_verify = 0.0
        for t in tasks:
            u = float(t.cost_scale)
            work_units_total += u
            if t.cls == LatencyClass.INTERACTIVE:
                metrics.work_units_interactive += u
            else:
                metrics.work_units_batch += u
            if t.mtp_phase == MtpPhase.DRAFT:
                work_units_draft += u
            elif t.mtp_phase == MtpPhase.VERIFY:
                work_units_verify += u
        metrics.work_units_total += work_units_total
        metrics.work_units_mtp_draft += work_units_draft
        metrics.work_units_mtp_verify += work_units_verify
        metrics.service_batches_started += 1
        metrics.service_base_ms_total += cfg.service_base_ms
        metrics.service_task_ms_total += (per_task_ms * work_units_total)
        dt_ms = (cfg.service_base_ms + (per_task_ms * work_units_total))
        metrics.service_slot_ms_total += dt_ms
        if serving_hi:
            metrics.service_slot_ms_interactive += dt_ms
        else:
            metrics.service_slot_ms_batch += dt_ms
        if work_units_total > 0.0:
            if work_units_draft > 0.0:
                metrics.service_slot_ms_mtp_draft += (dt_ms * (work_units_draft / work_units_total))
            if work_units_verify > 0.0:
                metrics.service_slot_ms_mtp_verify += (dt_ms * (work_units_verify / work_units_total))

        eq.in_flight += 1
        eq.in_flight_tasks += len(tasks)
        if serving_hi:
            eq.in_flight_tasks_hi += len(tasks)
            eq.in_flight_work_hi += work_units_total
        else:
            eq.in_flight_tasks_lo += len(tasks)
            eq.in_flight_work_lo += work_units_total
        n_draft = 0
        n_verify = 0
        for t in tasks:
            if t.mtp_phase == MtpPhase.DRAFT:
                n_draft += 1
            elif t.mtp_phase == MtpPhase.VERIFY:
                n_verify += 1
        eq.in_flight_tasks_mtp_draft += n_draft
        eq.in_flight_tasks_mtp_verify += n_verify
        seq_ref[0] += 1
        heapq.heappush(evq, Event(t_ms=(now_ms + dt_ms), kind=EventKind.TASK_DONE, seq=seq_ref[0], expert_id=expert_id, tasks=tuple(tasks)))


def _sample_mtp_accept_len(cfg: SimConfig, rng: random.Random, metrics: SimMetrics, draft_attempt_policy: str) -> int:
    if cfg.mtp_draft_len <= 0:
        return(1)
    if cfg.mtp_accept_prob <= 0.0:
        return(1)
    if cfg.mtp_accept_prob > 1.0:
        return(1)
    if cfg.mtp_accept_decay <= 0.0:
        return(1)

    draft_len = cfg.mtp_draft_len
    accepted_draft = 0
    attempted = 0
    for i in range(draft_len):
        metrics.mtp_pos_attempted[i] += 1
        p = (cfg.mtp_accept_prob * (cfg.mtp_accept_decay ** float(i)))
        if p >= 1.0 or rng.random() < p:
            metrics.mtp_pos_accepted[i] += 1
            accepted_draft += 1
            attempted += 1
        else:
            attempted += 1
            break

    total_draft = draft_len if draft_attempt_policy == "full" else attempted
    metrics.mtp_draft_tokens_total += total_draft
    metrics.mtp_draft_tokens_accepted += accepted_draft
    metrics.mtp_draft_tokens_rejected += (total_draft - accepted_draft)
    if accepted_draft == draft_len:
        metrics.mtp_bonus_tokens += 1
        return(draft_len + 1)
    return(accepted_draft + 1)


def _record_mtp_accept_len(cfg: SimConfig, metrics: SimMetrics, accept_len: int, draft_attempt_policy: str) -> None:
    if cfg.mtp_draft_len <= 0:
        return
    draft_len = cfg.mtp_draft_len
    if accept_len < 1:
        raise RuntimeError("accept_len must be >= 1")
    if accept_len > (draft_len + 1):
        raise RuntimeError("accept_len must be <= draft_len + 1")

    accepted_draft = (accept_len - 1)
    attempted = accepted_draft
    if accept_len <= draft_len:
        attempted += 1
    if attempted > draft_len:
        attempted = draft_len

    for i in range(attempted):
        metrics.mtp_pos_attempted[i] += 1
        if i < accepted_draft:
            metrics.mtp_pos_accepted[i] += 1

    total_draft = draft_len if draft_attempt_policy == "full" else attempted
    metrics.mtp_draft_tokens_total += total_draft
    metrics.mtp_draft_tokens_accepted += accepted_draft
    metrics.mtp_draft_tokens_rejected += (total_draft - accepted_draft)
    if accept_len == (draft_len + 1):
        metrics.mtp_bonus_tokens += 1


def _choose_mtp_accept_len(cfg: SimConfig, rng: random.Random, metrics: SimMetrics, route: TokenRoute, draft_attempt_policy: str) -> int:
    if cfg.mtp_draft_len <= 0:
        return(1)
    if route.mtp_accept_len is not None:
        accept_len = int(route.mtp_accept_len)
        if accept_len < 1 or accept_len > (cfg.mtp_draft_len + 1):
            raise ValueError("trace route mtp_accept_len out of range for configured mtp_draft_len")
        return(accept_len)
    if route.accepted_mtp is not None:
        accept_len = (int(route.accepted_mtp) + 1)
        if accept_len < 1 or accept_len > (cfg.mtp_draft_len + 1):
            raise ValueError("trace route accepted_mtp out of range for configured mtp_draft_len")
        return(accept_len)
    if route.rejected_mtp is not None:
        accept_len = ((cfg.mtp_draft_len - int(route.rejected_mtp)) + 1)
        if accept_len < 1 or accept_len > (cfg.mtp_draft_len + 1):
            raise ValueError("trace route rejected_mtp out of range for configured mtp_draft_len")
        return(accept_len)
    return(_sample_mtp_accept_len(cfg, rng, metrics, draft_attempt_policy))


def _mtp_attempted_draft_len(draft_len: int, accept_len: int) -> int:
    if draft_len <= 0:
        return(0)
    if accept_len < 1:
        return(0)
    if accept_len >= (draft_len + 1):
        return(draft_len)
    return(min(draft_len, accept_len))


def run_simulation(cfg: SimConfig, trace: Sequence[TokenRoute], token_states_out: Optional[List[TokenState]] = None) -> SimMetrics:
    if cfg.num_experts <= 0:
        raise ValueError("num_experts must be > 0")
    if cfg.expert_parallelism <= 0:
        raise ValueError("expert_parallelism must be > 0")
    if cfg.expert_queue_max <= 0:
        raise ValueError("expert_queue_max must be > 0")
    if cfg.expert_queue_reserve_interactive < 0:
        raise ValueError("expert_queue_reserve_interactive must be >= 0")
    if cfg.expert_queue_reserve_interactive > cfg.expert_queue_max:
        raise ValueError("expert_queue_reserve_interactive must be <= expert_queue_max")
    if cfg.service_ms <= 0.0 and cfg.service_per_task_ms < 0.0:
        raise ValueError("service_ms must be > 0")
    if cfg.service_base_ms < 0.0:
        raise ValueError("service_base_ms must be >= 0")
    if cfg.service_per_task_ms < -1.0:
        raise ValueError("service_per_task_ms must be >= -1")
    if cfg.batch_max_interactive <= 0:
        raise ValueError("batch_max_interactive must be > 0")
    if cfg.batch_max_batch <= 0:
        raise ValueError("batch_max_batch must be > 0")
    if cfg.batch_wait_interactive_ms < 0.0:
        raise ValueError("batch_wait_interactive_ms must be >= 0")
    if cfg.batch_wait_batch_ms < 0.0:
        raise ValueError("batch_wait_batch_ms must be >= 0")
    if _service_time_ms(cfg, 1) <= 0.0:
        raise ValueError("service model must produce >0ms for batch_size=1")
    if cfg.starvation_ms <= 0.0:
        raise ValueError("starvation_ms must be > 0")
    if cfg.hi_burst < 0:
        raise ValueError("hi_burst must be >= 0")
    if cfg.promote_ms < 0.0:
        raise ValueError("promote_ms must be >= 0")

    k_mode = cfg.k_mode.strip().lower()
    if k_mode not in ("controller", "trace"):
        raise ValueError("k_mode must be 'controller' or 'trace'")

    k_signal = cfg.k_signal.strip().lower()
    if k_signal not in ("global", "candidates", "class"):
        raise ValueError("k_signal must be 'global', 'candidates', or 'class'")

    pending_units = cfg.pending_units.strip().lower()
    if pending_units not in ("tasks", "work"):
        raise ValueError("pending_units must be 'tasks' or 'work'")

    backpressure_units = cfg.backpressure_units.strip().lower()
    if backpressure_units not in ("tasks", "work"):
        raise ValueError("backpressure_units must be 'tasks' or 'work'")

    k_scope = cfg.k_scope.strip().lower()
    if k_scope not in ("token", "layer"):
        raise ValueError("k_scope must be 'token' or 'layer'")

    admit_policy = cfg.admit_policy.strip().lower()
    if admit_policy not in ("ordered", "least_pending", "score_desc"):
        raise ValueError("admit_policy must be 'ordered', 'least_pending', or 'score_desc'")

    if cfg.pending_hist_max_depth < 0:
        raise ValueError("pending_hist_max_depth must be >= 0")

    if cfg.adaptive_k.k_min_interactive <= 0 or cfg.adaptive_k.k_max_interactive <= 0:
        raise ValueError("k_min_interactive and k_max_interactive must be > 0")
    if cfg.adaptive_k.k_min_batch <= 0 or cfg.adaptive_k.k_max_batch <= 0:
        raise ValueError("k_min_batch and k_max_batch must be > 0")
    if cfg.adaptive_k.k_min_interactive > cfg.adaptive_k.k_max_interactive:
        raise ValueError("k_min_interactive must be <= k_max_interactive")
    if cfg.adaptive_k.k_min_batch > cfg.adaptive_k.k_max_batch:
        raise ValueError("k_min_batch must be <= k_max_batch")
    if cfg.adaptive_k.ema_alpha <= 0.0 or cfg.adaptive_k.ema_alpha > 1.0:
        raise ValueError("ema_alpha must be within (0,1]")
    if cfg.adaptive_k.update_ms < 0.0:
        raise ValueError("update_ms must be >= 0")
    if cfg.adaptive_k.k_slew < 0:
        raise ValueError("k_slew must be >= 0")
    if cfg.sla_interactive_ms < 0.0:
        raise ValueError("sla_interactive_ms must be >= 0")
    if cfg.sla_batch_ms < 0.0:
        raise ValueError("sla_batch_ms must be >= 0")
    if cfg.sim_seed < 0:
        raise ValueError("sim_seed must be >= 0")
    if cfg.mtp_draft_len < 0:
        raise ValueError("mtp_draft_len must be >= 0")
    if cfg.mtp_draft_len > 0:
        mtp_draft_attempt_policy = cfg.mtp_draft_attempt_policy.strip().lower()
        if mtp_draft_attempt_policy not in ("full", "stop_at_reject"):
            raise ValueError("mtp_draft_attempt_policy must be 'full' or 'stop_at_reject'")
        if cfg.mtp_accept_prob < 0.0 or cfg.mtp_accept_prob > 1.0:
            raise ValueError("mtp_accept_prob must be within [0,1]")
        if cfg.mtp_accept_decay <= 0.0:
            raise ValueError("mtp_accept_decay must be > 0")
        if cfg.mtp_draft_cost_scale <= 0.0:
            raise ValueError("mtp_draft_cost_scale must be > 0")
        if cfg.mtp_verify_per_draft_cost_scale < 0.0:
            raise ValueError("mtp_verify_per_draft_cost_scale must be >= 0")
    else:
        mtp_draft_attempt_policy = "full"

    _validate_trace_expert_ids(trace, cfg.num_experts)

    for route in trace:
        if route.cost_scale is not None and float(route.cost_scale) <= 0.0:
            raise ValueError("trace route cost_scale must be > 0")
        if route.k is not None and route.k <= 0:
            raise ValueError("trace route k must be > 0")
        if route.layers is not None and route.scores is not None:
            raise ValueError("trace route scores must be per-layer when layers are present")
        if route.layers is None and route.scores is not None and len(route.scores) != len(route.candidates):
            raise ValueError("trace route scores must have same length as candidates")
        if route.layers is None and admit_policy == "score_desc" and route.scores is None:
            raise ValueError("admit_policy score_desc requires scores on every trace route")
        if (route.mtp_accept_len is not None or route.accepted_mtp is not None or route.rejected_mtp is not None) and cfg.mtp_draft_len <= 0:
            raise ValueError("trace route mtp fields require mtp_draft_len > 0")
        if route.accepted_mtp is not None and route.rejected_mtp is not None:
            if (route.accepted_mtp + route.rejected_mtp) != cfg.mtp_draft_len:
                raise ValueError("trace route accepted_mtp + rejected_mtp must equal mtp_draft_len")

        layers = _route_layers(route)
        if k_mode == "trace" and route.k is None:
            if any(lr.k is None for lr in layers):
                raise ValueError("k_mode trace requires per-route k or per-layer k for every layer in the trace")
        union: List[int] = []
        seen_union: set[int] = set()
        for lr in layers:
            if len(lr.candidates) == 0:
                raise ValueError("trace route candidates must be non-empty")
            if lr.k is not None and lr.k <= 0:
                raise ValueError("trace route k must be > 0")
            if lr.k is not None and lr.k > len(lr.candidates):
                raise ValueError("trace route k must be <= len(candidates)")
            if lr.scores is not None and len(lr.scores) != len(lr.candidates):
                raise ValueError("trace route scores must have same length as candidates")
            if admit_policy == "score_desc" and lr.scores is None:
                raise ValueError("admit_policy score_desc requires scores on every trace layer")
            if lr.cost_scale is not None and float(lr.cost_scale) <= 0.0:
                raise ValueError("trace route layer cost_scale must be > 0")
            for expert_id in lr.candidates:
                if expert_id < 0 or expert_id >= cfg.num_experts:
                    raise ValueError("trace route has expert_id out of range")
                if expert_id not in seen_union:
                    union.append(expert_id)
                    seen_union.add(expert_id)

        if len(union) == 0:
            raise ValueError("trace route candidates must be non-empty")
        if route.k is not None and route.k > len(union):
            raise ValueError("trace route k must be <= len(candidates)")

    experts: List[ExpertQueue] = [ExpertQueue() for _ in range(cfg.num_experts)]
    tokens: Dict[int, TokenState] = {}
    hist_len = 0
    if cfg.pending_hist_max_depth > 0:
        hist_len = min(cfg.pending_hist_max_depth, cfg.expert_queue_max) + 1
    metrics = SimMetrics(
        num_tokens=len(trace),
        k_mode=k_mode,
        pending_units=pending_units,
        backpressure_units=backpressure_units,
        tasks_started_per_expert=[0 for _ in range(cfg.num_experts)],
        starved_tasks_started_per_expert=[0 for _ in range(cfg.num_experts)],
        max_task_queue_wait_ms_per_expert=[0.0 for _ in range(cfg.num_experts)],
        max_pending_per_expert=[0 for _ in range(cfg.num_experts)],
        mean_pending_per_expert=[0.0 for _ in range(cfg.num_experts)],
        max_pending_work_per_expert=[0.0 for _ in range(cfg.num_experts)],
        mean_pending_work_per_expert=[0.0 for _ in range(cfg.num_experts)],
        mean_utilization_per_expert=[0.0 for _ in range(cfg.num_experts)],
        saturated_time_frac_per_expert=[0.0 for _ in range(cfg.num_experts)],
        pending_depth_hist=[0.0 for _ in range(hist_len)] if hist_len != 0 else [],
        pending_depth_hist_overflow=0.0,
        hi_queue_depth_hist=[0.0 for _ in range(hist_len)] if hist_len != 0 else [],
        hi_queue_depth_hist_overflow=0.0,
        lo_queue_depth_hist=[0.0 for _ in range(hist_len)] if hist_len != 0 else [],
        lo_queue_depth_hist_overflow=0.0,
        pending_work_depth_hist=[0.0 for _ in range(hist_len)] if hist_len != 0 else [],
        pending_work_depth_hist_overflow=0.0,
        hi_queue_work_depth_hist=[0.0 for _ in range(hist_len)] if hist_len != 0 else [],
        hi_queue_work_depth_hist_overflow=0.0,
        lo_queue_work_depth_hist=[0.0 for _ in range(hist_len)] if hist_len != 0 else [],
        lo_queue_work_depth_hist_overflow=0.0,
        pending_depth_hist_mtp_draft=[0.0 for _ in range(hist_len)] if hist_len != 0 else [],
        pending_depth_hist_mtp_draft_overflow=0.0,
        pending_depth_hist_mtp_verify=[0.0 for _ in range(hist_len)] if hist_len != 0 else [],
        pending_depth_hist_mtp_verify_overflow=0.0,
    )
    rng = random.Random(cfg.sim_seed)
    if cfg.mtp_draft_len > 0:
        metrics.mtp_verify_steps = len(trace)
        metrics.mtp_draft_len = cfg.mtp_draft_len
        metrics.mtp_accept_prob = cfg.mtp_accept_prob
        metrics.mtp_accept_decay = cfg.mtp_accept_decay
        metrics.mtp_draft_attempt_policy = mtp_draft_attempt_policy
        metrics.mtp_pos_attempted = [0 for _ in range(cfg.mtp_draft_len)]
        metrics.mtp_pos_accepted = [0 for _ in range(cfg.mtp_draft_len)]

    k_ctrl_token: Dict[LatencyClass, KControllerState] = {LatencyClass.INTERACTIVE: KControllerState(), LatencyClass.BATCH: KControllerState()}
    k_ctrl_layer: Dict[Tuple[LatencyClass, int], KControllerState] = {}

    # Time-weighted pending depth: integral pending(t) dt / makespan.
    pending_area: List[float] = [0.0 for _ in range(cfg.num_experts)]
    pending_work_area: List[float] = [0.0 for _ in range(cfg.num_experts)]
    inflight_area: List[float] = [0.0 for _ in range(cfg.num_experts)]
    saturated_area: List[float] = [0.0 for _ in range(cfg.num_experts)]
    last_t_ms = 0.0
    last_pending: List[int] = [0 for _ in range(cfg.num_experts)]
    last_pending_work: List[float] = [0.0 for _ in range(cfg.num_experts)]
    last_hi_queue: List[int] = [0 for _ in range(cfg.num_experts)]
    last_lo_queue: List[int] = [0 for _ in range(cfg.num_experts)]
    last_hi_queue_work: List[float] = [0.0 for _ in range(cfg.num_experts)]
    last_lo_queue_work: List[float] = [0.0 for _ in range(cfg.num_experts)]
    last_inflight: List[int] = [0 for _ in range(cfg.num_experts)]
    last_saturated: List[int] = [0 for _ in range(cfg.num_experts)]
    last_pending_mtp_draft: List[int] = [0 for _ in range(cfg.num_experts)]
    last_pending_mtp_verify: List[int] = [0 for _ in range(cfg.num_experts)]

    def integrate_areas(now_ms: float) -> None:
        nonlocal last_t_ms
        dt = (now_ms - last_t_ms)
        if dt < 0.0:
            raise RuntimeError("time went backwards")
        if dt != 0.0:
            for e in range(cfg.num_experts):
                pending_area[e] += (float(last_pending[e]) * dt)
                pending_work_area[e] += (float(last_pending_work[e]) * dt)
                inflight_area[e] += (float(last_inflight[e]) * dt)
                saturated_area[e] += (float(last_saturated[e]) * dt)
                if hist_len != 0:
                    depth = last_pending[e]
                    if depth >= hist_len:
                        metrics.pending_depth_hist_overflow += dt
                    else:
                        metrics.pending_depth_hist[depth] += dt
                    hi_depth = last_hi_queue[e]
                    if hi_depth >= hist_len:
                        metrics.hi_queue_depth_hist_overflow += dt
                    else:
                        metrics.hi_queue_depth_hist[hi_depth] += dt
                    lo_depth = last_lo_queue[e]
                    if lo_depth >= hist_len:
                        metrics.lo_queue_depth_hist_overflow += dt
                    else:
                        metrics.lo_queue_depth_hist[lo_depth] += dt
                    work_depth = int(math.floor(float(last_pending_work[e])))
                    if work_depth >= hist_len:
                        metrics.pending_work_depth_hist_overflow += dt
                    else:
                        metrics.pending_work_depth_hist[work_depth] += dt
                    hi_work_depth = int(math.floor(float(last_hi_queue_work[e])))
                    if hi_work_depth >= hist_len:
                        metrics.hi_queue_work_depth_hist_overflow += dt
                    else:
                        metrics.hi_queue_work_depth_hist[hi_work_depth] += dt
                    lo_work_depth = int(math.floor(float(last_lo_queue_work[e])))
                    if lo_work_depth >= hist_len:
                        metrics.lo_queue_work_depth_hist_overflow += dt
                    else:
                        metrics.lo_queue_work_depth_hist[lo_work_depth] += dt
                    d_draft = last_pending_mtp_draft[e]
                    if d_draft >= hist_len:
                        metrics.pending_depth_hist_mtp_draft_overflow += dt
                    else:
                        metrics.pending_depth_hist_mtp_draft[d_draft] += dt
                    d_verify = last_pending_mtp_verify[e]
                    if d_verify >= hist_len:
                        metrics.pending_depth_hist_mtp_verify_overflow += dt
                    else:
                        metrics.pending_depth_hist_mtp_verify[d_verify] += dt
        last_t_ms = now_ms

    def snapshot_state() -> None:
        for e in range(cfg.num_experts):
            last_pending[e] = experts[e].pending()
            last_pending_work[e] = experts[e].pending_work()
            last_hi_queue[e] = len(experts[e].hi)
            last_lo_queue[e] = len(experts[e].lo)
            last_hi_queue_work[e] = float(experts[e].pending_work_hi)
            last_lo_queue_work[e] = float(experts[e].pending_work_lo)
            last_inflight[e] = experts[e].in_flight
            if backpressure_units == "work":
                last_saturated[e] = 1 if last_pending_work[e] >= float(cfg.expert_queue_max) else 0
            else:
                last_saturated[e] = 1 if last_pending[e] >= cfg.expert_queue_max else 0
            last_pending_mtp_draft[e] = experts[e].pending_mtp_draft()
            last_pending_mtp_verify[e] = experts[e].pending_mtp_verify()
            if last_pending[e] > metrics.max_pending_per_expert[e]:
                metrics.max_pending_per_expert[e] = last_pending[e]
            if last_pending_work[e] > metrics.max_pending_work_per_expert[e]:
                metrics.max_pending_work_per_expert[e] = float(last_pending_work[e])

    evq: List[Event] = []
    seq_ref = [0]

    for tid, route in enumerate(trace):
        seq_ref[0] += 1
        heapq.heappush(
            evq,
            Event(
                t_ms=route.t_ms,
                kind=EventKind.TOKEN_ARRIVAL,
                seq=seq_ref[0],
                expert_id=-1,
                tasks=(Task(token_id=tid, cls=route.cls, enqueue_ms=route.t_ms),),
            ),
        )
        tokens[tid] = TokenState(
            cls=route.cls,
            submit_ms=route.t_ms,
            chosen_k=0,
            remaining=0,
            trace_decode_ms=route.decode_ms,
            trace_kv_tokens=route.kv_tokens,
            trace_expert_batch_size=route.expert_batch_size,
        )

    now_ms = 0.0
    snapshot_state()

    if cfg.mtp_draft_len > 0:
        metrics.mtp_accept_len_per_step = [0 for _ in range(len(trace))]
        metrics.mtp_draft_attempt_len_per_step = [0 for _ in range(len(trace))]
    metrics.dflash_steps = 0
    metrics.dflash_output_tokens = 0
    metrics.dflash_draft_tokens_total = 0
    metrics.dflash_draft_tokens_accepted = 0
    metrics.dflash_draft_tokens_rejected = 0
    metrics.dflash_bonus_tokens = 0
    metrics.dflash_accept_len_per_step = [-1 for _ in range(len(trace))]
    metrics.dflash_accepted_per_step = [-1 for _ in range(len(trace))]
    metrics.dflash_rejected_per_step = [-1 for _ in range(len(trace))]

    def _token_first_admit(tid: int) -> None:
        ts = tokens[tid]
        if ts.admitted_any:
            return
        ts.admitted_any = True
        metrics.admitted_tokens += 1
        if ts.cls == LatencyClass.INTERACTIVE:
            metrics.admitted_tokens_interactive += 1
            ts.metrics_slot = len(metrics.effective_k_interactive)
            metrics.effective_k_interactive.append(0)
            metrics.effective_k_total_interactive.append(0)
        else:
            metrics.admitted_tokens_batch += 1
            ts.metrics_slot = len(metrics.effective_k_batch)
            metrics.effective_k_batch.append(0)
            metrics.effective_k_total_batch.append(0)

    def _account_token_effective_k(tid: int) -> None:
        ts = tokens[tid]
        if not ts.admitted_any:
            return
        if ts.metrics_slot < 0:
            raise RuntimeError("token metrics_slot unset")
        if ts.cls == LatencyClass.INTERACTIVE:
            metrics.effective_k_interactive[ts.metrics_slot] = ts.admitted_verify_layer0
            metrics.effective_k_total_interactive[ts.metrics_slot] = ts.admitted_verify_total
        else:
            metrics.effective_k_batch[ts.metrics_slot] = ts.admitted_verify_layer0
            metrics.effective_k_total_batch[ts.metrics_slot] = ts.admitted_verify_total

        if ts.desired_verify_layer0 > 0 and ts.admitted_verify_layer0 < ts.desired_verify_layer0:
            metrics.partial_admit_tokens += 1
            if ts.cls == LatencyClass.INTERACTIVE:
                metrics.partial_admit_tokens_interactive += 1
            else:
                metrics.partial_admit_tokens_batch += 1
        if ts.partial_any_layer:
            metrics.partial_admit_any_layer_tokens += 1
            if ts.cls == LatencyClass.INTERACTIVE:
                metrics.partial_admit_any_layer_tokens_interactive += 1
            else:
                metrics.partial_admit_any_layer_tokens_batch += 1

    def _maybe_account_token_mtp(tid: int) -> None:
        if cfg.mtp_draft_len <= 0:
            return
        ts = tokens[tid]
        if ts.mtp_accounted:
            return
        if not ts.admitted_any:
            ts.mtp_accounted = True
            return
        metrics.mtp_accept_len_per_step[tid] = ts.mtp_accept_len
        metrics.mtp_draft_attempt_len_per_step[tid] = ts.mtp_draft_attempt_len
        metrics.mtp_output_tokens += ts.mtp_accept_len
        route = trace[tid]
        if route.mtp_accept_len is not None or route.accepted_mtp is not None or route.rejected_mtp is not None:
            _record_mtp_accept_len(cfg, metrics, ts.mtp_accept_len, mtp_draft_attempt_policy)
        ts.mtp_accounted = True

    def _maybe_account_token_dflash(tid: int) -> None:
        route = trace[tid]
        if route.dflash_accept_len is None and route.accepted_dflash is None and route.rejected_dflash is None:
            return
        ts = tokens[tid]
        if not ts.admitted_any:
            return
        if metrics.dflash_accept_len_per_step[tid] != -1 or metrics.dflash_accepted_per_step[tid] != -1 or metrics.dflash_rejected_per_step[tid] != -1:
            return
        metrics.dflash_steps += 1
        dal = _derive_dflash_accept_len(route)
        if dal is not None:
            metrics.dflash_accept_len_per_step[tid] = int(dal)
            metrics.dflash_output_tokens += int(dal)
            metrics.dflash_bonus_tokens += max(0, int(dal) - 1)
        if route.accepted_dflash is not None:
            metrics.dflash_accepted_per_step[tid] = int(route.accepted_dflash)
            metrics.dflash_draft_tokens_accepted += int(route.accepted_dflash)
        if route.rejected_dflash is not None:
            metrics.dflash_rejected_per_step[tid] = int(route.rejected_dflash)
            metrics.dflash_draft_tokens_rejected += int(route.rejected_dflash)
        if route.accepted_dflash is not None and route.rejected_dflash is not None:
            metrics.dflash_draft_tokens_total += (int(route.accepted_dflash) + int(route.rejected_dflash))

    def _enqueue_stage(now_ms: float, tid: int, stage: StagePlan) -> int:
        route = trace[tid]
        admitted = 0
        pending_limit = _expert_queue_pending_limit_units(cfg, route.cls, backpressure_units)
        for expert_id in _candidate_order_for_layer(admit_policy, experts, stage.candidates, stage.scores):
            if admitted >= stage.k:
                break
            eq = experts[expert_id]
            if backpressure_units == "work":
                pending_now = float(eq.pending_work())
            else:
                pending_now = float(eq.pending())
            if pending_now >= float(pending_limit):
                metrics.dropped_tasks_backpressure += 1
                if route.cls == LatencyClass.INTERACTIVE:
                    metrics.dropped_tasks_backpressure_interactive += 1
                else:
                    metrics.dropped_tasks_backpressure_batch += 1
                tokens[tid].dropped_tasks_backpressure += 1
                continue
            task = Task(token_id=tid, cls=route.cls, enqueue_ms=now_ms, cost_scale=stage.cost_scale, mtp_phase=stage.mtp_phase)
            if route.cls == LatencyClass.INTERACTIVE:
                eq.hi.append(task)
                eq.pending_work_hi += float(task.cost_scale)
            else:
                eq.lo.append(task)
                eq.pending_work_lo += float(task.cost_scale)
            if task.mtp_phase == MtpPhase.DRAFT:
                eq.queued_tasks_mtp_draft += 1
            elif task.mtp_phase == MtpPhase.VERIFY:
                eq.queued_tasks_mtp_verify += 1
            tokens[tid].remaining += 1
            tokens[tid].admitted_tasks_total += 1
            metrics.admitted_tasks += 1
            if route.cls == LatencyClass.INTERACTIVE:
                metrics.admitted_tasks_interactive += 1
            else:
                metrics.admitted_tasks_batch += 1
            admitted += 1
            _start_tasks(now_ms, cfg, eq, expert_id, evq, seq_ref, metrics)
        return(admitted)

    def _finish_token(now_ms: float, tid: int) -> None:
        ts = tokens[tid]
        if ts.done_ms is not None:
            return
        if not ts.admitted_any:
            metrics.dropped_tokens_backpressure += 1
            if ts.cls == LatencyClass.INTERACTIVE:
                metrics.dropped_tokens_backpressure_interactive += 1
            else:
                metrics.dropped_tokens_backpressure_batch += 1
            ts.output_len = 0
            _maybe_account_token_mtp(tid)
            _maybe_account_token_dflash(tid)
            ts.done_ms = now_ms
            return

        _account_token_effective_k(tid)
        _maybe_account_token_mtp(tid)
        _maybe_account_token_dflash(tid)
        ts.done_ms = now_ms
        lat_ms = (now_ms - ts.submit_ms)
        if ts.cls == LatencyClass.INTERACTIVE:
            metrics.token_lat_ms_interactive.append(lat_ms)
            if ts.trace_decode_ms is not None:
                metrics.trace_decode_ms_interactive.append(float(ts.trace_decode_ms))
                metrics.trace_decode_error_ms_interactive.append(float(lat_ms - float(ts.trace_decode_ms)))
            if ts.trace_kv_tokens is not None:
                metrics.trace_kv_tokens_interactive.append(float(ts.trace_kv_tokens))
            if ts.trace_expert_batch_size is not None:
                metrics.trace_expert_batch_size_interactive.append(float(ts.trace_expert_batch_size))
            if cfg.sla_interactive_ms > 0.0 and lat_ms > cfg.sla_interactive_ms:
                metrics.token_sla_violations_interactive += 1
        else:
            metrics.token_lat_ms_batch.append(lat_ms)
            if ts.trace_decode_ms is not None:
                metrics.trace_decode_ms_batch.append(float(ts.trace_decode_ms))
                metrics.trace_decode_error_ms_batch.append(float(lat_ms - float(ts.trace_decode_ms)))
            if ts.trace_kv_tokens is not None:
                metrics.trace_kv_tokens_batch.append(float(ts.trace_kv_tokens))
            if ts.trace_expert_batch_size is not None:
                metrics.trace_expert_batch_size_batch.append(float(ts.trace_expert_batch_size))
            if cfg.sla_batch_ms > 0.0 and lat_ms > cfg.sla_batch_ms:
                metrics.token_sla_violations_batch += 1
        if ts.output_len > 0:
            if ts.cls == LatencyClass.INTERACTIVE:
                metrics.output_token_lat_ms_interactive.extend([lat_ms for _ in range(ts.output_len)])
            else:
                metrics.output_token_lat_ms_batch.extend([lat_ms for _ in range(ts.output_len)])

    def _advance_token(now_ms: float, tid: int) -> None:
        ts = tokens[tid]
        if ts.stages is None:
            return

        while ts.remaining == 0 and ts.done_ms is None and ts.stage_idx < ts.stage_total:
            stage = ts.stages[ts.stage_idx]
            desired_stage = min(stage.k, len(stage.candidates))
            if desired_stage > 0:
                metrics.stages_total += 1
                if ts.cls == LatencyClass.INTERACTIVE:
                    metrics.stages_total_interactive += 1
                else:
                    metrics.stages_total_batch += 1
                if stage.is_verify:
                    metrics.stages_total_verify += 1
                else:
                    metrics.stages_total_draft += 1
            admitted = _enqueue_stage(now_ms, tid, stage)
            if admitted == 0 and desired_stage > 0:
                metrics.skipped_stages_backpressure += 1
                if ts.cls == LatencyClass.INTERACTIVE:
                    metrics.skipped_stages_backpressure_interactive += 1
                else:
                    metrics.skipped_stages_backpressure_batch += 1
                if stage.is_verify:
                    metrics.skipped_stages_backpressure_verify += 1
                else:
                    metrics.skipped_stages_backpressure_draft += 1
                ts.skipped_stages_backpressure += 1
                if stage.is_verify:
                    ts.skipped_stages_backpressure_verify += 1
                else:
                    ts.skipped_stages_backpressure_draft += 1
            if admitted != 0:
                _token_first_admit(tid)
            if stage.is_verify:
                desired_layer = min(stage.k, len(stage.candidates))
                ts.admitted_verify_total += admitted
                if admitted < desired_layer:
                    ts.partial_any_layer = True
                if stage.layer_index == 0:
                    ts.admitted_verify_layer0 = admitted
                    ts.desired_verify_layer0 = desired_layer
                    if cfg.mtp_draft_len > 0 and desired_layer > 0 and admitted == 0:
                        metrics.mtp_verify_layer0_skipped_backpressure += 1
                        ts.mtp_verify_layer0_skipped_backpressure = True
                        if ts.mtp_accept_len > 1:
                            metrics.mtp_accept_len_clamped_backpressure += 1
                            ts.mtp_accept_len = 1
                            ts.output_len = 1
                            ts.mtp_accept_len_clamped_backpressure = True
                    _maybe_account_token_mtp(tid)
            ts.stage_idx += 1
            if admitted != 0:
                return

        if ts.remaining == 0 and ts.done_ms is None and ts.stage_idx >= ts.stage_total:
            _finish_token(now_ms, tid)

    def controller_k_for_signal(cls: LatencyClass, cs: KControllerState, pending_signal: float) -> int:
        if cs.last_update_ms < 0.0:
            cs.ema_pending = pending_signal
        else:
            alpha = cfg.adaptive_k.ema_alpha
            cs.ema_pending = ((alpha * pending_signal) + ((1.0 - alpha) * cs.ema_pending))

        update = False
        if cs.k == 0:
            update = True
        elif cfg.adaptive_k.update_ms <= 0.0:
            update = True
        elif (now_ms - cs.last_update_ms) >= cfg.adaptive_k.update_ms:
            update = True

        if update:
            prev_k = cs.k
            k_target = choose_k(cfg.adaptive_k, cls, cs.ema_pending)
            if prev_k != 0 and cfg.adaptive_k.k_slew > 0:
                diff = (k_target - prev_k)
                if diff > cfg.adaptive_k.k_slew:
                    cs.k = (prev_k + cfg.adaptive_k.k_slew)
                elif diff < -cfg.adaptive_k.k_slew:
                    cs.k = (prev_k - cfg.adaptive_k.k_slew)
                else:
                    cs.k = k_target
            else:
                cs.k = k_target
            cs.last_update_ms = now_ms
            if cls == LatencyClass.INTERACTIVE:
                metrics.k_updates_interactive += 1
                if prev_k != 0 and cs.k != prev_k:
                    metrics.k_changes_interactive += 1
            else:
                metrics.k_updates_batch += 1
                if prev_k != 0 and cs.k != prev_k:
                    metrics.k_changes_batch += 1
        return(cs.k)

    while len(evq) != 0:
        ev = heapq.heappop(evq)
        now_ms = ev.t_ms
        integrate_areas(now_ms)

        if ev.kind == EventKind.TOKEN_ARRIVAL:
            if ev.tasks is None or len(ev.tasks) != 1:
                raise RuntimeError("TOKEN_ARRIVAL missing task")
            tid = ev.tasks[0].token_id
            route = trace[tid]
            mtp_enabled = (cfg.mtp_draft_len > 0)

            layers = _route_layers(route)

            if pending_units == "work":
                if k_signal == "global":
                    pending_signal = float(max(experts[e].pending_work() for e in range(cfg.num_experts)))
                elif k_signal == "candidates":
                    pending_signal = float(max(experts[e].pending_work() for e in route.candidates))
                else:
                    pending_signal = float(max(experts[e].pending_work_for_queue(route.cls) for e in range(cfg.num_experts)))
            else:
                if k_signal == "global":
                    pending_signal = float(max(experts[e].pending() for e in range(cfg.num_experts)))
                elif k_signal == "candidates":
                    pending_signal = float(max(experts[e].pending() for e in route.candidates))
                else:
                    pending_signal = float(max(expert_pending_for_class(experts[e], route.cls) for e in range(cfg.num_experts)))

            if route.cls == LatencyClass.INTERACTIVE:
                metrics.pending_signal_interactive.append(pending_signal)
            else:
                metrics.pending_signal_batch.append(pending_signal)

            layer_ks: List[int] = []
            if k_mode == "trace":
                for li, lr in enumerate(layers):
                    if lr.k is not None:
                        layer_ks.append(int(lr.k))
                        continue
                    if route.k is not None:
                        layer_ks.append(int(route.k))
                        continue
                    if layers[0].k is None:
                        raise RuntimeError("k_mode trace requires per-route k or per-layer k for every layer in the trace")
                    layer_ks.append(int(layers[0].k))
            else:
                if k_scope == "token":
                    cs = k_ctrl_token[route.cls]
                    k = controller_k_for_signal(route.cls, cs, pending_signal)
                    layer_ks = [k for _ in range(len(layers))]
                else:
                    for li, lr in enumerate(layers):
                        if pending_units == "work":
                            if k_signal == "global":
                                layer_pending_signal = float(max(experts[e].pending_work() for e in range(cfg.num_experts)))
                            elif k_signal == "candidates":
                                layer_pending_signal = float(max(experts[e].pending_work() for e in lr.candidates))
                            else:
                                layer_pending_signal = float(max(experts[e].pending_work_for_queue(route.cls) for e in range(cfg.num_experts)))
                        else:
                            if k_signal == "global":
                                layer_pending_signal = float(max(experts[e].pending() for e in range(cfg.num_experts)))
                            elif k_signal == "candidates":
                                layer_pending_signal = float(max(experts[e].pending() for e in lr.candidates))
                            else:
                                layer_pending_signal = float(max(expert_pending_for_class(experts[e], route.cls) for e in range(cfg.num_experts)))
                        cs = k_ctrl_layer.get((route.cls, li))
                        if cs is None:
                            cs = KControllerState()
                            k_ctrl_layer[(route.cls, li)] = cs
                        layer_ks.append(controller_k_for_signal(route.cls, cs, layer_pending_signal))

            k = layer_ks[0] if len(layer_ks) != 0 else 0
            tokens[tid].chosen_k = k
            tokens[tid].remaining = 0
            if route.cls == LatencyClass.INTERACTIVE:
                metrics.chosen_k_interactive.append(k)
            else:
                metrics.chosen_k_batch.append(k)

            desired_total = 0
            for li, lr in enumerate(layers):
                if li < len(layer_ks):
                    desired_total += min(layer_ks[li], len(lr.candidates))
            if route.cls == LatencyClass.INTERACTIVE:
                metrics.chosen_k_total_interactive.append(desired_total)
            else:
                metrics.chosen_k_total_batch.append(desired_total)

            accept_len = 1
            draft_attempt_len = 0
            if mtp_enabled:
                accept_len = _choose_mtp_accept_len(cfg, rng, metrics, route, mtp_draft_attempt_policy)
                draft_attempt_len = cfg.mtp_draft_len
                if mtp_draft_attempt_policy == "stop_at_reject":
                    draft_attempt_len = _mtp_attempted_draft_len(cfg.mtp_draft_len, accept_len)

            ts = tokens[tid]
            ts.remaining = 0
            ts.stage_idx = 0
            ts.stage_total = 0
            ts.stages = None
            ts.admitted_any = False
            ts.metrics_slot = -1
            ts.admitted_verify_layer0 = 0
            ts.desired_verify_layer0 = 0
            ts.admitted_verify_total = 0
            ts.partial_any_layer = False
            ts.mtp_accept_len = accept_len
            ts.mtp_draft_attempt_len = draft_attempt_len
            ts.mtp_accounted = False
            ts.output_len = accept_len if mtp_enabled else 1
            ts.mtp_verify_layer0_skipped_backpressure = False
            ts.mtp_accept_len_clamped_backpressure = False

            micro_tokens = (draft_attempt_len + 1) if mtp_enabled else 1
            layers = _route_layers(route)
            base_cost_scale = float(route.cost_scale) if route.cost_scale is not None else 1.0
            stage_plans: List[StagePlan] = []
            for micro_i in range(micro_tokens):
                is_verify = ((not mtp_enabled) or micro_i == draft_attempt_len)
                cost_scale = base_cost_scale
                mtp_phase = MtpPhase.NONE
                if mtp_enabled and micro_i < draft_attempt_len:
                    cost_scale *= cfg.mtp_draft_cost_scale
                    mtp_phase = MtpPhase.DRAFT
                elif mtp_enabled and micro_i == draft_attempt_len and cfg.mtp_verify_per_draft_cost_scale > 0.0:
                    cost_scale *= (1.0 + (cfg.mtp_verify_per_draft_cost_scale * float(draft_attempt_len)))
                    mtp_phase = MtpPhase.VERIFY
                elif mtp_enabled and micro_i == draft_attempt_len:
                    mtp_phase = MtpPhase.VERIFY

                for li, lr in enumerate(layers):
                    layer_cost_scale = float(lr.cost_scale) if lr.cost_scale is not None else 1.0
                    stage_cost_scale = (cost_scale * layer_cost_scale)
                    layer_k = layer_ks[li] if li < len(layer_ks) else k
                    if k_mode == "trace" and lr.k is not None:
                        layer_k = int(lr.k)
                    stage_plans.append(
                        StagePlan(
                            candidates=lr.candidates,
                            scores=lr.scores,
                            k=layer_k,
                            cost_scale=stage_cost_scale,
                            mtp_phase=mtp_phase,
                            is_verify=is_verify,
                            layer_index=li,
                        )
                    )

            ts.stages = tuple(stage_plans)
            ts.stage_total = len(stage_plans)
            _advance_token(now_ms, tid)

        elif ev.kind == EventKind.TASK_DONE:
            if ev.tasks is None or len(ev.tasks) == 0:
                raise RuntimeError("TASK_DONE missing tasks")
            if ev.expert_id < 0 or ev.expert_id >= cfg.num_experts:
                raise RuntimeError("TASK_DONE invalid expert_id")

            eq = experts[ev.expert_id]
            if eq.in_flight <= 0:
                raise RuntimeError("in_flight underflow")
            eq.in_flight -= 1
            if eq.in_flight_tasks < len(ev.tasks):
                raise RuntimeError("in_flight_tasks underflow")
            eq.in_flight_tasks -= len(ev.tasks)

            done_tasks_hi = 0
            done_tasks_lo = 0
            done_work_hi = 0.0
            done_work_lo = 0.0
            for task in ev.tasks:
                u = float(task.cost_scale)
                if task.served_hi:
                    done_tasks_hi += 1
                    done_work_hi += u
                else:
                    done_tasks_lo += 1
                    done_work_lo += u
            if eq.in_flight_tasks_hi < done_tasks_hi:
                raise RuntimeError("in_flight_tasks_hi underflow")
            if eq.in_flight_tasks_lo < done_tasks_lo:
                raise RuntimeError("in_flight_tasks_lo underflow")
            eq.in_flight_tasks_hi -= done_tasks_hi
            eq.in_flight_tasks_lo -= done_tasks_lo
            if eq.in_flight_work_hi < (done_work_hi - 1e-12):
                raise RuntimeError("in_flight_work_hi underflow")
            if eq.in_flight_work_lo < (done_work_lo - 1e-12):
                raise RuntimeError("in_flight_work_lo underflow")
            eq.in_flight_work_hi -= done_work_hi
            eq.in_flight_work_lo -= done_work_lo
            done_draft = 0
            done_verify = 0
            for task in ev.tasks:
                if task.mtp_phase == MtpPhase.DRAFT:
                    done_draft += 1
                elif task.mtp_phase == MtpPhase.VERIFY:
                    done_verify += 1
            if eq.in_flight_tasks_mtp_draft < done_draft:
                raise RuntimeError("in_flight_tasks_mtp_draft underflow")
            if eq.in_flight_tasks_mtp_verify < done_verify:
                raise RuntimeError("in_flight_tasks_mtp_verify underflow")
            eq.in_flight_tasks_mtp_draft -= done_draft
            eq.in_flight_tasks_mtp_verify -= done_verify

            for task in ev.tasks:
                tid = task.token_id
                if tid not in tokens:
                    raise RuntimeError("unknown token_id")
                ts = tokens[tid]
                if ts.remaining <= 0:
                    raise RuntimeError("token remaining underflow")
                ts.remaining -= 1
                if ts.remaining == 0 and ts.done_ms is None:
                    _advance_token(now_ms, tid)

            _start_tasks(now_ms, cfg, eq, ev.expert_id, evq, seq_ref, metrics)
        elif ev.kind == EventKind.EXPERT_WAKE:
            if ev.expert_id < 0 or ev.expert_id >= cfg.num_experts:
                raise RuntimeError("EXPERT_WAKE invalid expert_id")
            eq = experts[ev.expert_id]
            if eq.hi_wakeup_ms >= 0.0 and now_ms >= (eq.hi_wakeup_ms - 1e-12):
                eq.hi_wakeup_ms = -1.0
            if eq.lo_wakeup_ms >= 0.0 and now_ms >= (eq.lo_wakeup_ms - 1e-12):
                eq.lo_wakeup_ms = -1.0
            _start_tasks(now_ms, cfg, eq, ev.expert_id, evq, seq_ref, metrics)
        else:
            raise RuntimeError("unknown event kind")

        snapshot_state()

    makespan_ms = max((t.done_ms or 0.0) for t in tokens.values()) if len(tokens) != 0 else 0.0
    if makespan_ms <= 0.0:
        makespan_ms = 1.0
    metrics.makespan_ms = makespan_ms
    for e in range(cfg.num_experts):
        metrics.mean_pending_per_expert[e] = (pending_area[e] / makespan_ms)
        metrics.mean_pending_work_per_expert[e] = (pending_work_area[e] / makespan_ms)
        metrics.mean_utilization_per_expert[e] = (inflight_area[e] / (makespan_ms * float(cfg.expert_parallelism)))
        metrics.saturated_time_frac_per_expert[e] = (saturated_area[e] / makespan_ms)
    if token_states_out is not None:
        token_states_out.extend([tokens[i] for i in range(len(trace))])
    return(metrics)


def _gini_nonneg(xs: Sequence[float]) -> float:
    if len(xs) == 0:
        return(0.0)
    vals: List[float] = []
    for x in xs:
        v = float(x)
        vals.append(v if v > 0.0 else 0.0)
    vals.sort()
    s = float(sum(vals))
    if s <= 0.0:
        return(0.0)
    n = float(len(vals))
    cum = 0.0
    for i, x in enumerate(vals, 1):
        cum += (float(i) * float(x))
    g = ((2.0 * cum) / (n * s)) - ((n + 1.0) / n)
    if g < 0.0:
        return(0.0)
    if g > 1.0:
        return(1.0)
    return(float(g))


def compare_summary_jsonable(metrics: SimMetrics) -> Dict[str, float]:
    def _p_or_zero(xs: Sequence[float], p: float) -> float:
        if len(xs) == 0:
            return(0.0)
        xs_sorted = sorted(xs)
        x = (p * float(len(xs_sorted) - 1))
        i0 = int(math.floor(x))
        i1 = int(math.ceil(x))
        if i0 == i1:
            return(float(xs_sorted[i0]))
        frac = (x - float(i0))
        return(float(xs_sorted[i0]) * (1.0 - frac) + (float(xs_sorted[i1]) * frac))

    def _hist_int_percentile(hist_time_ms: Sequence[float], overflow_time_ms: float, p: float) -> int:
        if p <= 0.0:
            return(0)
        if p >= 1.0:
            if overflow_time_ms > 0.0:
                return(len(hist_time_ms))
            if len(hist_time_ms) == 0:
                return(0)
            return(len(hist_time_ms) - 1)
        total = float(sum(hist_time_ms)) + float(overflow_time_ms)
        if total <= 0.0:
            return(0)
        target = (p * total)
        acc = 0.0
        for d, t in enumerate(hist_time_ms):
            acc += float(t)
            if acc >= target:
                return(int(d))
        if overflow_time_ms > 0.0:
            return(len(hist_time_ms))
        if len(hist_time_ms) == 0:
            return(0)
        return(len(hist_time_ms) - 1)

    makespan_ms = metrics.makespan_ms
    token_tps = (float(metrics.num_tokens) * 1000.0 / makespan_ms) if makespan_ms > 0.0 else 0.0
    task_tps = (float(metrics.admitted_tasks) * 1000.0 / makespan_ms) if makespan_ms > 0.0 else 0.0
    output_tokens = float(metrics.mtp_output_tokens) if metrics.mtp_draft_len > 0 else float(metrics.admitted_tokens)
    output_tps = (output_tokens * 1000.0 / makespan_ms) if makespan_ms > 0.0 else 0.0
    dflash_steps = float(metrics.dflash_steps)
    dflash_output_tokens = float(metrics.dflash_output_tokens)
    dflash_output_tps = (dflash_output_tokens * 1000.0 / makespan_ms) if makespan_ms > 0.0 else 0.0
    dflash_bonus_tokens = float(metrics.dflash_bonus_tokens)
    dflash_accept_rate = (float(metrics.dflash_draft_tokens_accepted) / float(metrics.dflash_draft_tokens_total)) if metrics.dflash_draft_tokens_total > 0 else 0.0
    dropped = float(metrics.dropped_tokens_backpressure)
    denom = float(metrics.admitted_tokens + metrics.dropped_tokens_backpressure)
    drop_frac = (dropped / denom) if denom > 0.0 else 0.0
    service_per_output_token = (float(metrics.service_slot_ms_total) / output_tokens) if output_tokens > 0.0 else 0.0
    tasks_started_total = float(sum(metrics.tasks_started_per_expert)) if len(metrics.tasks_started_per_expert) != 0 else 0.0
    expert_tasks_started_gini = _gini_nonneg([float(v) for v in metrics.tasks_started_per_expert])
    expert_utilization_gini = _gini_nonneg([float(v) for v in metrics.mean_utilization_per_expert])
    expert_tasks_started_top1_frac = (
        (float(max(metrics.tasks_started_per_expert)) / tasks_started_total) if tasks_started_total > 0.0 and len(metrics.tasks_started_per_expert) != 0 else 0.0
    )
    starved_task_frac = (float(metrics.starved_tasks) / tasks_started_total) if tasks_started_total > 0.0 else 0.0
    starved_task_frac_interactive = (float(metrics.starved_tasks_interactive) / float(len(metrics.task_queue_wait_ms_interactive))) if len(metrics.task_queue_wait_ms_interactive) != 0 else 0.0
    starved_task_frac_batch = (float(metrics.starved_tasks_batch) / float(len(metrics.task_queue_wait_ms_batch))) if len(metrics.task_queue_wait_ms_batch) != 0 else 0.0
    starved_task_frac_mtp_draft = (float(metrics.starved_tasks_mtp_draft) / float(metrics.tasks_started_mtp_draft)) if metrics.tasks_started_mtp_draft > 0 else 0.0
    starved_task_frac_mtp_verify = (float(metrics.starved_tasks_mtp_verify) / float(metrics.tasks_started_mtp_verify)) if metrics.tasks_started_mtp_verify > 0 else 0.0
    partial_admit_frac = (float(metrics.partial_admit_tokens) / float(metrics.admitted_tokens)) if metrics.admitted_tokens > 0 else 0.0
    mtp_accept_rate = (float(metrics.mtp_draft_tokens_accepted) / float(metrics.mtp_draft_tokens_total)) if metrics.mtp_draft_tokens_total > 0 else 0.0
    mtp_service_slot_draft_frac = (float(metrics.service_slot_ms_mtp_draft) / float(metrics.service_slot_ms_total)) if metrics.service_slot_ms_total > 0.0 else 0.0
    mtp_service_slot_verify_frac = (float(metrics.service_slot_ms_mtp_verify) / float(metrics.service_slot_ms_total)) if metrics.service_slot_ms_total > 0.0 else 0.0
    dropped_interactive = float(metrics.dropped_tokens_backpressure_interactive)
    denom_interactive = float(metrics.admitted_tokens_interactive + metrics.dropped_tokens_backpressure_interactive)
    drop_frac_interactive = (dropped_interactive / denom_interactive) if denom_interactive > 0.0 else 0.0
    dropped_batch = float(metrics.dropped_tokens_backpressure_batch)
    denom_batch = float(metrics.admitted_tokens_batch + metrics.dropped_tokens_backpressure_batch)
    drop_frac_batch = (dropped_batch / denom_batch) if denom_batch > 0.0 else 0.0
    sla_violation_frac_interactive = (float(metrics.token_sla_violations_interactive) / float(len(metrics.token_lat_ms_interactive))) if len(metrics.token_lat_ms_interactive) != 0 else 0.0
    sla_violation_frac_batch = (float(metrics.token_sla_violations_batch) / float(len(metrics.token_lat_ms_batch))) if len(metrics.token_lat_ms_batch) != 0 else 0.0
    stages_total = float(metrics.stages_total)
    stages_total_interactive = float(metrics.stages_total_interactive)
    stages_total_batch = float(metrics.stages_total_batch)
    stages_total_verify = float(metrics.stages_total_verify)
    stages_total_draft = float(metrics.stages_total_draft)
    skipped_stages = float(metrics.skipped_stages_backpressure)
    skipped_stage_frac = (skipped_stages / stages_total) if stages_total > 0.0 else 0.0
    skipped_stage_frac_interactive = (float(metrics.skipped_stages_backpressure_interactive) / stages_total_interactive) if stages_total_interactive > 0.0 else 0.0
    skipped_stage_frac_batch = (float(metrics.skipped_stages_backpressure_batch) / stages_total_batch) if stages_total_batch > 0.0 else 0.0
    skipped_stage_frac_verify = (float(metrics.skipped_stages_backpressure_verify) / stages_total_verify) if stages_total_verify > 0.0 else 0.0
    skipped_stage_frac_draft = (float(metrics.skipped_stages_backpressure_draft) / stages_total_draft) if stages_total_draft > 0.0 else 0.0
    return(
        {
            "makespan_ms": float(makespan_ms),
            "token_throughput_tps": float(token_tps),
            "task_throughput_tps": float(task_tps),
            "output_tokens": float(output_tokens),
            "output_token_throughput_tps": float(output_tps),
            "dflash_steps": float(dflash_steps),
            "dflash_output_tokens": float(dflash_output_tokens),
            "dflash_output_token_throughput_tps": float(dflash_output_tps),
            "dflash_bonus_tokens": float(dflash_bonus_tokens),
            "dflash_mean_accept_len": float((dflash_output_tokens / dflash_steps) if dflash_steps > 0.0 else 0.0),
            "dflash_accept_rate": float(dflash_accept_rate),
            "service_slot_ms_total": float(metrics.service_slot_ms_total),
            "service_slot_ms_per_output_token": float(service_per_output_token),
            "service_batch_size_p50_interactive": float(_p_or_zero(metrics.service_batch_size_interactive, 0.50)),
            "service_batch_size_p95_interactive": float(_p_or_zero(metrics.service_batch_size_interactive, 0.95)),
            "service_batch_size_p50_batch": float(_p_or_zero(metrics.service_batch_size_batch, 0.50)),
            "service_batch_size_p95_batch": float(_p_or_zero(metrics.service_batch_size_batch, 0.95)),
            "trace_expert_batch_size_p50_interactive": float(_p_or_zero(metrics.trace_expert_batch_size_interactive, 0.50)),
            "trace_expert_batch_size_p95_interactive": float(_p_or_zero(metrics.trace_expert_batch_size_interactive, 0.95)),
            "trace_expert_batch_size_p50_batch": float(_p_or_zero(metrics.trace_expert_batch_size_batch, 0.50)),
            "trace_expert_batch_size_p95_batch": float(_p_or_zero(metrics.trace_expert_batch_size_batch, 0.95)),
            "trace_decode_ms_p50_interactive": float(_p_or_zero(metrics.trace_decode_ms_interactive, 0.50)),
            "trace_decode_ms_p95_interactive": float(_p_or_zero(metrics.trace_decode_ms_interactive, 0.95)),
            "trace_decode_ms_p50_batch": float(_p_or_zero(metrics.trace_decode_ms_batch, 0.50)),
            "trace_decode_ms_p95_batch": float(_p_or_zero(metrics.trace_decode_ms_batch, 0.95)),
            "trace_decode_error_ms_p50_interactive": float(_p_or_zero(metrics.trace_decode_error_ms_interactive, 0.50)),
            "trace_decode_error_ms_p95_interactive": float(_p_or_zero(metrics.trace_decode_error_ms_interactive, 0.95)),
            "trace_decode_error_ms_p50_batch": float(_p_or_zero(metrics.trace_decode_error_ms_batch, 0.50)),
            "trace_decode_error_ms_p95_batch": float(_p_or_zero(metrics.trace_decode_error_ms_batch, 0.95)),
            "trace_kv_tokens_p50_interactive": float(_p_or_zero(metrics.trace_kv_tokens_interactive, 0.50)),
            "trace_kv_tokens_p95_interactive": float(_p_or_zero(metrics.trace_kv_tokens_interactive, 0.95)),
            "trace_kv_tokens_p50_batch": float(_p_or_zero(metrics.trace_kv_tokens_batch, 0.50)),
            "trace_kv_tokens_p95_batch": float(_p_or_zero(metrics.trace_kv_tokens_batch, 0.95)),
            "drop_frac_tokens": float(drop_frac),
            "drop_frac_tokens_interactive": float(drop_frac_interactive),
            "drop_frac_tokens_batch": float(drop_frac_batch),
            "partial_admit_frac_tokens": float(partial_admit_frac),
            "token_p50_interactive_ms": float(_p_or_zero(metrics.token_lat_ms_interactive, 0.50)),
            "token_p95_interactive_ms": float(_p_or_zero(metrics.token_lat_ms_interactive, 0.95)),
            "token_p50_batch_ms": float(_p_or_zero(metrics.token_lat_ms_batch, 0.50)),
            "token_p95_batch_ms": float(_p_or_zero(metrics.token_lat_ms_batch, 0.95)),
            "output_token_p50_interactive_ms": float(_p_or_zero(metrics.output_token_lat_ms_interactive, 0.50)),
            "output_token_p95_interactive_ms": float(_p_or_zero(metrics.output_token_lat_ms_interactive, 0.95)),
            "output_token_p50_batch_ms": float(_p_or_zero(metrics.output_token_lat_ms_batch, 0.50)),
            "output_token_p95_batch_ms": float(_p_or_zero(metrics.output_token_lat_ms_batch, 0.95)),
            "sla_violation_frac_tokens_interactive": float(sla_violation_frac_interactive),
            "sla_violation_frac_tokens_batch": float(sla_violation_frac_batch),
            "starved_tasks": float(metrics.starved_tasks),
            "starved_task_frac": float(starved_task_frac),
            "starved_task_frac_interactive": float(starved_task_frac_interactive),
            "starved_task_frac_batch": float(starved_task_frac_batch),
            "starved_task_frac_mtp_draft": float(starved_task_frac_mtp_draft),
            "starved_task_frac_mtp_verify": float(starved_task_frac_mtp_verify),
            "dropped_tasks_backpressure": float(metrics.dropped_tasks_backpressure),
            "expert_max_pending_tasks_p50": float(_p_or_zero(metrics.max_pending_per_expert, 0.50)),
            "expert_max_pending_tasks_max": float(max(metrics.max_pending_per_expert)) if len(metrics.max_pending_per_expert) != 0 else 0.0,
            "expert_mean_pending_tasks_p50": float(_p_or_zero(metrics.mean_pending_per_expert, 0.50)),
            "expert_mean_pending_tasks_p95": float(_p_or_zero(metrics.mean_pending_per_expert, 0.95)),
            "expert_max_pending_work_p50": float(_p_or_zero(metrics.max_pending_work_per_expert, 0.50)),
            "expert_max_pending_work_max": float(max(metrics.max_pending_work_per_expert)) if len(metrics.max_pending_work_per_expert) != 0 else 0.0,
            "expert_mean_pending_work_p50": float(_p_or_zero(metrics.mean_pending_work_per_expert, 0.50)),
            "expert_mean_pending_work_p95": float(_p_or_zero(metrics.mean_pending_work_per_expert, 0.95)),
            "expert_utilization_p50": float(_p_or_zero(metrics.mean_utilization_per_expert, 0.50)),
            "expert_utilization_p95": float(_p_or_zero(metrics.mean_utilization_per_expert, 0.95)),
            "expert_utilization_gini": float(expert_utilization_gini),
            "expert_saturation_p50": float(_p_or_zero(metrics.saturated_time_frac_per_expert, 0.50)),
            "expert_saturation_p95": float(_p_or_zero(metrics.saturated_time_frac_per_expert, 0.95)),
            "expert_tasks_started_gini": float(expert_tasks_started_gini),
            "expert_tasks_started_top1_frac": float(expert_tasks_started_top1_frac),
            "pending_depth_time_weighted_p95": float(_hist_int_percentile(metrics.pending_depth_hist, metrics.pending_depth_hist_overflow, 0.95)),
            "hi_queue_depth_time_weighted_p95": float(_hist_int_percentile(metrics.hi_queue_depth_hist, metrics.hi_queue_depth_hist_overflow, 0.95)),
            "lo_queue_depth_time_weighted_p95": float(_hist_int_percentile(metrics.lo_queue_depth_hist, metrics.lo_queue_depth_hist_overflow, 0.95)),
            "pending_work_depth_time_weighted_p95": float(_hist_int_percentile(metrics.pending_work_depth_hist, metrics.pending_work_depth_hist_overflow, 0.95)),
            "hi_queue_work_depth_time_weighted_p95": float(_hist_int_percentile(metrics.hi_queue_work_depth_hist, metrics.hi_queue_work_depth_hist_overflow, 0.95)),
            "lo_queue_work_depth_time_weighted_p95": float(_hist_int_percentile(metrics.lo_queue_work_depth_hist, metrics.lo_queue_work_depth_hist_overflow, 0.95)),
            "pending_depth_time_weighted_p95_mtp_draft": float(_hist_int_percentile(metrics.pending_depth_hist_mtp_draft, metrics.pending_depth_hist_mtp_draft_overflow, 0.95)),
            "pending_depth_time_weighted_p95_mtp_verify": float(_hist_int_percentile(metrics.pending_depth_hist_mtp_verify, metrics.pending_depth_hist_mtp_verify_overflow, 0.95)),
            "mtp_accept_rate": float(mtp_accept_rate),
            "mtp_service_slot_ms_draft_frac": float(mtp_service_slot_draft_frac),
            "mtp_service_slot_ms_verify_frac": float(mtp_service_slot_verify_frac),
            "mtp_verify_layer0_skipped_backpressure": float(metrics.mtp_verify_layer0_skipped_backpressure),
            "mtp_verify_layer0_skipped_backpressure_frac": float(float(metrics.mtp_verify_layer0_skipped_backpressure) / float(metrics.mtp_verify_steps)) if metrics.mtp_verify_steps > 0 else 0.0,
            "mtp_accept_len_clamped_backpressure": float(metrics.mtp_accept_len_clamped_backpressure),
            "mtp_accept_len_clamped_backpressure_frac": float(float(metrics.mtp_accept_len_clamped_backpressure) / float(metrics.mtp_verify_steps)) if metrics.mtp_verify_steps > 0 else 0.0,
            "stages_total": float(stages_total),
            "skipped_stages_backpressure": float(skipped_stages),
            "skipped_stage_frac": float(skipped_stage_frac),
            "skipped_stage_frac_interactive": float(skipped_stage_frac_interactive),
            "skipped_stage_frac_batch": float(skipped_stage_frac_batch),
            "skipped_stage_frac_verify": float(skipped_stage_frac_verify),
            "skipped_stage_frac_draft": float(skipped_stage_frac_draft),
        }
    )


def _sim_cfg_apply_overrides(base: SimConfig, overrides: Dict[str, object]) -> SimConfig:
    fields = set(SimConfig.__dataclass_fields__.keys())
    adapt_fields = set(AdaptiveKConfig.__dataclass_fields__.keys())
    replace_kwargs: Dict[str, object] = {}
    adapt_kwargs: Dict[str, object] = {}
    for k, v in overrides.items():
        if k.startswith("adaptive_k."):
            sub = k[len("adaptive_k.") :]
            if sub not in adapt_fields:
                raise ValueError(f"Unknown AdaptiveKConfig field '{sub}' in override '{k}'")
            adapt_kwargs[sub] = v
            continue
        if k not in fields:
            raise ValueError(f"Unknown SimConfig field '{k}' in override")
        replace_kwargs[k] = v
    cfg = base
    if len(adapt_kwargs) != 0:
        cfg = dataclasses.replace(cfg, adaptive_k=dataclasses.replace(cfg.adaptive_k, **adapt_kwargs))
    if len(replace_kwargs) != 0:
        cfg = dataclasses.replace(cfg, **replace_kwargs)
    return(cfg)


def strip_trace_mtp_fields(trace: Sequence[TokenRoute]) -> List[TokenRoute]:
    out: List[TokenRoute] = []
    any_mtp = False
    for r in trace:
        if r.mtp_accept_len is not None or r.accepted_mtp is not None or r.rejected_mtp is not None:
            any_mtp = True
            break
    if any_mtp == False:
        return(list(trace))
    for r in trace:
        if r.mtp_accept_len is None and r.accepted_mtp is None and r.rejected_mtp is None:
            out.append(r)
            continue
        out.append(dataclasses.replace(r, mtp_accept_len=None, accepted_mtp=None, rejected_mtp=None))
    return(out)


def compare_simulation_variants(
    base_cfg: SimConfig,
    trace: Sequence[TokenRoute],
    variants: Sequence[Tuple[str, Dict[str, object]]],
    *,
    arrival_units: str = "steps",
) -> Dict[str, object]:
    return(
        compare_simulation_variants_with_dumps(
            base_cfg,
            trace,
            variants,
            dump_sim_jsonl_tmpl="",
            trace_meta=None,
            arrival_units=arrival_units,
        )
    )


def compare_simulation_variants_with_dumps(
    base_cfg: SimConfig,
    trace: Sequence[TokenRoute],
    variants: Sequence[Tuple[str, Dict[str, object]]],
    dump_sim_jsonl_tmpl: str = "",
    trace_meta: Optional[Dict[str, object]] = None,
    *,
    arrival_units: str = "steps",
) -> Dict[str, object]:
    out: Dict[str, object] = {"arrival_units": str(arrival_units)}
    dump_tmpl = dump_sim_jsonl_tmpl.strip()
    dump_enabled = (dump_tmpl != "")
    base_token_states: List[TokenState] = []
    base_trace = scale_trace_arrival_units(trace, arrival_units, base_cfg)
    base_metrics = run_simulation(base_cfg, base_trace, token_states_out=base_token_states if dump_enabled else None)
    if dump_enabled:
        write_sim_jsonl(dump_tmpl.replace("{label}", "baseline"), base_trace, base_token_states, base_cfg, meta=trace_meta)
    base_json = base_metrics.to_jsonable()
    base_summary = compare_summary_jsonable(base_metrics)
    out["baseline"] = {"overrides": {}, "summary": base_summary, "metrics": base_json}

    variants_out: Dict[str, object] = {}
    for label, overrides in variants:
        cfg = _sim_cfg_apply_overrides(base_cfg, overrides)
        token_states: List[TokenState] = []
        trace_in = trace
        if int(base_cfg.mtp_draft_len) > 0 and int(cfg.mtp_draft_len) <= 0:
            trace_in = strip_trace_mtp_fields(trace)
        v_trace = scale_trace_arrival_units(trace_in, arrival_units, cfg)
        m = run_simulation(cfg, v_trace, token_states_out=token_states if dump_enabled else None)
        if dump_enabled:
            write_sim_jsonl(dump_tmpl.replace("{label}", label), v_trace, token_states, cfg, meta=trace_meta)
        summary = compare_summary_jsonable(m)
        delta: Dict[str, float] = {}
        for k, v in summary.items():
            base_v = float(base_summary.get(k, 0.0))
            delta[k] = (float(v) - base_v)
        variants_out[label] = {
            "overrides": overrides,
            "summary": summary,
            "delta_vs_baseline": delta,
            "metrics": m.to_jsonable(),
        }
    out["variants"] = variants_out
    return(out)


def compare_simulation_summaries(
    base_cfg: SimConfig,
    trace: Sequence[TokenRoute],
    variants: Sequence[Tuple[str, Dict[str, object]]],
    *,
    arrival_units: str = "steps",
) -> Dict[str, object]:
    return(
        compare_simulation_summaries_with_dumps(
            base_cfg,
            trace,
            variants,
            dump_sim_jsonl_tmpl="",
            trace_meta=None,
            arrival_units=arrival_units,
        )
    )


def compare_simulation_summaries_with_dumps(
    base_cfg: SimConfig,
    trace: Sequence[TokenRoute],
    variants: Sequence[Tuple[str, Dict[str, object]]],
    dump_sim_jsonl_tmpl: str = "",
    trace_meta: Optional[Dict[str, object]] = None,
    *,
    arrival_units: str = "steps",
) -> Dict[str, object]:
    out: Dict[str, object] = {"arrival_units": str(arrival_units)}
    dump_tmpl = dump_sim_jsonl_tmpl.strip()
    dump_enabled = (dump_tmpl != "")
    base_token_states: List[TokenState] = []
    base_trace = scale_trace_arrival_units(trace, arrival_units, base_cfg)
    base_metrics = run_simulation(base_cfg, base_trace, token_states_out=base_token_states if dump_enabled else None)
    if dump_enabled:
        write_sim_jsonl(dump_tmpl.replace("{label}", "baseline"), base_trace, base_token_states, base_cfg, meta=trace_meta)
    base_summary = compare_summary_jsonable(base_metrics)
    out["baseline"] = {"overrides": {}, "summary": base_summary}

    variants_out: Dict[str, object] = {}
    for label, overrides in variants:
        cfg = _sim_cfg_apply_overrides(base_cfg, overrides)
        token_states: List[TokenState] = []
        trace_in = trace
        if int(base_cfg.mtp_draft_len) > 0 and int(cfg.mtp_draft_len) <= 0:
            trace_in = strip_trace_mtp_fields(trace)
        v_trace = scale_trace_arrival_units(trace_in, arrival_units, cfg)
        m = run_simulation(cfg, v_trace, token_states_out=token_states if dump_enabled else None)
        if dump_enabled:
            write_sim_jsonl(dump_tmpl.replace("{label}", label), v_trace, token_states, cfg, meta=trace_meta)
        summary = compare_summary_jsonable(m)
        delta: Dict[str, float] = {}
        for k, v in summary.items():
            base_v = float(base_summary.get(k, 0.0))
            delta[k] = (float(v) - base_v)
        variants_out[label] = {"overrides": overrides, "summary": summary, "delta_vs_baseline": delta}
    out["variants"] = variants_out
    return(out)


def scale_trace_speedup(trace: Sequence[TokenRoute], speedup: float) -> List[TokenRoute]:
    if speedup <= 0.0:
        raise ValueError("trace_speedup must be > 0")
    if speedup == 1.0:
        return(list(trace))
    scale = (1.0 / float(speedup))
    return([dataclasses.replace(r, t_ms=(float(r.t_ms) * scale)) for r in trace])


def scale_trace_arrival_units(trace: Sequence[TokenRoute], arrival_units: str, cfg: SimConfig) -> List[TokenRoute]:
    units = arrival_units.strip().lower()
    if units in ("", "steps"):
        return(list(trace))
    if units != "output_tokens":
        raise ValueError("arrival_units must be 'steps' or 'output_tokens'")
    if cfg.mtp_draft_len <= 0:
        return(list(trace))
    if len(trace) <= 1:
        return(list(trace))

    derived: List[float] = []
    for r in trace:
        al = _derive_mtp_accept_len(r, int(cfg.mtp_draft_len))
        if al is not None:
            derived.append(float(int(al)))
    if len(derived) != 0:
        scale = statistics.fmean(derived)
    else:
        scale = expected_mtp_accept_len(int(cfg.mtp_draft_len), float(cfg.mtp_accept_prob), float(cfg.mtp_accept_decay))
    if scale <= 0.0:
        return(list(trace))
    if abs(scale - 1.0) < 1e-12:
        return(list(trace))

    t0 = float(trace[0].t_ms)
    out: List[TokenRoute] = []
    for r in trace:
        t_ms = float(t0 + ((float(r.t_ms) - t0) * float(scale)))
        out.append(dataclasses.replace(r, t_ms=t_ms))
    return(out)


def _p50(xs: Sequence[float]) -> float:
    if len(xs) == 0:
        raise ValueError("xs must be non-empty")
    xs_sorted = sorted(xs)
    idx50 = int(math.floor(0.50 * float(len(xs_sorted) - 1)))
    return(float(xs_sorted[idx50]))


def derive_trace_cost_scale(trace: Sequence[TokenRoute], mode: str, meta_out: Optional[Dict[str, object]] = None) -> List[TokenRoute]:
    mode_n = mode.strip().lower()
    if mode_n in ("", "none"):
        return(list(trace))

    ref = 0.0
    derived_field = ""
    if mode_n == "kv_tokens_p50":
        xs = [float(r.kv_tokens) for r in trace if r.kv_tokens is not None and int(r.kv_tokens) > 0]
        if len(xs) == 0:
            raise ValueError("trace_derive_cost_scale=kv_tokens_p50 requires kv_tokens in the trace")
        ref = _p50(xs)
        derived_field = "kv_tokens"
    elif mode_n == "decode_ms_p50":
        xs = [float(r.decode_ms) for r in trace if r.decode_ms is not None and float(r.decode_ms) > 0.0]
        if len(xs) == 0:
            raise ValueError("trace_derive_cost_scale=decode_ms_p50 requires decode_ms in the trace")
        ref = _p50(xs)
        derived_field = "decode_ms"
    else:
        raise ValueError("trace_derive_cost_scale must be one of: none, kv_tokens_p50, decode_ms_p50")

    if ref <= 0.0:
        raise ValueError("trace_derive_cost_scale reference must be > 0")

    eps = 1e-6
    out: List[TokenRoute] = []
    filled = 0
    for r in trace:
        if r.cost_scale is not None:
            out.append(r)
            continue
        if mode_n == "kv_tokens_p50":
            if r.kv_tokens is None:
                out.append(r)
                continue
            s = (float(int(r.kv_tokens)) / float(ref))
        else:
            if r.decode_ms is None:
                out.append(r)
                continue
            s = (float(r.decode_ms) / float(ref))
        if s <= 0.0:
            s = eps
        out.append(dataclasses.replace(r, cost_scale=float(s)))
        filled += 1

    if meta_out is not None:
        meta_out["derived_cost_scale"] = {"mode": str(mode_n), "field": str(derived_field), "p50_ref": float(ref), "filled": int(filled)}
    return(out)


def _parse_args(argv: Optional[Sequence[str]] = None) -> argparse.Namespace:
    p = argparse.ArgumentParser(description="Host-only scheduler simulator (synthetic routing traces).")
    p.add_argument(
        "--trace-jsonl",
        type=str,
        default="",
        help="Replay routing trace from JSONL file (use '-' for stdin). Required fields: t_ms/dt_ms, cls, candidates (or layers). Optional: token_index, k, scores, mtp_accept_len, accepted_mtp, rejected_mtp, dflash_accept_len, accepted_dflash, rejected_dflash, cost_scale, decode_ms, kv_tokens, expert_batch_size.",
    )
    p.add_argument(
        "--trace-input-format",
        type=str,
        default="strict",
        choices=("strict", "runtime"),
        help="JSONL trace input format: strict expects the simulator contract; runtime applies the trace extractor's alias mapping first (useful for mixed/alias-heavy runtime logs).",
    )
    p.add_argument("--trace-route-type", type=str, default="", help="JSONL runtime-format trace: only accept records with obj.type == trace-route-type (empty = accept all).")
    p.add_argument(
        "--trace-default-cls",
        type=str,
        default="",
        help="Optional: when trace records omit cls/latency class, treat all routes as this value (interactive or batch). Useful for early runtime traces that do not tag QoS.",
    )
    p.add_argument("--trace-csv", type=str, default="", help="Replay routing trace from CSV file with a header row (t_ms or dt_ms, cls, candidates; same optional fields as --trace-jsonl; list fields can be JSON lists).")
    p.add_argument("--trace-meta-json", type=str, default="", help="Optional JSON file with trace metadata (merged into the trace summary; overridden by any inline JSONL meta records).")
    p.add_argument("--trace-time-mode", type=str, default="t_ms", help="Trace replay time mode (with --trace-jsonl/--trace-csv): t_ms (default) requires per-record t_ms, dt_ms uses per-record dt_ms deltas and cumulative sum.")
    p.add_argument(
        "--trace-derive-cost-scale",
        type=str,
        default="none",
        help="Trace replay/canonicalization helper: fill missing cost_scale using a simple per-token proxy (none, kv_tokens_p50, decode_ms_p50).",
    )
    p.add_argument(
        "--trace-non-route",
        type=str,
        default="error",
        choices=("error", "skip"),
        help="JSONL trace replay: what to do with non-route input. 'skip' ignores non-route JSON objects (non-meta 'type' without route fields) and non-JSON lines (useful for mixed runtime stdout/stderr logs).",
    )
    p.add_argument("--trace-speedup", type=float, default=1.0, help="Scale trace arrivals by dividing t_ms by this factor (>0). Useful for stressing backpressure/starvation using one fixed trace.")
    p.add_argument("--trace-summary", action="store_true", help="Print a JSON summary of the trace contract (and exit).")
    p.add_argument(
        "--summary-json",
        action="store_true",
        help="Print a concise JSON summary of the simulation metrics (and exit). When used with --compare, prints only summaries + deltas (no full metrics).",
    )
    p.add_argument("--canonicalize-trace-jsonl", type=str, default="", help="Replay trace tool: write a canonical JSONL trace (meta header + derived mtp_accept_len / dflash_accept_len) and exit. Requires --trace-jsonl/--trace-csv. Use '-' for stdout.")
    p.add_argument("--dump-trace-jsonl", type=str, default="", help="Write the generated synthetic trace to a JSONL file before simulation (t_ms, cls, candidates; includes layers when --num-layers>1).")
    p.add_argument("--dump-trace-csv", type=str, default="", help="Write the generated synthetic trace to a CSV file before simulation (t_ms, cls, candidates; includes layers when --num-layers>1).")
    p.add_argument(
        "--dump-sim-jsonl",
        type=str,
        default="",
        help="Write per-token simulation results to JSONL after running (meta header + one record per trace step). Use '-' for stdout. With --compare, include '{label}' in the path to emit one dump per variant (plus baseline).",
    )
    p.add_argument("--trace-mode", type=str, default="zipf", help="Synthetic trace mode: zipf (default), hotset, markov, or twostream.")
    p.add_argument("--num-experts", type=int, default=64, help="Number of experts. Replay: use 0 to infer from the trace/meta.")
    p.add_argument("--num-tokens", type=int, default=20000)
    p.add_argument("--num-candidates", type=int, default=16)
    p.add_argument("--num-layers", type=int, default=1, help="Synthetic trace: number of MoE layers per token (1 = candidates only; >1 emits per-layer routing under `layers`).")
    p.add_argument(
        "--synthetic-score-mode",
        type=str,
        default="none",
        choices=("none", "random", "router_desc"),
        help="Synthetic trace: emit per-candidate `scores`. random assigns independent U[0,1) scores; router_desc also reorders candidates by descending score (router-like). Multi-layer traces emit scores under layers[].scores.",
    )
    p.add_argument(
        "--synthetic-cost-scale-mode",
        type=str,
        default="none",
        choices=("none", "lognormal"),
        help="Synthetic trace: emit per-token `cost_scale`. lognormal draws exp(N(0, sigma)) so median is ~1.0.",
    )
    p.add_argument("--synthetic-cost-scale-log-sigma", type=float, default=0.5, help="Synthetic trace: lognormal sigma for --synthetic-cost-scale-mode lognormal (must be >0).")
    p.add_argument("--interactive-prob", type=float, default=0.3)
    p.add_argument("--arrival-rate-tps", type=float, default=5000.0)
    p.add_argument("--interactive-arrival-rate-tps", type=float, default=-1.0, help="Two-stream synthetic trace: interactive arrival rate (defaults to arrival_rate_tps * interactive_prob).")
    p.add_argument("--batch-arrival-rate-tps", type=float, default=-1.0, help="Two-stream synthetic trace: batch arrival rate (defaults to arrival_rate_tps * (1-interactive_prob)).")
    p.add_argument(
        "--arrival-units",
        type=str,
        default="steps",
        help="Synthetic: interpret --arrival-rate-tps as steps (verify steps) or output_tokens (rescale by expected MTP accept length when enabled). Trace replay: output_tokens scales trace arrival deltas by expected/observed accept length so MTP comparisons hold output-token demand roughly constant.",
    )
    p.add_argument("--burst-prob", type=float, default=0.05)
    p.add_argument("--burst-scale", type=float, default=8.0)
    p.add_argument("--interactive-burst-prob", type=float, default=-1.0, help="Two-stream synthetic trace: interactive burst probability (defaults to --burst-prob).")
    p.add_argument("--interactive-burst-scale", type=float, default=-1.0, help="Two-stream synthetic trace: interactive burst scale (defaults to --burst-scale).")
    p.add_argument("--batch-burst-prob", type=float, default=-1.0, help="Two-stream synthetic trace: batch burst probability (defaults to --burst-prob).")
    p.add_argument("--batch-burst-scale", type=float, default=-1.0, help="Two-stream synthetic trace: batch burst scale (defaults to --burst-scale).")
    p.add_argument("--zipf-alpha", type=float, default=1.1)
    p.add_argument("--hotset-size", type=int, default=8, help="Hotset trace: number of 'hot' experts.")
    p.add_argument("--hotset-bias", type=float, default=0.9, help="Hotset trace: probability a candidate is drawn from the hotset.")
    p.add_argument("--hotset-rotate-every-tokens", type=int, default=2000, help="Hotset trace: rotate hotset every N tokens (0 = never).")
    p.add_argument("--markov-stay-prob", type=float, default=0.9, help="Markov trace: probability to reuse previous token's primary expert.")
    p.add_argument("--seed", type=int, default=1)

    p.add_argument("--expert-parallelism", type=int, default=2)
    p.add_argument("--expert-queue-max", type=int, default=256)
    p.add_argument(
        "--expert-queue-reserve-interactive",
        type=int,
        default=0,
        help="Reserve per-expert queue capacity for interactive tasks by reducing the effective pending limit for batch admissions (batch_limit = expert_queue_max - reserve).",
    )
    p.add_argument("--service-ms", type=float, default=0.15)
    p.add_argument("--service-base-ms", type=float, default=0.0, help="Batch service model: fixed overhead per started expert batch.")
    p.add_argument("--service-per-task-ms", type=float, default=-1.0, help="Batch service model: incremental cost per task in a started expert batch (-1 = use --service-ms).")
    p.add_argument("--batch-max-interactive", type=int, default=1, help="Max tasks started per expert batch for interactive queue (1 = no batching).")
    p.add_argument("--batch-max-batch", type=int, default=1, help="Max tasks started per expert batch for batch queue (1 = no batching).")
    p.add_argument("--batch-wait-interactive-ms", type=float, default=0.0, help="Batching window: max time to wait to fill interactive expert batches (0 = start immediately).")
    p.add_argument("--batch-wait-batch-ms", type=float, default=0.0, help="Batching window: max time to wait to fill batch expert batches (0 = start immediately).")
    p.add_argument("--starvation-ms", type=float, default=50.0)
    p.add_argument("--hi-burst", type=int, default=0, help="Per-expert fairness: after starting N interactive tasks consecutively, force one batch start if any are queued (0 = strict priority).")
    p.add_argument("--promote-ms", type=float, default=0.0, help="Per-expert aging: promote batch tasks to interactive queue once they wait this long (0 = disabled).")
    p.add_argument("--sla-interactive-ms", type=float, default=0.0, help="Token SLA: count interactive tokens with latency > this (0 = disabled).")
    p.add_argument("--sla-batch-ms", type=float, default=0.0, help="Token SLA: count batch tokens with latency > this (0 = disabled).")
    p.add_argument("--sim-seed", type=int, default=1, help="Simulation seed (used for MTP accept/reject sampling).")
    p.add_argument("--mtp-draft-len", type=int, default=0, help="MTP: number of draft tokens per verify step (0 = disabled). Replay: use -1 to infer from trace/meta (requires accepted_mtp+rejected_mtp or meta.mtp_draft_len).")
    p.add_argument("--mtp-accept-prob", type=float, default=0.0, help="MTP: conditional accept probability for draft position 0 (within [0,1]).")
    p.add_argument("--mtp-accept-decay", type=float, default=1.0, help="MTP: conditional accept probability decay factor per draft position (>0, <1 biases early accept).")
    p.add_argument("--mtp-draft-cost-scale", type=float, default=0.25, help="MTP: per-task cost scaling for draft tokens relative to verify tokens (>0).")
    p.add_argument("--mtp-verify-per-draft-cost-scale", type=float, default=0.0, help="MTP: extra verify cost scale per drafted token (verify_cost *= 1 + this*draft_len).")
    p.add_argument("--mtp-draft-attempt-policy", type=str, default="full", help="MTP: draft compute policy: full (always compute mtp_draft_len drafts) or stop_at_reject (only compute the draft prefix up to the first rejection).")

    p.add_argument("--k-min-interactive", type=int, default=2)
    p.add_argument("--k-max-interactive", type=int, default=4)
    p.add_argument("--k-min-batch", type=int, default=1)
    p.add_argument("--k-max-batch", type=int, default=2)
    p.add_argument("--q-low", type=int, default=16)
    p.add_argument("--q-high", type=int, default=128)
    p.add_argument("--k-ema-alpha", type=float, default=1.0, help="Adaptive-K control: EMA smoothing alpha over pending signal ((0,1], 1 = no smoothing).")
    p.add_argument("--k-update-ms", type=float, default=0.0, help="Adaptive-K control: minimum time between K updates (0 = per-token).")
    p.add_argument("--k-slew", type=int, default=0, help="Adaptive-K control: max |delta K| per controller update (0 = unlimited).")
    p.add_argument("--k-mode", type=str, default="controller", help="K source: controller (default) or trace (use per-route k from JSONL).")
    p.add_argument(
        "--k-signal",
        type=str,
        default="global",
        help="Adaptive-K congestion signal: global (max total pending across all experts), candidates (max total pending among this token's candidates), or class (max pending in this token's latency-class queue + in-flight across all experts).",
    )
    p.add_argument("--pending-units", type=str, default="tasks", help="Adaptive-K pending units: tasks (default) uses outstanding task counts; work uses sum(cost_scale) of queued + in-flight work per expert.")
    p.add_argument(
        "--backpressure-units",
        type=str,
        default="tasks",
        help="Backpressure capacity units: tasks (default) caps queued+in-flight tasks per expert; work caps queued+in-flight sum(cost_scale) per expert (use with meaningful cost_scale in traces).",
    )
    p.add_argument("--k-scope", type=str, default="token", help="Adaptive-K controller scope: token (default) chooses one K per trace entry; layer chooses K independently for each MoE layer using that layer's candidates (requires layers[] in the trace).")
    p.add_argument("--admit-policy", type=str, default="ordered", help="Candidate admission policy: ordered (router order), least_pending (pick least pending experts among candidates), or score_desc (order candidates by descending trace scores).")
    p.add_argument("--pending-hist-max-depth", type=int, default=2048, help="Time-weighted pending-depth percentiles: cap histogram depth at this value (0 = disable).")

    p.add_argument("--compare", action="append", default=[], help="Run labeled variant(s) vs the baseline config. Format: label:JSON, with optional keys like mtp_draft_len or adaptive_k.q_high.")
    p.add_argument("--json", action="store_true", help="Print JSON metrics only.")
    return(p.parse_args(argv))


def main(argv: Optional[Sequence[str]] = None) -> int:
    args = _parse_args(argv)

    try:
        trace_speedup = float(args.trace_speedup)
    except (TypeError, ValueError):
        raise SystemExit("--trace-speedup must be a number")

    if args.trace_jsonl != "" and args.trace_csv != "":
        raise SystemExit("Choose exactly one: --trace-jsonl or --trace-csv")

    if args.dump_trace_jsonl.strip() != "" and args.dump_trace_csv.strip() != "":
        raise SystemExit("Choose at most one: --dump-trace-jsonl or --dump-trace-csv")

    if args.canonicalize_trace_jsonl.strip() != "" and args.trace_jsonl == "" and args.trace_csv == "":
        raise SystemExit("--canonicalize-trace-jsonl requires --trace-jsonl or --trace-csv")

    dump_sim_jsonl = args.dump_sim_jsonl.strip()
    dump_sim_enabled = (dump_sim_jsonl != "")

    if dump_sim_enabled and args.trace_summary:
        raise SystemExit("--dump-sim-jsonl is not compatible with --trace-summary (no simulation run)")
    if dump_sim_enabled and args.canonicalize_trace_jsonl.strip() != "":
        raise SystemExit("--dump-sim-jsonl is not compatible with --canonicalize-trace-jsonl (no simulation run)")
    if dump_sim_enabled and len(args.compare) != 0 and "{label}" not in dump_sim_jsonl:
        raise SystemExit("--dump-sim-jsonl with --compare requires a '{label}' placeholder in the path")

    trace_meta: Dict[str, object] = {}
    if args.trace_meta_json.strip() != "":
        if args.trace_jsonl == "" and args.trace_csv == "":
            raise SystemExit("--trace-meta-json requires --trace-jsonl or --trace-csv")
        try:
            with open(args.trace_meta_json, "r", encoding="utf-8") as f:
                obj = json.load(f)
        except OSError as e:
            raise SystemExit(f"--trace-meta-json read failed: {e}")
        except json.JSONDecodeError as e:
            raise SystemExit(f"--trace-meta-json parse failed: {e}")
        if not isinstance(obj, dict):
            raise SystemExit("--trace-meta-json must contain a JSON object")
        trace_meta.update(obj)

    if args.trace_jsonl != "" or args.trace_csv != "":
        if args.synthetic_score_mode.strip().lower() != "none":
            raise SystemExit("--synthetic-score-mode is only supported for synthetic trace generation (omit --trace-jsonl/--trace-csv)")
        if args.synthetic_cost_scale_mode.strip().lower() != "none":
            raise SystemExit("--synthetic-cost-scale-mode is only supported for synthetic trace generation (omit --trace-jsonl/--trace-csv)")
        if args.dump_trace_jsonl.strip() != "" or args.dump_trace_csv.strip() != "":
            raise SystemExit("--dump-trace-* is only supported for synthetic trace generation (omit --trace-jsonl/--trace-csv)")
        # --arrival-units can also be applied in trace replay mode by scaling trace arrival deltas per run.
        if args.trace_jsonl != "":
            trace = load_trace_jsonl(
                args.trace_jsonl,
                time_mode=args.trace_time_mode.strip().lower(),
                meta_out=trace_meta,
                non_route_policy=args.trace_non_route.strip().lower(),
                input_format=args.trace_input_format.strip().lower(),
                route_type=args.trace_route_type.strip(),
                default_cls=args.trace_default_cls,
            )
        else:
            trace = load_trace_csv(args.trace_csv, time_mode=args.trace_time_mode.strip().lower())
        if trace_speedup != 1.0:
            try:
                trace = scale_trace_speedup(trace, trace_speedup)
            except ValueError as e:
                raise SystemExit(str(e))

        if args.num_experts == 0:
            inferred = infer_num_experts_from_trace(trace, trace_meta)
            if inferred is None or inferred <= 0:
                raise SystemExit("--num-experts=0 requires a trace (or meta.num_experts) with valid expert IDs")
            args.num_experts = int(inferred)
        if args.mtp_draft_len == -1:
            inferred = infer_mtp_draft_len_from_trace(trace, trace_meta)
            if inferred is None:
                raise SystemExit("--mtp-draft-len=-1 requires meta.mtp_draft_len or consistent accepted_mtp+rejected_mtp in the trace")
            args.mtp_draft_len = int(inferred)

        if args.trace_derive_cost_scale.strip().lower() != "none":
            try:
                trace = derive_trace_cost_scale(trace, args.trace_derive_cost_scale, meta_out=trace_meta)
            except ValueError as e:
                raise SystemExit(str(e))

        if args.trace_summary:
            out = trace_summary_jsonable(trace, mtp_draft_len=args.mtp_draft_len, meta=trace_meta)
            if args.json:
                print(json.dumps(out, sort_keys=True))
                return(0)
            print("== trace summary ==")
            print(json.dumps(out, indent=2, sort_keys=True))
            return(0)

        if args.canonicalize_trace_jsonl.strip() != "":
            try:
                write_trace_jsonl_canonical(args.canonicalize_trace_jsonl, trace, meta=trace_meta)
            except (ValueError, OSError) as e:
                raise SystemExit(str(e))
            return(0)
    else:
        if args.num_experts <= 0:
            raise SystemExit("--num-experts must be > 0 for synthetic trace generation (use 0 only with --trace-jsonl/--trace-csv)")
        if args.mtp_draft_len == -1:
            raise SystemExit("--mtp-draft-len=-1 is only supported for trace replay (use an explicit value for synthetic traces)")
        try:
            arrival_rate_tps = arrival_rate_steps_tps(args.arrival_rate_tps, args.arrival_units, args.mtp_draft_len, args.mtp_accept_prob, args.mtp_accept_decay)
        except ValueError as e:
            raise SystemExit(str(e))

        mode = args.trace_mode.strip().lower()
        if mode == "zipf":
            trace_cfg = TraceConfig(
                num_tokens=args.num_tokens,
                num_experts=args.num_experts,
                num_candidates=args.num_candidates,
                interactive_prob=args.interactive_prob,
                arrival_rate_tps=arrival_rate_tps,
                burst_prob=args.burst_prob,
                burst_scale=args.burst_scale,
                zipf_alpha=args.zipf_alpha,
                seed=args.seed,
                num_layers=args.num_layers,
                synthetic_score_mode=args.synthetic_score_mode.strip().lower(),
                synthetic_cost_scale_mode=args.synthetic_cost_scale_mode.strip().lower(),
                synthetic_cost_scale_log_sigma=float(args.synthetic_cost_scale_log_sigma),
            )
            trace = generate_synthetic_trace(trace_cfg)
        elif mode == "hotset":
            trace_cfg = HotsetTraceConfig(
                num_tokens=args.num_tokens,
                num_experts=args.num_experts,
                num_candidates=args.num_candidates,
                interactive_prob=args.interactive_prob,
                arrival_rate_tps=arrival_rate_tps,
                burst_prob=args.burst_prob,
                burst_scale=args.burst_scale,
                hotset_size=args.hotset_size,
                hotset_bias=args.hotset_bias,
                hotset_rotate_every_tokens=args.hotset_rotate_every_tokens,
                seed=args.seed,
                num_layers=args.num_layers,
                synthetic_score_mode=args.synthetic_score_mode.strip().lower(),
                synthetic_cost_scale_mode=args.synthetic_cost_scale_mode.strip().lower(),
                synthetic_cost_scale_log_sigma=float(args.synthetic_cost_scale_log_sigma),
            )
            trace = generate_hotset_trace(trace_cfg)
        elif mode == "markov":
            trace_cfg = MarkovTraceConfig(
                num_tokens=args.num_tokens,
                num_experts=args.num_experts,
                num_candidates=args.num_candidates,
                interactive_prob=args.interactive_prob,
                arrival_rate_tps=arrival_rate_tps,
                burst_prob=args.burst_prob,
                burst_scale=args.burst_scale,
                zipf_alpha=args.zipf_alpha,
                stay_prob=args.markov_stay_prob,
                seed=args.seed,
                num_layers=args.num_layers,
                synthetic_score_mode=args.synthetic_score_mode.strip().lower(),
                synthetic_cost_scale_mode=args.synthetic_cost_scale_mode.strip().lower(),
                synthetic_cost_scale_log_sigma=float(args.synthetic_cost_scale_log_sigma),
            )
            trace = generate_markov_trace(trace_cfg)
        elif mode == "twostream":
            try:
                hi_rate_in = float(args.interactive_arrival_rate_tps) if float(args.interactive_arrival_rate_tps) >= 0.0 else -1.0
                lo_rate_in = float(args.batch_arrival_rate_tps) if float(args.batch_arrival_rate_tps) >= 0.0 else -1.0
                if hi_rate_in < 0.0:
                    hi_rate_in = (float(args.arrival_rate_tps) * float(args.interactive_prob))
                if lo_rate_in < 0.0:
                    lo_rate_in = (float(args.arrival_rate_tps) * (1.0 - float(args.interactive_prob)))
                hi_rate = arrival_rate_steps_tps(hi_rate_in, args.arrival_units, args.mtp_draft_len, args.mtp_accept_prob, args.mtp_accept_decay) if hi_rate_in > 0.0 else 0.0
                lo_rate = arrival_rate_steps_tps(lo_rate_in, args.arrival_units, args.mtp_draft_len, args.mtp_accept_prob, args.mtp_accept_decay) if lo_rate_in > 0.0 else 0.0
            except ValueError as e:
                raise SystemExit(str(e))

            hi_burst_prob = float(args.interactive_burst_prob) if float(args.interactive_burst_prob) >= 0.0 else float(args.burst_prob)
            hi_burst_scale = float(args.interactive_burst_scale) if float(args.interactive_burst_scale) > 0.0 else float(args.burst_scale)
            lo_burst_prob = float(args.batch_burst_prob) if float(args.batch_burst_prob) >= 0.0 else float(args.burst_prob)
            lo_burst_scale = float(args.batch_burst_scale) if float(args.batch_burst_scale) > 0.0 else float(args.burst_scale)

            trace_cfg = TwoStreamTraceConfig(
                num_tokens=args.num_tokens,
                num_experts=args.num_experts,
                num_candidates=args.num_candidates,
                interactive_arrival_rate_tps=float(hi_rate),
                batch_arrival_rate_tps=float(lo_rate),
                interactive_burst_prob=float(hi_burst_prob),
                interactive_burst_scale=float(hi_burst_scale),
                batch_burst_prob=float(lo_burst_prob),
                batch_burst_scale=float(lo_burst_scale),
                zipf_alpha=args.zipf_alpha,
                seed=args.seed,
                num_layers=args.num_layers,
                synthetic_score_mode=args.synthetic_score_mode.strip().lower(),
                synthetic_cost_scale_mode=args.synthetic_cost_scale_mode.strip().lower(),
                synthetic_cost_scale_log_sigma=float(args.synthetic_cost_scale_log_sigma),
            )
            trace = generate_twostream_trace(trace_cfg)
        else:
            raise SystemExit(f"Unknown --trace-mode '{args.trace_mode}'; expected zipf, hotset, markov, or twostream.")

        if trace_speedup != 1.0:
            try:
                trace = scale_trace_speedup(trace, trace_speedup)
            except ValueError as e:
                raise SystemExit(str(e))

        if args.dump_trace_jsonl.strip() != "":
            write_trace_jsonl(args.dump_trace_jsonl, trace)
        if args.dump_trace_csv.strip() != "":
            write_trace_csv(args.dump_trace_csv, trace)
        if args.trace_summary:
            out = trace_summary_jsonable(trace, mtp_draft_len=args.mtp_draft_len, meta=trace_meta)
            if args.json:
                print(json.dumps(out, sort_keys=True))
                return(0)
            print("== trace summary ==")
            print(json.dumps(out, indent=2, sort_keys=True))
            return(0)

    adapt = AdaptiveKConfig(
        k_min_interactive=args.k_min_interactive,
        k_max_interactive=args.k_max_interactive,
        k_min_batch=args.k_min_batch,
        k_max_batch=args.k_max_batch,
        q_low=args.q_low,
        q_high=args.q_high,
        ema_alpha=args.k_ema_alpha,
        update_ms=args.k_update_ms,
        k_slew=args.k_slew,
    )
    sim_cfg = SimConfig(
        num_experts=args.num_experts,
        expert_parallelism=args.expert_parallelism,
        expert_queue_max=args.expert_queue_max,
        expert_queue_reserve_interactive=args.expert_queue_reserve_interactive,
        service_ms=args.service_ms,
        service_base_ms=args.service_base_ms,
        service_per_task_ms=args.service_per_task_ms,
        batch_max_interactive=args.batch_max_interactive,
        batch_max_batch=args.batch_max_batch,
        batch_wait_interactive_ms=args.batch_wait_interactive_ms,
        batch_wait_batch_ms=args.batch_wait_batch_ms,
        starvation_ms=args.starvation_ms,
        hi_burst=args.hi_burst,
        promote_ms=args.promote_ms,
        adaptive_k=adapt,
        k_mode=args.k_mode,
        k_signal=args.k_signal,
        pending_units=args.pending_units,
        backpressure_units=args.backpressure_units,
        k_scope=args.k_scope,
        admit_policy=args.admit_policy,
        pending_hist_max_depth=args.pending_hist_max_depth,
        sla_interactive_ms=args.sla_interactive_ms,
        sla_batch_ms=args.sla_batch_ms,
        sim_seed=args.sim_seed,
        mtp_draft_len=args.mtp_draft_len,
        mtp_accept_prob=args.mtp_accept_prob,
        mtp_accept_decay=args.mtp_accept_decay,
        mtp_draft_cost_scale=args.mtp_draft_cost_scale,
        mtp_verify_per_draft_cost_scale=args.mtp_verify_per_draft_cost_scale,
        mtp_draft_attempt_policy=args.mtp_draft_attempt_policy,
    )

    replay_mode = (args.trace_jsonl != "" or args.trace_csv != "")
    arrival_units_sim = args.arrival_units.strip().lower() if replay_mode else "steps"

    if len(args.compare) != 0:
        variants: List[Tuple[str, Dict[str, object]]] = []
        for spec in args.compare:
            if ":" not in spec:
                raise SystemExit("--compare expects 'label:JSON' (missing ':')")
            label, js = spec.split(":", 1)
            label = label.strip()
            if label == "":
                raise SystemExit("--compare expects a non-empty label before ':'")
            try:
                overrides = json.loads(js)
            except json.JSONDecodeError as e:
                raise SystemExit(f"--compare JSON parse failed for '{label}': {e}")
            if not isinstance(overrides, dict):
                raise SystemExit(f"--compare JSON for '{label}' must be an object/dict")
            variants.append((label, overrides))
        try:
            if args.summary_json:
                if dump_sim_enabled:
                    out = compare_simulation_summaries_with_dumps(
                        sim_cfg,
                        trace,
                        variants,
                        dump_sim_jsonl_tmpl=dump_sim_jsonl,
                        trace_meta=trace_meta,
                        arrival_units=arrival_units_sim,
                    )
                else:
                    out = compare_simulation_summaries(sim_cfg, trace, variants, arrival_units=arrival_units_sim)
            else:
                if dump_sim_enabled:
                    out = compare_simulation_variants_with_dumps(
                        sim_cfg,
                        trace,
                        variants,
                        dump_sim_jsonl_tmpl=dump_sim_jsonl,
                        trace_meta=trace_meta,
                        arrival_units=arrival_units_sim,
                    )
                else:
                    out = compare_simulation_variants(sim_cfg, trace, variants, arrival_units=arrival_units_sim)
        except (ValueError, OSError) as e:
            raise SystemExit(str(e))
        if len(trace_meta) != 0:
            out["trace_meta"] = trace_meta
    else:
        sim_trace = scale_trace_arrival_units(trace, arrival_units_sim, sim_cfg)
        token_states: List[TokenState] = []
        metrics = run_simulation(sim_cfg, sim_trace, token_states_out=token_states if dump_sim_enabled else None)
        if dump_sim_enabled:
            try:
                dump_path = dump_sim_jsonl.replace("{label}", "baseline") if "{label}" in dump_sim_jsonl else dump_sim_jsonl
                write_sim_jsonl(dump_path, sim_trace, token_states, sim_cfg, meta=trace_meta)
            except (ValueError, OSError) as e:
                raise SystemExit(str(e))
        if args.summary_json:
            out = {"summary": compare_summary_jsonable(metrics)}
            if len(trace_meta) != 0:
                out["trace_meta"] = trace_meta
        else:
            out = metrics.to_jsonable()
            if len(trace_meta) != 0:
                trace_out = out.get("trace")
                if isinstance(trace_out, dict):
                    trace_out["meta"] = trace_meta
    if args.summary_json:
        print(json.dumps(out, sort_keys=True))
        return(0)
    if args.json:
        print(json.dumps(out, sort_keys=True))
        return(0)

    print("== scheduler sim metrics ==")
    print(json.dumps(out, indent=2, sort_keys=True))
    return(0)


if __name__ == "__main__":
    raise SystemExit(main())
