# Centaur system dashboard

> **Specification:** [`docs/CENTAUR_SPECIFICATION.md`](CENTAUR_SPECIFICATION.md) — system modules, end-state walkthrough, what "done" looks like. This dashboard reports progress against that spec.

> Last meaningful update: **2026-05-22T13:30Z** (hardware-bound-to-tasks restructure: per-node `hw:spark-N` labels become reservations held by status:in-progress issues; composite labels deprecated; LANES.md decision tree updated; `lane_hardware_free.sh` reports live reservation state; dashboard hardware count corrected to 8/8 nodes available)

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

## Component 1 — State-machine factory core (overall **65%**)

| Module (spec §6) | % | Status | Evidence |
|---|---:|---|---|
| 1 Domain definition | 70 | `centaur domain submit` validator merged | centaur PR #105 |
| 2 Node library | 55 | LongMem node primitives merged; type sigs + cost models still partial | centaur PR #107 |
| 3 SM representation | 60 | LongMem state-machine JSON schema validator merged | centaur PR #106 |
| 4 Candidate generator | 55 | LongMem HWM-seed generator + 5 single-axis mutations | centaur PR #108 |
| 5 Mutator | 50 | LongMem mutation operators (5) merged | centaur PR #109 |
| 6 Executor | 60 | LongMem fixture candidate executor merged; live executor pending Module 7 router | centaur PR #110 |
| 7 Model router (LongMem-aware) | 30 | Issue #1272 filed; needs to wire all 3 live tiers | open |
| 8 Evaluator | 25 | Issue #1273 filed; will wrap bench.py judge | open |
| 9 Promoter | 10 | Issue #1274 filed; not started | open |
| 10 Replay bundle | 35 | Issue #1275 filed; procedure bundles exist; SM-run bundles do not | open |
| 14 Budget control | 25 | Issue #1276 filed; current state is loose gates | open |

**Bottleneck:** Modules 7-9 must land in order before a first generation can produce a real score. Module 14 must land before any live evolution runs; the 500-question batch is too expensive to run without budget guarantees.

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

## Component 3 — Provider + model portfolio (overall **60%**)

| Tier | % | Provider(s) live | Notes |
|---|---:|---|---|
| `deterministic` | 60 | Internal deterministic tools | Existing test fixtures pass; not formally qualified |
| `local_small` | 45 | Corpus exists on Spark2 (#1213/#1214/#1239) — all 53 status=passed records across 91 attempts have derivable executed-run tok/s in `fixtures/small_model_qualification/throughput_addendum_20260523.json`. Fastest local-small candidates: `hf-deepseek-ai-DeepSeek-R1-Distill-Qwen-1.5B` at 40.747 tok/s and `hf-Qwen-Qwen3.5-0.8B` at 40.219 tok/s. Router wiring still pending. |
| `local_coder` | 45 | Same corpus; coding-specialized models present with throughput addendum coverage. Best correctness+throughput coder row in the addendum is `hf-Qwen-Qwen3.5-2B` at 24.794 tok/s with pass_rate 1.0; `hf-zai-org-SWE-Dev-7B` and `hf-zai-org-SWE-Dev-32B` also passed the eval prompts at 6.596 and 2.861 tok/s. Router wiring still pending. |
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

## Hardware capacity (overall **90%**)

There are **8 Sparks**, all on the 200G ring, all up. Reservations are owned by *issues*, not agents. A Spark is reserved when an open `status:in-progress` issue carries its `hw:spark-N` label; otherwise it's free.

| Spark | Hardware | Reservation state | Role / capability | Notes |
|---|---|---|---|---|
| spark-0 | Gigabyte GB10 | free | PP=3-A layout member | Restored from 5/20-5/21 outage; canonical SSH path via 200G proxy |
| spark-1 | MSI mini-PC GB10 | free | PP=3-A layout member | Distinct hardware family from the Gigabytes — useful for cross-family variance testing |
| spark-2 | Gigabyte GB10 | free | Small-model host | ~32 distinct models preloaded; correctness qualified, throughput pending (#1294) |
| spark-3 | Gigabyte GB10 | free | vLLM TP=2 / PP=N member | Also serves as sweep launcher when paired with 4/5 |
| spark-4 | Gigabyte GB10 | free | vLLM TP=2 / PP=N member | Restored 17:00Z 2026-05-21; verify with `ssh spark4 hostname` before claiming |
| spark-5 | Gigabyte GB10 | free | vLLM TP=2 / PP=N member | |
| spark-6 | Gigabyte GB10 | free | ds4-eval baseline host | Lane D 73/92 baseline done; available for next ds4-eval-shaped work (#1296) |
| spark-7 | Lenovo ThinkStation PGX-1449 | free (Codex auth pending) | LongMem evaluator candidate | SSH from Mac works; Codex direct-SSH key auth still to deploy. Mac-driven workloads can use it now. |

**All 8 Sparks are physically deployed and reachable.** Run `scripts/lane_hardware_free.sh` to get the live reservation state.

The Codex-auth-pending note on Spark7 means: agents running on the Mac can reach Spark7 via existing SSH paths; if a workflow specifically requires a Codex container ON a Spark to ssh into Spark7, that direct path still needs the auth deployment. Most Centaur workloads do not need that — the Mac orchestrates and the Spark just executes.

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
| 03:00–07:00Z (5/21) | 5 | vLLM agent: structured-choice bench, config tuning, fanout curve, model cache manifest |
| 09:00–11:00Z (5/21) | 6 | Coordination protocol (#1201, #1202); MXFP4 audit (#1204); MoE queue projection (#1206); Centaur vLLM binding merged (PR #100); 4 of 4 tracks self-bootstrapped via LANES.md |
| 12:00–16:30Z (5/21) | 18 | Anti-stall protocol (#1235); track-vs-component fix (#1237); small-model qualification chain complete; Lane D corrected baseline 73/92 |
| 23:00Z–09:30Z (5/22) | **~14** | Spec v1.1 merged (#1249); Spark7 added; 200G fabric pinned for distributed providers (#1259); PP=4 ring measured (#1269 — same throughput as PP=2 at c=256, PP=2 stays production); **6 of 11 LongMem critical-path modules merged in centaur (PRs #105, #106, #107, #108, #109, #110)**; track:2 revived with 4 of those 6 |

Average post-protocol cadence: still ~4-5 merges/hour. Spec-derived backlog is now driving most of the work; tactical issues (#1208 vLLM regression, #1209 MoE queue) deferred to opportunistic claim.

## Stall ledger

Track-by-track behavioral pattern, updated alongside material observation.

| Track slot | Sessions observed | Idle exits | Blocker comments | `/release-stalled` received | Cross-track claims shipped | Notes |
|---|---:|---:|---:|---:|---:|---|
| track:1 | 5 | 0 | 1 (#1218, valid hw block) | 0 | 7+ | Continues as team-player baseline. Claimed and managed the #1258 LongMem umbrella; landed Modules 1 & 3 (centaur PRs #105, #106). |
| **track:2** | 4 | 1 | 1 (#1220, valid hw block) | 0 | **5** | **Revived. Productivity star of the 09:30Z cycle.** Shipped centaur PRs #107, #108, #109, #110 (Modules 2, 4, 5, 6) plus #1262 (Spark reachability artifact). Slot retirement recommendation rescinded. |
| track:3 | 4 | 1 | 1 | 0 | 4 | Cross-track movement continues: PR #1271 in-flight on vLLM PP=3 network fallback measurement. |
| track:4 | 4 | 0 | 0 | 0 | 3 | PR #1170 corrected baseline + #1265/#1266 closed-ring topology work + Spark7 topology updates. |

**Anti-pattern callouts (resolved):**

- "Posted blocker comment, done" — addressed by 12:00Z anti-stall protocol. Blocker comments (#1218, #1220) include real raw evidence with proper follow-on claims.
- Refusing to claim outside the "track:N matches workstream N" mental model — addressed by 12:30Z track-vs-component naming fix. All four tracks now actively cross-claim.
- "Stepped outside my track, did one small thing, declared blocked or done" — addressed by partial-work-as-blocker rule.
- "Track silent across multiple sessions" — track:2 specifically reversed this; the slot is now productive.



- **Component 1:** Centaur evolves a candidate state machine on a domain it hasn't seen before, beats prior baseline by measurable economics, and the win is replayable from the bundle.
- **Component 2:** LongMem oracle accuracy ≥96.6% sustained when reached via a Centaur-orchestrated candidate (not the hand-tuned HWM config).
- **Component 3:** Every router tier has measured cost/quality/latency; strength-reduction routing demonstrably picks the cheapest sufficient tier on a held-out workload.
- **Component 4:** An operator can inspect a run bundle, replay it, compare it to another candidate, and trace why one was promoted — all from the API/UI without reading logs.

---

## How this file is maintained

Updated alongside material progress, not on a schedule. A PR that changes any percentage here must cite the evidence in its body (a commit hash, a fixture file, a merged PR number). Do not edit percentages without that citation.

The percentages are deliberately rough. Use them to spot what's lagging, not as a release gate.
