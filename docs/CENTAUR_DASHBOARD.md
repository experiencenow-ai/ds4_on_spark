# Centaur system dashboard

> Last meaningful update: **2026-05-21T22:07Z** (Spark4 back up — three P0 throughput investigations unblocked; Lane D failure analysis found corrected Spark6 73/92 is dominated by 13/19 hard 16000-token truncations; small-model qualification chain complete; track:2 silent and recommended retired)

> **Naming note.** The Centaur vision document names four *workstream components* (factory core, memory domain, providers, product/UI). The coordination system uses agent *track slots* (`track:1`, `track:2`, `track:3`, `track:4`). These are not the same thing despite the unfortunate number overlap. **Any track slot may work on any workstream component.** A track is an agent handle with accumulated PR history; it is not a job description. This dashboard reports component progress; the stall ledger reports per-track-slot behavior.

---


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

## Component 1 — State-machine factory core (overall **45%**)

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

## Component 2 — Memory / Trimind / LongMem domain (overall **40%**)

| Component | % | Status | Source |
|---|---:|---|---|
| Memory codec | 75 | model2vec embeddings (potion-base-8M, 256-dim), IVF-PQ search in C, ktok 18-facet extractor at v8 | `trimind-brain` repo |
| LongMemEval harness | 90 | HWM config (tools-haiku reader, sonnet escalation, opus judge, thinking 10000, sonnet codec) reached 96.6% oracle accuracy | `trimind-brain/tests/longmemeval/bench.py` |
| Brain forest | 80 | Local-module forest in production use; global forest deprecated; integration with thoughtstream live | `trimind-brain` |
| Centaur ⇄ Trimind binding | 15 | Trimind exists as a separate repo, used in development; **no Centaur domain adapter that drives Trimind as a memory subsystem under the state-machine factory** | not built yet |
| LongMem domain adapter for Centaur | 10 | Specified in the vision doc and CENTAUR docs; not implemented | #1195 captures this |

**Bottleneck:** Trimind components are mature, but the Centaur-side adapter that treats LongMem as the first evolution domain is unstarted. This is the gap memory_evolution_alpha closes.

---

## Component 3 — Provider + model portfolio (overall **55%**)

| Tier | % | Provider(s) live | Notes |
|---|---:|---|---|
| `deterministic` | 60 | Internal deterministic tools | Existing test fixtures pass; not formally qualified |
| `local_small` | 55 | **Qualification corpus exists on Spark2** (#1213/#1214 chain merged) — harness + batch + transformers backend (#1239). Router wiring (#1215) pending. |
| `local_coder` | 55 | Same qualification corpus; coding-specialized models present. Router wiring pending. |
| `near_frontier_local` | 60 | **vLLM PP=2 TP=2 on Spark4/5 LIVE** (centaur PR #100, merged 10:54Z). Spark4 currently DOWN since ~11:30Z. Live measured at 106 tok/s c=64. Sweep claimed 310 tok/s — under investigation #1208. |
| `frontier_api` | 50 | Anthropic / OpenAI integration exists | Used by qualification escalation; not load-tested |
| ds4 PP=3 (parity provider) | 35 | Spark0/1/2 layouts; currently Spark2/3/4 due to outage | Logits parity proven (May 16); **economic throughput proven nonviable** (PR #1203 K=618 projection) — **demote to parity-verification only** |
| Strength-reduction routing | 25 | Router structure exists with 5 tiers | Only 1 tier (`near_frontier_local`) has real live qualification; others fictitious until #1200 lands |

**Bottleneck:** Four of five tiers lack real qualification. #1200 captures the qualification work. **The 310 → 106 tok/s vLLM regression (#1208) is the most pressing single number to resolve before downstream economics are correct.**

### DS4 eval calibration

Spark6 PP=1 `ds4-eval` corrected baseline remains the active comparison fixture at 73/92 and 13.896 output tok/s, but #1240's failure analysis changes how to read that number. The executed fixture `fixtures/pipeline_quality/lane-d-pp1-redo-20260521T0412Z.failure_analysis.json` classifies the 19 failures as:

| Failure class | Count | Meaning |
|---|---:|---|
| truncation | 13 | Failed row generated exactly 16000 tokens, the ds4-eval ceiling |
| wrong_answer | 5 | Finished below the ceiling and selected the wrong answer |
| format_error | 1 | Finished below the ceiling but no parseable final answer |
| refusal | 0 | No refusal-pattern failures |

Largest lead: truncation is 13/19 failures, so the 79.3% baseline should be treated as materially affected by eval termination/control, not as a pure model-quality ceiling. By source, failures are AIME2025 10 (9 truncation, 1 format), GPQA Diamond 5 (4 truncation, 1 wrong answer), SuperGPQA 3 (all wrong answer), and COMPSEC 1 (wrong answer).

---

## Component 4 — Product API / UI / debug / release (overall **35%**)

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
| spark-2 | UP | dedicated (qualification done) | Small-model qualification corpus committed; can now host live `local_small`/`local_coder` providers if wired | |
| spark-3 | UP | track:1 | vLLM TP=2 spare / sweep launcher | |
| spark-4 | UP | track:1 | vLLM TP=2 node A | Restored 17:00Z; verify with `ssh spark4 hostname` and `curl /v1/models` before claiming |
| spark-5 | UP | track:1 | vLLM TP=2 node B | |
| spark-6 | UP | track:4 | Isolated ds4-eval baseline | Corrected baseline done (73/92 at 13.9 tok/s); slot free for next claim |

6/7 Sparks online and useful. Spark0/1 remain down; everything else is claimable. The vLLM throughput investigation lane is unblocked.

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

**Small-model qualification workstream (Spark2 dedicated):**
1. #1213 — qualification harness + Spark2 inventory (P1, `hw:spark-2`)
2. #1214 — run harness against all preloaded models (P1, `hw:spark-2`, depends on #1213)
3. #1215 — wire qualified models into Centaur `local_small`/`local_coder` tiers (P1, `hw:none`, depends on #1214)

This chain takes `local_small` and `local_coder` from 30% (no live providers) toward ~75% (qualified models routable). It does not unblock memory_evolution_alpha directly, but **does** make the eventual evolution loop economical: short/trivial nodes route to cheap qualified small models instead of burning vLLM capacity. Strength reduction needs cheap tiers to reduce *to*.

---

## Velocity (recent windows)

| Window | Merges | Highlights |
|---|---:|---|
| 03:00–07:00Z | 5 | vLLM agent: structured-choice bench, config tuning, fanout curve, model cache manifest |
| 09:00–11:00Z | 6 | Coordination protocol (#1201, #1202); MXFP4 audit (#1204); MoE queue projection (#1206); Centaur vLLM binding merged in centaur repo (PR #100); 4 of 4 tracks self-bootstrapped via LANES.md |
| 12:00–16:30Z | **18** | Anti-stall protocol (#1235); track-vs-component fix (#1237); small-model qualification chain complete (#1217/#1221/#1231/#1239); Spark ring deploy automation (#1225); vLLM memory preflight (#1233/#1234); vLLM safe c256 benchmark (#1238); Lane D corrected baseline (#1170: 73/92 at 13.9 tok/s); transformers small-model backend (#1239) |

Average post-protocol cadence: ~4.5 merges/hour vs ~1/hour pre-protocol. Structural intervention worked.

## Stall ledger

Track-by-track behavioral pattern, updated alongside material observation.

| Track slot | Sessions observed | Idle exits | Blocker comments | `/release-stalled` received | Cross-track claims shipped | Notes |
|---|---:|---:|---:|---:|---:|---|
| track:1 | 4 | 0 | 1 (#1218, valid hw block) | 0 | 5+ | Continues as team-player baseline. Claimed #1195 (memory_evolution_alpha) explicitly under updated rules. |
| **track:2** | 2 | 1 | 1 (#1220, valid hw block but no follow-on claim) | 0 | 0 | **Silent for 18 hours after the block. Slot recommended retired.** |
| track:3 | 3 | 1 | 1 | 0 | 4 | Major cross-track movement: deploy automation, small-model qualification, vLLM memory preflight, #1195 unblock check. Naming-collision fix worked. |
| track:4 | 3 | 0 | 0 | 0 | 2 | Corrected baseline (#1170), Spark0 smoke split (#1188), transformers backend (#1239). Multi-area participant. |

**Anti-pattern callouts (resolved):**

- "Posted blocker comment, done" — addressed by 12:00Z anti-stall protocol. Subsequent blocker comments (#1218, #1220) include real raw evidence; #1218 follower claim of #1195 demonstrates the protocol works when followed.
- Refusing to claim outside the "track:N matches workstream N" mental model — addressed by 12:30Z track-vs-component naming fix. Track:3 and Track:4 now actively cross-claim.
- "Stepped outside my track, did one small thing, declared blocked or done" — addressed by partial-work-as-blocker rule.

**Anti-pattern remaining (track:2 only):**

- "Posted blocker comment, did not claim from backlog in same runtime, vanished" — the five-question gate explicitly requires backlog-claim within the same runtime. Track:2's #1220 has Q1–Q4 answered but Q5 (claimed from backlog instead) blank. They were given runtime and did not return. Slot retirement recommended.



- **Component 1:** Centaur evolves a candidate state machine on a domain it hasn't seen before, beats prior baseline by measurable economics, and the win is replayable from the bundle.
- **Component 2:** LongMem oracle accuracy ≥96.6% sustained when reached via a Centaur-orchestrated candidate (not the hand-tuned HWM config).
- **Component 3:** Every router tier has measured cost/quality/latency; strength-reduction routing demonstrably picks the cheapest sufficient tier on a held-out workload.
- **Component 4:** An operator can inspect a run bundle, replay it, compare it to another candidate, and trace why one was promoted — all from the API/UI without reading logs.

---

## How this file is maintained

Updated alongside material progress, not on a schedule. A PR that changes any percentage here must cite the evidence in its body (a commit hash, a fixture file, a merged PR number). Do not edit percentages without that citation.

The percentages are deliberately rough. Use them to spot what's lagging, not as a release gate.
