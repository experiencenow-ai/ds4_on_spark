# Centaur system dashboard

> Last meaningful update: **2026-05-21T11:00Z** (Claude in chat, after PR #1201/#1202 coordination protocol landed and centaur PR #100 made vLLM the first live local provider)
>
> Percentages are deliberate approximations. They reflect "what fraction of this component is built and working end-to-end against real hardware/data" — not lines of code, not number of files, not roadmap-checklist position. A 70% component means the happy path works for one well-known input; a 90% component means it has been exercised at scale.

---

## The north stars

The Centaur vision doc names two near-term milestones. Everything else exists to enable them.

| Milestone | Progress | What's still required | Tracked |
|---|---:|---|---|
| **live_provider_alpha** — at least one local provider produces real generated tokens at measured speed; Centaur can route a state-machine node through it; the output participates in evaluation and promotion | **70%** | "Participates in evaluation and promotion" requires the evolution loop closure from memory_evolution_alpha | First three sub-bullets done by centaur PR #100 |
| **memory_evolution_alpha** — Centaur runs a no-paid LongMem domain, generates ≥3 candidates, executes through real providers, scores from produced outputs, promotes one, emits replayable bundle the UI can inspect | **20%** | LongMem domain adapter, candidate generation in factory, scoring from outputs, promotion record, replay verification | #1195 (P0 backlog) |

The product target is `a machine that creates machines that solves domains efficiently`. We have the first real provider for those machines to run on; we do not yet have the loop that creates the machines.

---

## Track 1 — State-machine factory core (overall **45%**)

| Component | % | Status | Source |
|---|---:|---|---|
| Candidate generation | 50 | `centaur_state_machine_factory.py` exists with seed/mutation primitives; never exercised on a real domain end-to-end | `centaur_state_machine_factory.py` |
| Node execution dispatch | 65 | Provider gateway routes nodes; works through vLLM live (PR #100), works through fixture providers; ds4 PP=3 path proven economically nonviable (PR #1203) | `centaur_vllm_provider.py`, `centaur_ds4_provider.py` |
| Scoring | 30 | Score-card structure exists, but only fixture-derived scores; **no output-derived scoring against a real domain yet** | `centaur.py` scoring subcommands |
| Mutation | 30 | API surface defined; mutators exist for memory/codec but not validated against domain outcomes | `state-*` subcommands (18 of them) |
| Replay bundle emit | 40 | Bundle format defined; bundles emitted by some procedures; round-trip replay-then-rescore unverified at scale | procedure registry, `procedure-*` subcommands |
| Promotion / rejection | 20 | Single-candidate runs work; multi-candidate compare-and-promote untested against real measured outputs | factory module |

**Bottleneck:** Scoring-from-outputs has never been demonstrated against a real provider for a real domain. Until #1195 lands, the factory is scaffolding plus one route.

---

## Track 2 — Memory / Trimind / LongMem domain (overall **40%**)

| Component | % | Status | Source |
|---|---:|---|---|
| Memory codec | 75 | model2vec embeddings (potion-base-8M, 256-dim), IVF-PQ search in C, ktok 18-facet extractor at v8 | `trimind-brain` repo |
| LongMemEval harness | 90 | HWM config (tools-haiku reader, sonnet escalation, opus judge, thinking 10000, sonnet codec) reached 96.6% oracle accuracy | `trimind-brain/tests/longmemeval/bench.py` |
| Brain forest | 80 | Local-module forest in production use; global forest deprecated; integration with thoughtstream live | `trimind-brain` |
| Centaur ⇄ Trimind binding | 15 | Trimind exists as a separate repo, used in development; **no Centaur domain adapter that drives Trimind as a memory subsystem under the state-machine factory** | not built yet |
| LongMem domain adapter for Centaur | 10 | Specified in the vision doc and CENTAUR docs; not implemented | #1195 captures this |

**Bottleneck:** Trimind components are mature, but the Centaur-side adapter that treats LongMem as the first evolution domain is unstarted. This is the gap memory_evolution_alpha closes.

---

## Track 3 — Provider + model portfolio (overall **45%**)

| Tier | % | Provider(s) live | Notes |
|---|---:|---|---|
| `deterministic` | 60 | Internal deterministic tools | Existing test fixtures pass; not formally qualified |
| `local_small` | 30 | None live | llama.cpp work older; no current binding |
| `local_coder` | 30 | None live | Same; SGLang lane stale |
| `near_frontier_local` | 60 | **vLLM PP=2 TP=2 on Spark4/5 LIVE** (centaur PR #100, merged 10:54Z) | Live measured at 106 tok/s c=64. Sweep claimed 310 tok/s — under investigation #1208. Topline 566 tok/s aggregate at c=512 (PR #1183). |
| `frontier_api` | 50 | Anthropic / OpenAI integration exists | Used by qualification escalation; not load-tested |
| ds4 PP=3 (parity provider) | 35 | Spark0/1/2 layouts; currently Spark2/3/4 due to outage | Logits parity proven (May 16); **economic throughput proven nonviable** (PR #1203 K=618 projection) — **demote to parity-verification only** |
| Strength-reduction routing | 25 | Router structure exists with 5 tiers | Only 1 tier (`near_frontier_local`) has real live qualification; others fictitious until #1200 lands |

**Bottleneck:** Four of five tiers lack real qualification. #1200 captures the qualification work. **The 310 → 106 tok/s vLLM regression (#1208) is the most pressing single number to resolve before downstream economics are correct.**

---

## Track 4 — Product API / UI / debug / release (overall **35%**)

| Component | % | Status |
|---|---:|---|
| Centaur API server | 50 | `CENTAUR_API_SERVER.md` documents the surface; some endpoints implemented; not exposed externally |
| Run inspection / replay | 40 | Replayable bundle concept exists, used by `dogfood-*` subcommands; UI surfacing unclear |
| Debug / complexity gates | 65 | 8 `complexity-*` subcommands, scan/drilldown/gate/calibrate/trend implemented; used in CI for centaur itself |
| Procedure registry / fingerprints | 70 | 35 `procedure-*` subcommands; fingerprint-based repeated-failure detection works |
| Release gating | 20 | No formal release-cut tooling; merges are the de-facto release events |
| Dashboard (this file) | NEW | Living progress view; updated alongside real progress |

**Bottleneck:** No interactive operator view yet — the protocol assumes the human reads PRs and issue comments. That's fine for now.

---

## Hardware capacity (overall **70%**)

| Spark | State | Owner | Role | Notes |
|---|---|---|---|---|
| spark-0 | DOWN | — | — | SSH banner timeout since ~2026-05-20 late |
| spark-1 | DOWN | — | — | Same |
| spark-2 | UP | (free) | PP=3 stage candidate | Available, no current claimant |
| spark-3 | UP | track:1 | vLLM TP=2 spare / sweep launcher | |
| spark-4 | UP | track:1 | vLLM TP=2 node A | Live provider here |
| spark-5 | UP | track:1 | vLLM TP=2 node B | Live provider here |
| spark-6 | UP | track:4 | Isolated ds4-eval baseline | Currently running 92-case eval |

5/7 Sparks online. The two down nodes do not block any critical-path work — vLLM lives on 4/5 and ds4 PP=3 is no longer a production target.

---

## High-level dependency graph

```
                 ┌─────────────────────────────────────────┐
                 │     memory_evolution_alpha (#1195)      │
                 │     20% — depends on three things:      │
                 └──────────────────┬──────────────────────┘
                                    │
       ┌────────────────────────────┼────────────────────────────────┐
       │                            │                                │
       ▼                            ▼                                ▼
┌──────────────┐         ┌────────────────────┐         ┌──────────────────────┐
│ live_provider│         │ LongMem domain      │         │ Output-derived      │
│   _alpha     │         │  adapter            │         │ scoring & promotion │
│   70%        │         │   10%               │         │   25%               │
│   #1192 DONE │         │   not started       │         │   factory: 45%      │
└──────┬───────┘         └──────────┬──────────┘         └──────────────────────┘
       │                            │
       │                            ▼
       │                 ┌────────────────────┐
       │                 │ Trimind ⇄ Centaur  │
       │                 │  binding (15%)     │
       │                 │  not started       │
       │                 └────────────────────┘
       │
   needs accurate
   throughput truth
       │
       ▼
┌──────────────────────────┐    ┌──────────────────────────┐
│ vLLM regression (#1208)  │───▶│ MoE batched queue (#1209)│
│  P0, blocks economics    │    │  P0, up to 3× e2e lever  │
└──────────────────────────┘    └──────────────────────────┘
```

**Critical path to memory_evolution_alpha:**
1. #1208 resolves vLLM throughput truth → unblocks #1191 recommendation
2. #1197 corrects ds4 provider profile → router routes honestly
3. #1195 implements LongMem domain adapter + Centaur ⇄ Trimind binding + output-derived scoring
4. Replayable bundle exercised against real outputs
5. memory_evolution_alpha lands; live_provider_alpha completes its "participates in evaluation and promotion" clause as a side effect

**Critical path to higher provider throughput:**
1. #1208 resolves vLLM regression — produces real baseline
2. #1209 implements MoE batched queue — measured 1.85–3× e2e if projection holds
3. #1198 prefix cache hit rate on Centaur-shaped workload — possible additional multiplier
4. #1196 vLLM PP=3 — possible additional capacity but contested

---

## Velocity (last 8 hours)

| Window | Merges | Highlights |
|---|---:|---|
| 03:00–07:00Z | 5 | vLLM agent: structured-choice bench, config tuning, fanout curve, model cache manifest |
| 09:00–11:00Z | 6 | Coordination protocol (#1201, #1202); MXFP4 audit (#1204); MoE queue projection (#1206); Centaur vLLM binding merged in centaur repo (PR #100); 4 of 4 tracks self-bootstrapped via LANES.md |

Sustained merge cadence since protocol landed: track:1 most productive (3 merges); track:2 silent (needs prompting); track:3 one ready PR (#1203); track:4 cross-repo save on #1192 plus #1194 in flight.

---

## What "100%" would look like for each track

- **Track 1:** Centaur evolves a candidate state machine on a domain it hasn't seen before, beats prior baseline by measurable economics, and the win is replayable from the bundle.
- **Track 2:** LongMem oracle accuracy ≥96.6% sustained when reached via a Centaur-orchestrated candidate (not the hand-tuned HWM config).
- **Track 3:** Every router tier has measured cost/quality/latency; strength-reduction routing demonstrably picks the cheapest sufficient tier on a held-out workload.
- **Track 4:** An operator can inspect a run bundle, replay it, compare it to another candidate, and trace why one was promoted — all from the API/UI without reading logs.

---

## How this file is maintained

Updated alongside material progress, not on a schedule. A PR that changes any percentage here must cite the evidence in its body (a commit hash, a fixture file, a merged PR number). Do not edit percentages without that citation.

The percentages are deliberately rough. Use them to spot what's lagging, not as a release gate.
