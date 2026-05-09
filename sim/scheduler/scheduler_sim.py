#!/usr/bin/env python3
from __future__ import annotations

import argparse
import dataclasses
import enum
import heapq
import json
import math
import random
import statistics
from collections import deque
from dataclasses import dataclass
from typing import Deque, Dict, Iterable, List, Optional, Sequence, Tuple


class LatencyClass(str, enum.Enum):
    INTERACTIVE = "interactive"
    BATCH = "batch"


@dataclass(frozen=True)
class TokenRoute:
    t_ms: float
    cls: LatencyClass
    candidates: Tuple[int, ...]
    k: Optional[int] = None
    scores: Optional[Tuple[float, ...]] = None
    mtp_accept_len: Optional[int] = None
    cost_scale: Optional[float] = None


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
    k_mode: str = "controller"
    k_signal: str = "global"
    admit_policy: str = "ordered"
    pending_hist_max_depth: int = 2048
    sla_interactive_ms: float = 0.0
    sla_batch_ms: float = 0.0
    sim_seed: int = 1
    mtp_draft_len: int = 0
    mtp_accept_prob: float = 0.0
    mtp_accept_decay: float = 1.0
    mtp_draft_cost_scale: float = 0.25
    batch_max_interactive: int = 1
    batch_max_batch: int = 1
    service_base_ms: float = 0.0
    service_per_task_ms: float = -1.0


@dataclass
class Task:
    token_id: int
    cls: LatencyClass
    enqueue_ms: float
    cost_scale: float = 1.0
    start_ms: Optional[float] = None


@dataclass
class TokenState:
    cls: LatencyClass
    submit_ms: float
    chosen_k: int
    remaining: int
    done_ms: Optional[float] = None


@dataclass
class ExpertQueue:
    hi: Deque[Task] = dataclasses.field(default_factory=deque)
    lo: Deque[Task] = dataclasses.field(default_factory=deque)
    in_flight: int = 0
    in_flight_tasks: int = 0
    hi_burst: int = 0

    def pending(self) -> int:
        return(len(self.hi) + len(self.lo) + self.in_flight_tasks)


class EventKind(enum.IntEnum):
    TOKEN_ARRIVAL = 0
    TASK_DONE = 1


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
    token_lat_ms_interactive: List[float] = dataclasses.field(default_factory=list)
    token_lat_ms_batch: List[float] = dataclasses.field(default_factory=list)
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
    chosen_k_interactive: List[int] = dataclasses.field(default_factory=list)
    chosen_k_batch: List[int] = dataclasses.field(default_factory=list)
    k_updates_interactive: int = 0
    k_updates_batch: int = 0
    k_changes_interactive: int = 0
    k_changes_batch: int = 0
    effective_k_interactive: List[int] = dataclasses.field(default_factory=list)
    effective_k_batch: List[int] = dataclasses.field(default_factory=list)
    partial_admit_tokens: int = 0
    partial_admit_tokens_interactive: int = 0
    partial_admit_tokens_batch: int = 0
    admitted_tasks: int = 0
    admitted_tasks_interactive: int = 0
    admitted_tasks_batch: int = 0
    dropped_tasks_backpressure: int = 0
    dropped_tasks_backpressure_interactive: int = 0
    dropped_tasks_backpressure_batch: int = 0
    starved_tasks: int = 0
    starved_tasks_interactive: int = 0
    starved_tasks_batch: int = 0
    promoted_tasks: int = 0
    forced_batch_starts: int = 0
    max_pending_per_expert: List[int] = dataclasses.field(default_factory=list)
    mean_pending_per_expert: List[float] = dataclasses.field(default_factory=list)
    mean_utilization_per_expert: List[float] = dataclasses.field(default_factory=list)
    saturated_time_frac_per_expert: List[float] = dataclasses.field(default_factory=list)
    pending_depth_hist: List[float] = dataclasses.field(default_factory=list)
    pending_depth_hist_overflow: float = 0.0
    mtp_output_tokens: int = 0
    mtp_verify_steps: int = 0
    mtp_draft_len: int = 0
    mtp_accept_prob: float = 0.0
    mtp_accept_decay: float = 1.0
    mtp_draft_tokens_total: int = 0
    mtp_draft_tokens_accepted: int = 0
    mtp_draft_tokens_rejected: int = 0
    mtp_bonus_tokens: int = 0
    mtp_accept_len_per_step: List[int] = dataclasses.field(default_factory=list)
    mtp_pos_attempted: List[int] = dataclasses.field(default_factory=list)
    mtp_pos_accepted: List[int] = dataclasses.field(default_factory=list)

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

        return(
            {
                "sim": {
                    "num_tokens": self.num_tokens,
                    "makespan_ms": self.makespan_ms,
                    "token_throughput_tps": (float(self.num_tokens) * 1000.0 / self.makespan_ms) if self.makespan_ms > 0.0 else 0.0,
                    "task_throughput_tps": (float(self.admitted_tasks) * 1000.0 / self.makespan_ms) if self.makespan_ms > 0.0 else 0.0,
                },
                "trace": {"k_mode": self.k_mode},
                "mtp": {
                    "enabled": self.mtp_draft_len > 0,
                    "output_tokens": self.mtp_output_tokens,
                    "output_token_throughput_tps": (float(self.mtp_output_tokens) * 1000.0 / self.makespan_ms) if self.makespan_ms > 0.0 else 0.0,
                    "verify_steps": self.mtp_verify_steps,
                    "draft_len": self.mtp_draft_len,
                    "accept_prob": self.mtp_accept_prob,
                    "accept_decay": self.mtp_accept_decay,
                    "draft_tokens_total": self.mtp_draft_tokens_total,
                    "draft_tokens_accepted": self.mtp_draft_tokens_accepted,
                    "draft_tokens_rejected": self.mtp_draft_tokens_rejected,
                    "bonus_tokens": self.mtp_bonus_tokens,
                    "accept_len": summarize_ints(self.mtp_accept_len_per_step),
                    "accept_rate": (float(self.mtp_draft_tokens_accepted) / float(self.mtp_draft_tokens_total)) if self.mtp_draft_tokens_total != 0 else 0.0,
                    "per_pos_accept_rate_conditional": [
                        (float(a) / float(t)) if t != 0 else 0.0
                        for t, a in zip(self.mtp_pos_attempted, self.mtp_pos_accepted)
                    ],
                },
                "token_latency_ms": {
                    "interactive": summarize(self.token_lat_ms_interactive),
                    "batch": summarize(self.token_lat_ms_batch),
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
                "effective_k": {
                    "interactive": summarize_ints(self.effective_k_interactive),
                    "batch": summarize_ints(self.effective_k_batch),
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
                    "pending_depth_time_weighted": {
                        "max_depth": (len(self.pending_depth_hist) - 1) if len(self.pending_depth_hist) != 0 else 0,
                        "overflow_time_ms": self.pending_depth_hist_overflow,
                        "p50": hist_int_percentile(self.pending_depth_hist, self.pending_depth_hist_overflow, 0.50),
                        "p95": hist_int_percentile(self.pending_depth_hist, self.pending_depth_hist_overflow, 0.95),
                        "p99": hist_int_percentile(self.pending_depth_hist, self.pending_depth_hist_overflow, 0.99),
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
        eq.hi.append(t0)
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

    rng = random.Random(cfg.seed)
    weights = _zipf_weights(cfg.num_experts, cfg.zipf_alpha)
    routes: List[TokenRoute] = []

    arrivals = _generate_arrival_times_ms(rng, cfg.num_tokens, cfg.arrival_rate_tps, cfg.burst_prob, cfg.burst_scale)
    for t_ms in arrivals:
        cls = LatencyClass.INTERACTIVE if rng.random() < cfg.interactive_prob else LatencyClass.BATCH
        candidates = _sample_unique_ordered(rng, cfg.num_experts, weights, cfg.num_candidates)
        routes.append(TokenRoute(t_ms=t_ms, cls=cls, candidates=candidates))

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

    rng = random.Random(cfg.seed)
    perm = list(range(cfg.num_experts))
    rng.shuffle(perm)

    arrivals = _generate_arrival_times_ms(rng, cfg.num_tokens, cfg.arrival_rate_tps, cfg.burst_prob, cfg.burst_scale)
    routes: List[TokenRoute] = []
    for i, t_ms in enumerate(arrivals):
        hotset = _hotset_for_token(perm, cfg.hotset_size, cfg.hotset_rotate_every_tokens, i)
        cls = LatencyClass.INTERACTIVE if rng.random() < cfg.interactive_prob else LatencyClass.BATCH
        candidates = _sample_hotset_candidates(rng, cfg.num_experts, hotset, cfg.hotset_bias, cfg.num_candidates)
        routes.append(TokenRoute(t_ms=t_ms, cls=cls, candidates=candidates))

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

    rng = random.Random(cfg.seed)
    weights = _zipf_weights(cfg.num_experts, cfg.zipf_alpha)
    arrivals = _generate_arrival_times_ms(rng, cfg.num_tokens, cfg.arrival_rate_tps, cfg.burst_prob, cfg.burst_scale)
    routes: List[TokenRoute] = []

    primary = rng.randrange(0, cfg.num_experts)
    for t_ms in arrivals:
        if rng.random() > cfg.stay_prob:
            primary = rng.choices(range(cfg.num_experts), weights=weights, k=1)[0]
        cls = LatencyClass.INTERACTIVE if rng.random() < cfg.interactive_prob else LatencyClass.BATCH
        others = _sample_unique_ordered_excluding(rng, cfg.num_experts, weights, cfg.num_candidates - 1, excluded=(primary,))
        candidates = (primary,) + others
        routes.append(TokenRoute(t_ms=t_ms, cls=cls, candidates=candidates))

    routes.sort(key=lambda r: r.t_ms)
    return(routes)


def load_trace_jsonl(path: str) -> List[TokenRoute]:
    routes: List[TokenRoute] = []
    with open(path, "r", encoding="utf-8") as f:
        for lineno, line in enumerate(f, 1):
            line = line.strip()
            if line == "":
                continue
            obj = json.loads(line)
            if not isinstance(obj, dict):
                raise ValueError(f"{path}:{lineno}: expected JSON object")

            if "t_ms" not in obj:
                raise ValueError(f"{path}:{lineno}: missing t_ms")
            if "cls" not in obj:
                raise ValueError(f"{path}:{lineno}: missing cls")
            if "candidates" not in obj:
                raise ValueError(f"{path}:{lineno}: missing candidates")

            t_ms = float(obj["t_ms"])
            if t_ms < 0.0:
                raise ValueError(f"{path}:{lineno}: t_ms must be >= 0")

            cls_raw = obj["cls"]
            if not isinstance(cls_raw, str):
                raise ValueError(f"{path}:{lineno}: cls must be a string")
            cls_norm = cls_raw.strip().lower()
            if cls_norm == "interactive":
                cls = LatencyClass.INTERACTIVE
            elif cls_norm == "batch":
                cls = LatencyClass.BATCH
            else:
                raise ValueError(f"{path}:{lineno}: cls must be 'interactive' or 'batch'")

            cand_raw = obj["candidates"]
            if not isinstance(cand_raw, list):
                raise ValueError(f"{path}:{lineno}: candidates must be a JSON list")
            candidates: List[int] = []
            for c in cand_raw:
                if not isinstance(c, int):
                    raise ValueError(f"{path}:{lineno}: candidates must be integers")
                candidates.append(c)
            if len(candidates) == 0:
                raise ValueError(f"{path}:{lineno}: candidates must be non-empty")

            k: Optional[int] = None
            if "k" in obj and obj["k"] is not None:
                k_raw = obj["k"]
                if not isinstance(k_raw, int):
                    raise ValueError(f"{path}:{lineno}: k must be an integer")
                if k_raw <= 0:
                    raise ValueError(f"{path}:{lineno}: k must be > 0")
                k = int(k_raw)

            scores: Optional[Tuple[float, ...]] = None
            if "scores" in obj and obj["scores"] is not None:
                scores_raw = obj["scores"]
                if not isinstance(scores_raw, list):
                    raise ValueError(f"{path}:{lineno}: scores must be a JSON list")
                if len(scores_raw) != len(candidates):
                    raise ValueError(f"{path}:{lineno}: scores must have same length as candidates")
                scores_list: List[float] = []
                for s in scores_raw:
                    if not isinstance(s, (int, float)):
                        raise ValueError(f"{path}:{lineno}: scores must be numbers")
                    scores_list.append(float(s))
                scores = tuple(scores_list)

            mtp_accept_len: Optional[int] = None
            if "mtp_accept_len" in obj and obj["mtp_accept_len"] is not None:
                al_raw = obj["mtp_accept_len"]
                if not isinstance(al_raw, int):
                    raise ValueError(f"{path}:{lineno}: mtp_accept_len must be an integer")
                if al_raw < 1:
                    raise ValueError(f"{path}:{lineno}: mtp_accept_len must be >= 1")
                mtp_accept_len = int(al_raw)

            cost_scale: Optional[float] = None
            if "cost_scale" in obj and obj["cost_scale"] is not None:
                cs_raw = obj["cost_scale"]
                if not isinstance(cs_raw, (int, float)):
                    raise ValueError(f"{path}:{lineno}: cost_scale must be a number")
                if float(cs_raw) <= 0.0:
                    raise ValueError(f"{path}:{lineno}: cost_scale must be > 0")
                cost_scale = float(cs_raw)

            routes.append(
                TokenRoute(
                    t_ms=t_ms,
                    cls=cls,
                    candidates=tuple(candidates),
                    k=k,
                    scores=scores,
                    mtp_accept_len=mtp_accept_len,
                    cost_scale=cost_scale,
                )
            )

    routes.sort(key=lambda r: r.t_ms)
    return(routes)


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


def _candidate_order(admit_policy: str, experts: Sequence[ExpertQueue], route: TokenRoute) -> Sequence[int]:
    if admit_policy == "ordered":
        return(route.candidates)
    if admit_policy == "least_pending":
        ranked = [(experts[e].pending(), i, e) for i, e in enumerate(route.candidates)]
        ranked.sort()
        return([e for _p, _i, e in ranked])
    if admit_policy == "score_desc":
        if route.scores is None:
            raise ValueError("admit_policy score_desc requires per-candidate scores")
        ranked = [(-float(route.scores[i]), i, e) for i, e in enumerate(route.candidates)]
        ranked.sort()
        return([e for _s, _i, e in ranked])
    raise ValueError("admit_policy must be 'ordered', 'least_pending', or 'score_desc'")


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

        n = min(batch_max, len(q))
        tasks: List[Task] = []
        for _i in range(n):
            tasks.append(q.popleft())
        if len(tasks) == 0:
            break

        if serving_hi:
            eq.hi_burst += len(tasks)
        else:
            eq.hi_burst = 0

        for task in tasks:
            wait_ms = (now_ms - task.enqueue_ms)
            if wait_ms >= cfg.starvation_ms:
                metrics.starved_tasks += 1
                if task.cls == LatencyClass.INTERACTIVE:
                    metrics.starved_tasks_interactive += 1
                else:
                    metrics.starved_tasks_batch += 1
            if task.cls == LatencyClass.INTERACTIVE:
                metrics.task_queue_wait_ms_interactive.append(wait_ms)
            else:
                metrics.task_queue_wait_ms_batch.append(wait_ms)
            task.start_ms = now_ms

        eq.in_flight += 1
        eq.in_flight_tasks += len(tasks)
        seq_ref[0] += 1
        heapq.heappush(evq, Event(t_ms=(now_ms + _service_time_tasks_ms(cfg, tasks)), kind=EventKind.TASK_DONE, seq=seq_ref[0], expert_id=expert_id, tasks=tuple(tasks)))


def _sample_mtp_accept_len(cfg: SimConfig, rng: random.Random, metrics: SimMetrics) -> int:
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
    for i in range(draft_len):
        metrics.mtp_pos_attempted[i] += 1
        p = (cfg.mtp_accept_prob * (cfg.mtp_accept_decay ** float(i)))
        if p >= 1.0 or rng.random() < p:
            metrics.mtp_pos_accepted[i] += 1
            accepted_draft += 1
        else:
            break

    metrics.mtp_draft_tokens_total += draft_len
    metrics.mtp_draft_tokens_accepted += accepted_draft
    metrics.mtp_draft_tokens_rejected += (draft_len - accepted_draft)
    if accepted_draft == draft_len:
        metrics.mtp_bonus_tokens += 1
        return(draft_len + 1)
    return(accepted_draft + 1)


def _record_mtp_accept_len(cfg: SimConfig, metrics: SimMetrics, accept_len: int) -> None:
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

    metrics.mtp_draft_tokens_total += draft_len
    metrics.mtp_draft_tokens_accepted += accepted_draft
    metrics.mtp_draft_tokens_rejected += (draft_len - accepted_draft)
    if accept_len == (draft_len + 1):
        metrics.mtp_bonus_tokens += 1


def _choose_mtp_accept_len(cfg: SimConfig, rng: random.Random, metrics: SimMetrics, route: TokenRoute) -> int:
    if cfg.mtp_draft_len <= 0:
        return(1)
    if route.mtp_accept_len is not None:
        accept_len = int(route.mtp_accept_len)
        if accept_len < 1 or accept_len > (cfg.mtp_draft_len + 1):
            raise ValueError("trace route mtp_accept_len out of range for configured mtp_draft_len")
        return(accept_len)
    return(_sample_mtp_accept_len(cfg, rng, metrics))


def run_simulation(cfg: SimConfig, trace: Sequence[TokenRoute]) -> SimMetrics:
    if cfg.num_experts <= 0:
        raise ValueError("num_experts must be > 0")
    if cfg.expert_parallelism <= 0:
        raise ValueError("expert_parallelism must be > 0")
    if cfg.expert_queue_max <= 0:
        raise ValueError("expert_queue_max must be > 0")
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
    if k_signal not in ("global", "candidates"):
        raise ValueError("k_signal must be 'global' or 'candidates'")

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
        if cfg.mtp_accept_prob < 0.0 or cfg.mtp_accept_prob > 1.0:
            raise ValueError("mtp_accept_prob must be within [0,1]")
        if cfg.mtp_accept_decay <= 0.0:
            raise ValueError("mtp_accept_decay must be > 0")
        if cfg.mtp_draft_cost_scale <= 0.0:
            raise ValueError("mtp_draft_cost_scale must be > 0")

    for route in trace:
        if len(route.candidates) == 0:
            raise ValueError("trace route candidates must be non-empty")
        if route.cost_scale is not None and float(route.cost_scale) <= 0.0:
            raise ValueError("trace route cost_scale must be > 0")
        if route.k is not None:
            if route.k <= 0:
                raise ValueError("trace route k must be > 0")
            if route.k > len(route.candidates):
                raise ValueError("trace route k must be <= len(candidates)")
        if k_mode == "trace" and route.k is None:
            raise ValueError("k_mode trace requires per-route k in the trace")
        if route.scores is not None and len(route.scores) != len(route.candidates):
            raise ValueError("trace route scores must have same length as candidates")
        if admit_policy == "score_desc" and route.scores is None:
            raise ValueError("admit_policy score_desc requires scores on every trace route")
        if route.mtp_accept_len is not None and cfg.mtp_draft_len <= 0:
            raise ValueError("trace route mtp_accept_len requires mtp_draft_len > 0")
        for expert_id in route.candidates:
            if expert_id < 0 or expert_id >= cfg.num_experts:
                raise ValueError("trace route has expert_id out of range")

    experts: List[ExpertQueue] = [ExpertQueue() for _ in range(cfg.num_experts)]
    tokens: Dict[int, TokenState] = {}
    hist_len = 0
    if cfg.pending_hist_max_depth > 0:
        hist_len = min(cfg.pending_hist_max_depth, cfg.expert_queue_max) + 1
    metrics = SimMetrics(
        num_tokens=len(trace),
        k_mode=k_mode,
        max_pending_per_expert=[0 for _ in range(cfg.num_experts)],
        mean_pending_per_expert=[0.0 for _ in range(cfg.num_experts)],
        mean_utilization_per_expert=[0.0 for _ in range(cfg.num_experts)],
        saturated_time_frac_per_expert=[0.0 for _ in range(cfg.num_experts)],
        pending_depth_hist=[0.0 for _ in range(hist_len)] if hist_len != 0 else [],
        pending_depth_hist_overflow=0.0,
    )
    rng = random.Random(cfg.sim_seed)
    if cfg.mtp_draft_len > 0:
        metrics.mtp_verify_steps = len(trace)
        metrics.mtp_draft_len = cfg.mtp_draft_len
        metrics.mtp_accept_prob = cfg.mtp_accept_prob
        metrics.mtp_accept_decay = cfg.mtp_accept_decay
        metrics.mtp_pos_attempted = [0 for _ in range(cfg.mtp_draft_len)]
        metrics.mtp_pos_accepted = [0 for _ in range(cfg.mtp_draft_len)]

    k_ctrl: Dict[LatencyClass, KControllerState] = {LatencyClass.INTERACTIVE: KControllerState(), LatencyClass.BATCH: KControllerState()}

    # Time-weighted pending depth: integral pending(t) dt / makespan.
    pending_area: List[float] = [0.0 for _ in range(cfg.num_experts)]
    inflight_area: List[float] = [0.0 for _ in range(cfg.num_experts)]
    saturated_area: List[float] = [0.0 for _ in range(cfg.num_experts)]
    last_t_ms = 0.0
    last_pending: List[int] = [0 for _ in range(cfg.num_experts)]
    last_inflight: List[int] = [0 for _ in range(cfg.num_experts)]
    last_saturated: List[int] = [0 for _ in range(cfg.num_experts)]

    def integrate_areas(now_ms: float) -> None:
        nonlocal last_t_ms
        dt = (now_ms - last_t_ms)
        if dt < 0.0:
            raise RuntimeError("time went backwards")
        if dt != 0.0:
            for e in range(cfg.num_experts):
                pending_area[e] += (float(last_pending[e]) * dt)
                inflight_area[e] += (float(last_inflight[e]) * dt)
                saturated_area[e] += (float(last_saturated[e]) * dt)
                if hist_len != 0:
                    depth = last_pending[e]
                    if depth >= hist_len:
                        metrics.pending_depth_hist_overflow += dt
                    else:
                        metrics.pending_depth_hist[depth] += dt
        last_t_ms = now_ms

    def snapshot_state() -> None:
        for e in range(cfg.num_experts):
            last_pending[e] = experts[e].pending()
            last_inflight[e] = experts[e].in_flight
            last_saturated[e] = 1 if last_pending[e] >= cfg.expert_queue_max else 0
            if last_pending[e] > metrics.max_pending_per_expert[e]:
                metrics.max_pending_per_expert[e] = last_pending[e]

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
        tokens[tid] = TokenState(cls=route.cls, submit_ms=route.t_ms, chosen_k=0, remaining=0)

    now_ms = 0.0
    snapshot_state()

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
            if k_mode == "trace":
                k = int(route.k or 0)
            else:
                if k_signal == "global":
                    pending_signal = float(max(experts[e].pending() for e in range(cfg.num_experts)))
                else:
                    pending_signal = float(max(experts[e].pending() for e in route.candidates))

                cs = k_ctrl[route.cls]
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
                    k_target = choose_k(cfg.adaptive_k, route.cls, cs.ema_pending)
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
                    if route.cls == LatencyClass.INTERACTIVE:
                        metrics.k_updates_interactive += 1
                        if prev_k != 0 and cs.k != prev_k:
                            metrics.k_changes_interactive += 1
                    else:
                        metrics.k_updates_batch += 1
                        if prev_k != 0 and cs.k != prev_k:
                            metrics.k_changes_batch += 1

                k = cs.k

            tokens[tid].chosen_k = k
            tokens[tid].remaining = 0
            if route.cls == LatencyClass.INTERACTIVE:
                metrics.chosen_k_interactive.append(k)
            else:
                metrics.chosen_k_batch.append(k)

            admitted = 0
            admitted_verify = 0
            micro_tokens = (cfg.mtp_draft_len + 1) if mtp_enabled else 1
            accept_len = 1
            if mtp_enabled:
                accept_len = _choose_mtp_accept_len(cfg, rng, metrics, route)

            for micro_i in range(micro_tokens):
                base_cost_scale = float(route.cost_scale) if route.cost_scale is not None else 1.0
                cost_scale = base_cost_scale
                if mtp_enabled and micro_i < cfg.mtp_draft_len:
                    cost_scale *= cfg.mtp_draft_cost_scale

                admitted = 0
                for expert_id in _candidate_order(admit_policy, experts, route):
                    if admitted >= k:
                        break
                    eq = experts[expert_id]
                    if eq.pending() >= cfg.expert_queue_max:
                        metrics.dropped_tasks_backpressure += 1
                        if route.cls == LatencyClass.INTERACTIVE:
                            metrics.dropped_tasks_backpressure_interactive += 1
                        else:
                            metrics.dropped_tasks_backpressure_batch += 1
                        continue
                    task = Task(token_id=tid, cls=route.cls, enqueue_ms=now_ms, cost_scale=cost_scale)
                    if route.cls == LatencyClass.INTERACTIVE:
                        eq.hi.append(task)
                    else:
                        eq.lo.append(task)
                    tokens[tid].remaining += 1
                    metrics.admitted_tasks += 1
                    if route.cls == LatencyClass.INTERACTIVE:
                        metrics.admitted_tasks_interactive += 1
                    else:
                        metrics.admitted_tasks_batch += 1
                    admitted += 1
                    if (not mtp_enabled) or micro_i == cfg.mtp_draft_len:
                        admitted_verify += 1
                    _start_tasks(now_ms, cfg, eq, expert_id, evq, seq_ref, metrics)

            if tokens[tid].remaining == 0:
                metrics.dropped_tokens_backpressure += 1
                if route.cls == LatencyClass.INTERACTIVE:
                    metrics.dropped_tokens_backpressure_interactive += 1
                else:
                    metrics.dropped_tokens_backpressure_batch += 1
                tokens[tid].done_ms = now_ms
                if mtp_enabled:
                    metrics.mtp_accept_len_per_step.append(0)
            else:
                metrics.admitted_tokens += 1
                if route.cls == LatencyClass.INTERACTIVE:
                    metrics.admitted_tokens_interactive += 1
                    metrics.effective_k_interactive.append(admitted_verify)
                else:
                    metrics.admitted_tokens_batch += 1
                    metrics.effective_k_batch.append(admitted_verify)
                desired = min(k, len(route.candidates))
                if admitted_verify < desired:
                    metrics.partial_admit_tokens += 1
                    if route.cls == LatencyClass.INTERACTIVE:
                        metrics.partial_admit_tokens_interactive += 1
                    else:
                        metrics.partial_admit_tokens_batch += 1
                if mtp_enabled:
                    if route.mtp_accept_len is not None and admitted_verify > 0:
                        _record_mtp_accept_len(cfg, metrics, accept_len)
                    if admitted_verify == 0:
                        metrics.mtp_accept_len_per_step.append(0)
                    else:
                        metrics.mtp_accept_len_per_step.append(accept_len)
                        metrics.mtp_output_tokens += accept_len

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

            for task in ev.tasks:
                tid = task.token_id
                if tid not in tokens:
                    raise RuntimeError("unknown token_id")
                ts = tokens[tid]
                if ts.remaining <= 0:
                    raise RuntimeError("token remaining underflow")
                ts.remaining -= 1
                if ts.remaining == 0 and ts.done_ms is None:
                    ts.done_ms = now_ms
                    lat_ms = (now_ms - ts.submit_ms)
                    if ts.cls == LatencyClass.INTERACTIVE:
                        metrics.token_lat_ms_interactive.append(lat_ms)
                        if cfg.sla_interactive_ms > 0.0 and lat_ms > cfg.sla_interactive_ms:
                            metrics.token_sla_violations_interactive += 1
                    else:
                        metrics.token_lat_ms_batch.append(lat_ms)
                        if cfg.sla_batch_ms > 0.0 and lat_ms > cfg.sla_batch_ms:
                            metrics.token_sla_violations_batch += 1

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
        metrics.mean_utilization_per_expert[e] = (inflight_area[e] / (makespan_ms * float(cfg.expert_parallelism)))
        metrics.saturated_time_frac_per_expert[e] = (saturated_area[e] / makespan_ms)
    return(metrics)


def _parse_args(argv: Optional[Sequence[str]] = None) -> argparse.Namespace:
    p = argparse.ArgumentParser(description="Host-only scheduler simulator (synthetic routing traces).")
    p.add_argument("--trace-jsonl", type=str, default="", help="Replay routing trace from JSONL file (t_ms, cls, candidates; optional k, scores, mtp_accept_len, cost_scale).")
    p.add_argument("--trace-mode", type=str, default="zipf", help="Synthetic trace mode: zipf (default), hotset, or markov.")
    p.add_argument("--num-experts", type=int, default=64)
    p.add_argument("--num-tokens", type=int, default=20000)
    p.add_argument("--num-candidates", type=int, default=16)
    p.add_argument("--interactive-prob", type=float, default=0.3)
    p.add_argument("--arrival-rate-tps", type=float, default=5000.0)
    p.add_argument("--arrival-units", type=str, default="steps", help="Interpret --arrival-rate-tps as steps (verify steps) or output_tokens (rescale by expected MTP accept length when enabled). Synthetic traces only.")
    p.add_argument("--burst-prob", type=float, default=0.05)
    p.add_argument("--burst-scale", type=float, default=8.0)
    p.add_argument("--zipf-alpha", type=float, default=1.1)
    p.add_argument("--hotset-size", type=int, default=8, help="Hotset trace: number of 'hot' experts.")
    p.add_argument("--hotset-bias", type=float, default=0.9, help="Hotset trace: probability a candidate is drawn from the hotset.")
    p.add_argument("--hotset-rotate-every-tokens", type=int, default=2000, help="Hotset trace: rotate hotset every N tokens (0 = never).")
    p.add_argument("--markov-stay-prob", type=float, default=0.9, help="Markov trace: probability to reuse previous token's primary expert.")
    p.add_argument("--seed", type=int, default=1)

    p.add_argument("--expert-parallelism", type=int, default=2)
    p.add_argument("--expert-queue-max", type=int, default=256)
    p.add_argument("--service-ms", type=float, default=0.15)
    p.add_argument("--service-base-ms", type=float, default=0.0, help="Batch service model: fixed overhead per started expert batch.")
    p.add_argument("--service-per-task-ms", type=float, default=-1.0, help="Batch service model: incremental cost per task in a started expert batch (-1 = use --service-ms).")
    p.add_argument("--batch-max-interactive", type=int, default=1, help="Max tasks started per expert batch for interactive queue (1 = no batching).")
    p.add_argument("--batch-max-batch", type=int, default=1, help="Max tasks started per expert batch for batch queue (1 = no batching).")
    p.add_argument("--starvation-ms", type=float, default=50.0)
    p.add_argument("--hi-burst", type=int, default=0, help="Per-expert fairness: after starting N interactive tasks consecutively, force one batch start if any are queued (0 = strict priority).")
    p.add_argument("--promote-ms", type=float, default=0.0, help="Per-expert aging: promote batch tasks to interactive queue once they wait this long (0 = disabled).")
    p.add_argument("--sla-interactive-ms", type=float, default=0.0, help="Token SLA: count interactive tokens with latency > this (0 = disabled).")
    p.add_argument("--sla-batch-ms", type=float, default=0.0, help="Token SLA: count batch tokens with latency > this (0 = disabled).")
    p.add_argument("--sim-seed", type=int, default=1, help="Simulation seed (used for MTP accept/reject sampling).")
    p.add_argument("--mtp-draft-len", type=int, default=0, help="MTP: number of draft tokens per verify step (0 = disabled).")
    p.add_argument("--mtp-accept-prob", type=float, default=0.0, help="MTP: conditional accept probability for draft position 0 (within [0,1]).")
    p.add_argument("--mtp-accept-decay", type=float, default=1.0, help="MTP: conditional accept probability decay factor per draft position (>0, <1 biases early accept).")
    p.add_argument("--mtp-draft-cost-scale", type=float, default=0.25, help="MTP: per-task cost scaling for draft tokens relative to verify tokens (>0).")

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
    p.add_argument("--k-signal", type=str, default="global", help="Adaptive-K congestion signal: global (max pending across all experts) or candidates (max pending among this token's candidates).")
    p.add_argument("--admit-policy", type=str, default="ordered", help="Candidate admission policy: ordered (router order), least_pending (pick least pending experts among candidates), or score_desc (order candidates by descending trace scores).")
    p.add_argument("--pending-hist-max-depth", type=int, default=2048, help="Time-weighted pending-depth percentiles: cap histogram depth at this value (0 = disable).")

    p.add_argument("--json", action="store_true", help="Print JSON metrics only.")
    return(p.parse_args(argv))


def main(argv: Optional[Sequence[str]] = None) -> int:
    args = _parse_args(argv)

    if args.trace_jsonl != "":
        if args.arrival_units.strip().lower() != "steps":
            raise SystemExit("--arrival-units is only supported for synthetic trace generation (omit --trace-jsonl)")
        trace = load_trace_jsonl(args.trace_jsonl)
    else:
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
            )
            trace = generate_markov_trace(trace_cfg)
        else:
            raise SystemExit(f"Unknown --trace-mode '{args.trace_mode}'; expected zipf, hotset, or markov.")

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
        service_ms=args.service_ms,
        service_base_ms=args.service_base_ms,
        service_per_task_ms=args.service_per_task_ms,
        batch_max_interactive=args.batch_max_interactive,
        batch_max_batch=args.batch_max_batch,
        starvation_ms=args.starvation_ms,
        hi_burst=args.hi_burst,
        promote_ms=args.promote_ms,
        adaptive_k=adapt,
        k_mode=args.k_mode,
        k_signal=args.k_signal,
        admit_policy=args.admit_policy,
        pending_hist_max_depth=args.pending_hist_max_depth,
        sla_interactive_ms=args.sla_interactive_ms,
        sla_batch_ms=args.sla_batch_ms,
        sim_seed=args.sim_seed,
        mtp_draft_len=args.mtp_draft_len,
        mtp_accept_prob=args.mtp_accept_prob,
        mtp_accept_decay=args.mtp_accept_decay,
        mtp_draft_cost_scale=args.mtp_draft_cost_scale,
    )

    metrics = run_simulation(sim_cfg, trace)
    out = metrics.to_jsonable()
    if args.json:
        print(json.dumps(out, sort_keys=True))
        return(0)

    print("== scheduler sim metrics ==")
    print(json.dumps(out, indent=2, sort_keys=True))
    return(0)


if __name__ == "__main__":
    raise SystemExit(main())
