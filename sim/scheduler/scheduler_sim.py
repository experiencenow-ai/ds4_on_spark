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
class AdaptiveKConfig:
    k_min_interactive: int
    k_max_interactive: int
    k_min_batch: int
    k_max_batch: int
    q_low: int
    q_high: int


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
    k_signal: str = "global"


@dataclass
class Task:
    token_id: int
    cls: LatencyClass
    enqueue_ms: float
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
    hi_burst: int = 0

    def pending(self) -> int:
        return(len(self.hi) + len(self.lo))


class EventKind(enum.IntEnum):
    TOKEN_ARRIVAL = 0
    TASK_DONE = 1


@dataclass(order=True)
class Event:
    t_ms: float
    kind: EventKind
    seq: int
    expert_id: int = -1
    task: Optional[Task] = None


@dataclass
class SimMetrics:
    num_tokens: int = 0
    makespan_ms: float = 0.0
    token_lat_ms_interactive: List[float] = dataclasses.field(default_factory=list)
    token_lat_ms_batch: List[float] = dataclasses.field(default_factory=list)
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

        return(
            {
                "sim": {
                    "num_tokens": self.num_tokens,
                    "makespan_ms": self.makespan_ms,
                    "token_throughput_tps": (float(self.num_tokens) * 1000.0 / self.makespan_ms) if self.makespan_ms > 0.0 else 0.0,
                    "task_throughput_tps": (float(self.admitted_tasks) * 1000.0 / self.makespan_ms) if self.makespan_ms > 0.0 else 0.0,
                },
                "token_latency_ms": {
                    "interactive": summarize(self.token_lat_ms_interactive),
                    "batch": summarize(self.token_lat_ms_batch),
                },
                "tokens": {
                    "admitted": self.admitted_tokens,
                    "admitted_interactive": self.admitted_tokens_interactive,
                    "admitted_batch": self.admitted_tokens_batch,
                    "dropped_backpressure_all": self.dropped_tokens_backpressure,
                    "dropped_backpressure_all_interactive": self.dropped_tokens_backpressure_interactive,
                    "dropped_backpressure_all_batch": self.dropped_tokens_backpressure_batch,
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
                    },
                    "batch": {
                        "count": len(self.chosen_k_batch),
                        "mean": statistics.fmean(self.chosen_k_batch) if len(self.chosen_k_batch) != 0 else 0.0,
                        "min": min(self.chosen_k_batch) if len(self.chosen_k_batch) != 0 else 0,
                        "max": max(self.chosen_k_batch) if len(self.chosen_k_batch) != 0 else 0,
                    },
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

            routes.append(TokenRoute(t_ms=t_ms, cls=cls, candidates=tuple(candidates)))

    routes.sort(key=lambda r: r.t_ms)
    return(routes)


def _clamp_i32(v: int, lo: int, hi: int) -> int:
    if v < lo:
        return(lo)
    if v > hi:
        return(hi)
    return(v)


def choose_k(adapt: AdaptiveKConfig, cls: LatencyClass, max_pending: int) -> int:
    if cls == LatencyClass.INTERACTIVE:
        k_min, k_max = adapt.k_min_interactive, adapt.k_max_interactive
    else:
        k_min, k_max = adapt.k_min_batch, adapt.k_max_batch

    if max_pending <= adapt.q_low:
        return(k_max)
    if max_pending >= adapt.q_high:
        return(k_min)

    span_q = (adapt.q_high - adapt.q_low)
    if span_q <= 0:
        return(_clamp_i32(k_min, k_min, k_max))
    frac = float(max_pending - adapt.q_low) / float(span_q)
    k = int(round(float(k_max) - (frac * float(k_max - k_min))))
    return(_clamp_i32(k, k_min, k_max))


def _start_tasks(now_ms: float, cfg: SimConfig, eq: ExpertQueue, expert_id: int, evq: List[Event], seq_ref: List[int], metrics: SimMetrics) -> None:
    _promote_aged_batch(now_ms, cfg, eq, metrics)
    while eq.in_flight < cfg.expert_parallelism:
        task: Optional[Task] = None
        if len(eq.hi) != 0:
            if cfg.hi_burst > 0 and eq.hi_burst >= cfg.hi_burst and len(eq.lo) != 0:
                task = eq.lo.popleft()
                eq.hi_burst = 0
                metrics.forced_batch_starts += 1
            else:
                task = eq.hi.popleft()
                eq.hi_burst += 1
        elif len(eq.lo) != 0:
            task = eq.lo.popleft()
            eq.hi_burst = 0
        else:
            break

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
        seq_ref[0] += 1
        heapq.heappush(evq, Event(t_ms=(now_ms + cfg.service_ms), kind=EventKind.TASK_DONE, seq=seq_ref[0], expert_id=expert_id, task=task))


def run_simulation(cfg: SimConfig, trace: Sequence[TokenRoute]) -> SimMetrics:
    if cfg.num_experts <= 0:
        raise ValueError("num_experts must be > 0")
    if cfg.expert_parallelism <= 0:
        raise ValueError("expert_parallelism must be > 0")
    if cfg.expert_queue_max <= 0:
        raise ValueError("expert_queue_max must be > 0")
    if cfg.service_ms <= 0.0:
        raise ValueError("service_ms must be > 0")
    if cfg.starvation_ms <= 0.0:
        raise ValueError("starvation_ms must be > 0")
    if cfg.hi_burst < 0:
        raise ValueError("hi_burst must be >= 0")
    if cfg.promote_ms < 0.0:
        raise ValueError("promote_ms must be >= 0")

    k_signal = cfg.k_signal.strip().lower()
    if k_signal not in ("global", "candidates"):
        raise ValueError("k_signal must be 'global' or 'candidates'")

    for route in trace:
        if len(route.candidates) == 0:
            raise ValueError("trace route candidates must be non-empty")
        for expert_id in route.candidates:
            if expert_id < 0 or expert_id >= cfg.num_experts:
                raise ValueError("trace route has expert_id out of range")

    experts: List[ExpertQueue] = [ExpertQueue() for _ in range(cfg.num_experts)]
    tokens: Dict[int, TokenState] = {}
    metrics = SimMetrics(
        num_tokens=len(trace),
        max_pending_per_expert=[0 for _ in range(cfg.num_experts)],
        mean_pending_per_expert=[0.0 for _ in range(cfg.num_experts)],
        mean_utilization_per_expert=[0.0 for _ in range(cfg.num_experts)],
        saturated_time_frac_per_expert=[0.0 for _ in range(cfg.num_experts)],
    )

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
        heapq.heappush(evq, Event(t_ms=route.t_ms, kind=EventKind.TOKEN_ARRIVAL, seq=seq_ref[0], expert_id=-1, task=Task(token_id=tid, cls=route.cls, enqueue_ms=route.t_ms)))
        tokens[tid] = TokenState(cls=route.cls, submit_ms=route.t_ms, chosen_k=0, remaining=0)

    now_ms = 0.0
    snapshot_state()

    while len(evq) != 0:
        ev = heapq.heappop(evq)
        now_ms = ev.t_ms
        integrate_areas(now_ms)

        if ev.kind == EventKind.TOKEN_ARRIVAL:
            tid = ev.task.token_id if ev.task is not None else -1
            route = trace[tid]
            if k_signal == "global":
                max_pending = max(experts[e].pending() for e in range(cfg.num_experts))
            else:
                max_pending = max(experts[e].pending() for e in route.candidates)
            k = choose_k(cfg.adaptive_k, route.cls, max_pending)

            tokens[tid].chosen_k = k
            tokens[tid].remaining = 0
            if route.cls == LatencyClass.INTERACTIVE:
                metrics.chosen_k_interactive.append(k)
            else:
                metrics.chosen_k_batch.append(k)

            admitted = 0
            for expert_id in route.candidates:
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
                task = Task(token_id=tid, cls=route.cls, enqueue_ms=now_ms)
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
                _start_tasks(now_ms, cfg, eq, expert_id, evq, seq_ref, metrics)

            if tokens[tid].remaining == 0:
                metrics.dropped_tokens_backpressure += 1
                if route.cls == LatencyClass.INTERACTIVE:
                    metrics.dropped_tokens_backpressure_interactive += 1
                else:
                    metrics.dropped_tokens_backpressure_batch += 1
                tokens[tid].done_ms = now_ms
            else:
                metrics.admitted_tokens += 1
                if route.cls == LatencyClass.INTERACTIVE:
                    metrics.admitted_tokens_interactive += 1
                else:
                    metrics.admitted_tokens_batch += 1

        elif ev.kind == EventKind.TASK_DONE:
            if ev.task is None:
                raise RuntimeError("TASK_DONE missing task")
            if ev.expert_id < 0 or ev.expert_id >= cfg.num_experts:
                raise RuntimeError("TASK_DONE invalid expert_id")

            eq = experts[ev.expert_id]
            if eq.in_flight <= 0:
                raise RuntimeError("in_flight underflow")
            eq.in_flight -= 1

            tid = ev.task.token_id
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
                else:
                    metrics.token_lat_ms_batch.append(lat_ms)

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
    p.add_argument("--trace-jsonl", type=str, default="", help="Replay routing trace from JSONL file (t_ms, cls, candidates).")
    p.add_argument("--trace-mode", type=str, default="zipf", help="Synthetic trace mode: zipf (default) or hotset.")
    p.add_argument("--num-experts", type=int, default=64)
    p.add_argument("--num-tokens", type=int, default=20000)
    p.add_argument("--num-candidates", type=int, default=16)
    p.add_argument("--interactive-prob", type=float, default=0.3)
    p.add_argument("--arrival-rate-tps", type=float, default=5000.0)
    p.add_argument("--burst-prob", type=float, default=0.05)
    p.add_argument("--burst-scale", type=float, default=8.0)
    p.add_argument("--zipf-alpha", type=float, default=1.1)
    p.add_argument("--hotset-size", type=int, default=8, help="Hotset trace: number of 'hot' experts.")
    p.add_argument("--hotset-bias", type=float, default=0.9, help="Hotset trace: probability a candidate is drawn from the hotset.")
    p.add_argument("--hotset-rotate-every-tokens", type=int, default=2000, help="Hotset trace: rotate hotset every N tokens (0 = never).")
    p.add_argument("--seed", type=int, default=1)

    p.add_argument("--expert-parallelism", type=int, default=2)
    p.add_argument("--expert-queue-max", type=int, default=256)
    p.add_argument("--service-ms", type=float, default=0.15)
    p.add_argument("--starvation-ms", type=float, default=50.0)
    p.add_argument("--hi-burst", type=int, default=0, help="Per-expert fairness: after starting N interactive tasks consecutively, force one batch start if any are queued (0 = strict priority).")
    p.add_argument("--promote-ms", type=float, default=0.0, help="Per-expert aging: promote batch tasks to interactive queue once they wait this long (0 = disabled).")

    p.add_argument("--k-min-interactive", type=int, default=2)
    p.add_argument("--k-max-interactive", type=int, default=4)
    p.add_argument("--k-min-batch", type=int, default=1)
    p.add_argument("--k-max-batch", type=int, default=2)
    p.add_argument("--q-low", type=int, default=16)
    p.add_argument("--q-high", type=int, default=128)
    p.add_argument("--k-signal", type=str, default="global", help="Adaptive-K congestion signal: global (max pending across all experts) or candidates (max pending among this token's candidates).")

    p.add_argument("--json", action="store_true", help="Print JSON metrics only.")
    return(p.parse_args(argv))


def main(argv: Optional[Sequence[str]] = None) -> int:
    args = _parse_args(argv)

    if args.trace_jsonl != "":
        trace = load_trace_jsonl(args.trace_jsonl)
    else:
        mode = args.trace_mode.strip().lower()
        if mode == "zipf":
            trace_cfg = TraceConfig(
                num_tokens=args.num_tokens,
                num_experts=args.num_experts,
                num_candidates=args.num_candidates,
                interactive_prob=args.interactive_prob,
                arrival_rate_tps=args.arrival_rate_tps,
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
                arrival_rate_tps=args.arrival_rate_tps,
                burst_prob=args.burst_prob,
                burst_scale=args.burst_scale,
                hotset_size=args.hotset_size,
                hotset_bias=args.hotset_bias,
                hotset_rotate_every_tokens=args.hotset_rotate_every_tokens,
                seed=args.seed,
            )
            trace = generate_hotset_trace(trace_cfg)
        else:
            raise SystemExit(f"Unknown --trace-mode '{args.trace_mode}'; expected zipf or hotset.")

    adapt = AdaptiveKConfig(
        k_min_interactive=args.k_min_interactive,
        k_max_interactive=args.k_max_interactive,
        k_min_batch=args.k_min_batch,
        k_max_batch=args.k_max_batch,
        q_low=args.q_low,
        q_high=args.q_high,
    )
    sim_cfg = SimConfig(
        num_experts=args.num_experts,
        expert_parallelism=args.expert_parallelism,
        expert_queue_max=args.expert_queue_max,
        service_ms=args.service_ms,
        starvation_ms=args.starvation_ms,
        hi_burst=args.hi_burst,
        promote_ms=args.promote_ms,
        adaptive_k=adapt,
        k_signal=args.k_signal,
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
