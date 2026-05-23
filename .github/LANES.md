# Lane coordination protocol

> ## 🛑 HALT — code-and-doc cleanup mode (effective 2026-05-23T05:00Z)
>
> **No new feature work.** ct direction: "stop all new work, until we achieve the high-entropy state, we need to keep fixing the code... impossible to have any complex system actually work if it is not DRY."
>
> Every track on its next runtime claims one of the cleanup issues — **and only** cleanup issues — until the codebase and docs are DRY, unique, and necessary on every line.
>
> Currently open in-progress issues (#1295, #1296) are allowed to finish what they started ONLY if they're within a few hours of merging. Otherwise they pause and join cleanup. New `lane_claim_next.sh` runs MUST claim from the cleanup set listed below, never from the legacy backlog. The previous P0 backlog (archive manager, vLLM patches, LongMem modules, throughput/quality measurement) is paused with `prio:P2` until cleanup is complete.
>
> **The cleanup set, in priority order:**
>
> 1. **#1326 P0** — DRY consolidation pass on scripts/. 57 duplicate function groups, 121 extra copies. Split across 3+ tracks. Phase 1 (helper consolidation, ~80 copies) is the largest single chunk.
> 2. **#1330 P0** — Doc distillation: 147 docs/*.md down to ~25-30 non-overlapping documents. 15 `build-*.md` for one build system, 15 `deployment-*.md`, 13 `ops-*.md`, 18 `upstream-*.md`, 4 `ops-tpN-readiness.md` files differing only in N — all merge.
> 3. **#1331 P0** — Integrate Centaur's existing function-similarity detection on this repo. Centaur already has logic for identifying similar functions; we are not using any of it. Wire it up.
> 4. **#1328 P0** — Centaur's complexity metric as CI gate.
>
> **Acceptance for exiting halt mode:** `python3 scripts/audit_code_rot.py` reports zero duplicate-function groups; docs/*.md count is ≤30; Centaur's complexity metric runs on every PR with a non-regressing score; baseline snapshot re-recorded to the post-cleanup state.
>
> **Until that acceptance is met, this halt block is the controlling document.** No track may interpret "highest value Centaur task" as anything other than the cleanup set. Adding new files, new helpers, or new docs during halt mode is itself a halt-rule violation.

This document is the autonomous-loop spec every xhigh track reads on startup. The pinned issue **🚦 Lane coordination state — DO NOT CLOSE** (#1190) is the live source of truth for track ownership and hardware allocation. For where each component of the Centaur system sits in overall progress, see [`docs/CENTAUR_DASHBOARD.md`](../docs/CENTAUR_DASHBOARD.md). For the full system specification — modules, end-state walkthrough, what "done" looks like — see [`docs/CENTAUR_SPECIFICATION.md`](../docs/CENTAUR_SPECIFICATION.md).

## Scope of work — multi-repo

The coordination *hub* — where labels, issues, and this protocol live — is `experiencenow-ai/ds4_on_spark`. The *work* a track does can target any repo in the experiencenow-ai org or its sanctioned forks:| Target repo | Typical work |
|---|---|
| `experiencenow-ai/ds4_on_spark` | Spark deployment, layer-pipeline patches, evaluation harnesses, vLLM/SGLang benchmarks, coordination infrastructure |
| `experiencenow-ai/centaur` | State-machine factory core, provider bindings, model-router qualification, evolution domains, dogfood projects |
| `experiencenow-ai/trimind-brain` | Memory codec, brain forest, IVF-PQ search, LongMemEval harness, ThoughtStream/ClaimStore |
| `ethpred/tc` (fork) → PR to `experiencenow-ai/tc` | Tockchain firmware, C runtime, formal-verification adjuncts |
| `ethpred/ds4` (fork) → PR to `antirez/ds4` | Upstream-compatible patches to the ds4 runtime itself |

Every work issue has a **Target repo** line in its body. Open the PR in that repo, not in the coordination repo. The issue stays in `ds4_on_spark` because that is where the cross-repo coordination lives. The PR's `Closes` line uses the cross-repo form:

```
Closes experiencenow-ai/ds4_on_spark#<issue-number>
```

When in doubt about target repo, read the issue body. Do not assume the work is in the coordination repo.

## Track identity

There are four persistent track slots: `track:1`, `track:2`, `track:3`, `track:4`. These are **agent handles**, not job descriptions. Each track is one xhigh agent slot with continuity of past PRs and accumulated context. That context is useful for picking up familiar repos or familiar bugs, but **it does not assign you to a workstream**.

### What track:N means

- **Yes:** you are the xhigh agent currently working under handle `track:N`. Your past PRs are associated with this handle.
- **Yes:** when you have a `status:claimed` or `status:in-progress` issue carrying your label, that issue is yours to finish.
- **No:** `track:N` does not map to one of the four Centaur workstream components. The Centaur vision document names Components 1–4 (factory core, memory domain, providers, product/UI). **These are not the same as agent track slots, despite the unfortunate naming collision.** Any track may work on any component.
- **No:** you are not a specialist. When your current claim merges or genuinely blocks, you claim the top backlog item that's hardware-compatible, regardless of which component it touches.

If you do not know your track, post a comment on the coordination issue saying so and wait. Do not guess.

## Autonomous loop

On every runtime, run these steps in order. Stop at the first one that produces a task.

```
1. Resume in-progress
   gh issue list --label "track:<N>" --label "status:in-progress" --state open
   → if any results: continue the top issue. Post a status comment with current step
     and what you'll do next, then work. End of decision.

2. Start claimed work
   gh issue list --label "track:<N>" --label "status:claimed" --state open
   → if any results: pick the highest prio. Transition to status:in-progress via
     `gh issue edit <N> --remove-label status:claimed --add-label status:in-progress`.
     Post a "starting" comment. Work.

3. Claim from backlog
   Run `scripts/lane_claim_next.sh <your-N>`.
   The script:
     - Reads which Sparks are currently reserved (by open status:in-progress
       issues carrying hw:spark-N labels)
     - Walks the backlog P0 -> P1 -> P2
     - Picks the first issue whose required Sparks are ALL free AND whose
       declared dependencies are all closed
     - Atomically transitions labels (track:backlog -> track:<N>,
       status:queued -> status:claimed)
     - Posts a /claim comment naming the hardware reservation

   You no longer pass "free-hw-labels" as an argument. The script reads
   the actual reservation state from GitHub. You also no longer need to
   consult a coordination-issue hardware table; the labels themselves
   are the reservation.

   If the script returns "none", every backlog item is either hardware-
   reserved by an in-progress issue or dependency-blocked. Go to step 4.

4. Idle exit (gated)
   You may exit idle ONLY if all three are true:
     a. You posted the five-question comment from the Anti-stall protocol
        on whatever you were just doing (if you were working).
     b. lane_claim_next.sh <your-N> returned "none". (One call, no args.)
     c. Your idle comment on #1190 names at least one specific backlog gap
        (an issue that would let you work if it existed). Do not just say
        "no compatible work."

   If any of (a)(b)(c) is not satisfied, you have not earned idle exit.
   Go back to step 3. The decision tree does not have an "I don't feel
   like the available work" branch.
```

## Cross-track claiming is the default

When your current `status:in-progress` issue merges, blocks, or completes, your next action is **claim from backlog** — and the backlog is *shared across all tracks*. The autonomous loop step 3 has no filter for "issues that match my track's past area." Hardware compatibility and dependency status are the only filters.

This is normal and expected. Every track will routinely work on issues outside the area they have past PRs in. The continuity-of-context benefit of having a stable track handle is real but limited; the cost of refusing cross-area work is much larger (idle agents, slow throughput, the manager getting frustrated and replacing you with a fresh slot).

**A track that has only ever claimed `domain:provider` issues will, on any given session, find that the top backlog item is `domain:centaur` or `domain:harness` or `domain:memory`.** Claim it. The "Track affinity hint" field in the issue body is *advisory* — it names which agent slot has the most relevant past context — but it is not reserved seating. If you have free capacity and the issue is hardware-compatible, you can claim it.

### Cross-track claims are tracked as positive signals

The dashboard's stall ledger now records `cross_track_claims_shipped` per track. This is a good metric — high counts mean the autonomous system is fluid, not siloed. Tracks that consistently claim only from one area, even when other-area items sit higher in priority, will see their stall ledger reflect that pattern.

### Partial-work-as-blocker is not allowed

Doing one piece of an issue, hitting the second piece, and posting `/block` is **not** a valid use of the blocker label. If you got far enough to do any work at all, the work is `status:in-progress` until acceptance gates are met. To apply `status:blocked`, the obstacle must prevent *all* further progress on the issue, and the five-question gate (Anti-stall protocol section) must be answered.

The pattern "stepped outside my track, did one small thing, declared blocked or done" is forbidden. The acceptance gates of an issue are what determine completion, not your sense that you've engaged enough with it.

GitHub's label edits are not transactional. The protocol is:

1. Read the issue, verify it is `status:queued` and `track:backlog` and unassigned to any other track label.
2. Apply your edit.
3. Re-read the issue. If your track label is now the only `track:*` label and `status:claimed`, you have it. If another `track:*` label appeared between your read and write, you lost the race — remove your label and try the next issue.

This is a soft contention model. With four tracks claiming from a backlog of ~10, collisions are rare.

## Hardware reservation (task-bound, not agent-bound)

Hardware is reserved by *issues*, not by *agents*. There are 8 Sparks (`spark-0` through `spark-7`); each has a label `hw:spark-N`. A Spark is **reserved** if any open issue with `status:in-progress` carries its label. Otherwise **free**.

### Label rules

Each work issue carries one of these hardware shapes:

- `hw:none` — no Spark required; always claimable
- `hw:spark-N` (one or more) — those specific Sparks must all be free. An issue needing Spark-3, Spark-4, and Spark-5 carries three labels: `hw:spark-3` + `hw:spark-4` + `hw:spark-5`
- `hw:any-1` — needs one free Spark, any of the 8
- `hw:any-3` — needs three free Sparks, any combination

**Deprecated:** composite labels like `hw:spark-3-4-5`. Decompose to per-node labels.

### The source of truth is the issue labels, not a coordination table

There is no "ownership table" to keep in sync. The reservation state is computed live from the labels on open `status:in-progress` issues:

```
$ scripts/lane_hardware_free.sh
  spark-0: free
  spark-1: free
  spark-2: free
  spark-3: RESERVED by #1208 (Investigate vLLM throughput regression)
  spark-4: RESERVED by #1208
  spark-5: RESERVED by #1208
  spark-6: free
  spark-7: free

  any-N capacity: 5 free Sparks of 8
```

If a Spark is reserved, no other in-progress issue can hold its label. The script `scripts/lane_claim_next.sh <track>` walks the backlog and atomically claims the first issue whose hardware is fully free.

### How an agent uses this

- Before claiming, `lane_claim_next.sh` checks hardware availability for you. You do not need to read a table.
- After claiming an issue with hw labels, when you flip to `status:in-progress`, those Sparks are reserved.
- When you finish (PR merged) or release (status flipped back to queued / blocked), the Sparks are immediately free for the next claimant.
- The script never picks an issue whose hardware is already in use by another `status:in-progress` issue.

### Track:N is no longer hardware-related

Track labels are agent slot handles only. They do not carry hardware affinity. The autonomous loop chooses work by **what's free right now**, not by what a particular track has done in the past. If track:2 happens to claim an issue requiring Spark-4, that does not "give track:2 Spark-4" — it gives the *issue* Spark-4 until the issue closes.

## Anti-stall protocol (read this twice)

The most common failure mode of agents in this system is **writing a status report and stopping**. An agent hits friction, posts a `status:blocked` comment describing what blocked them, and considers themselves done. **This is not done. This is abandonment with paperwork.**

A blocker is a *handoff request*, not a completion state. The work item is still in flight; you have only changed who is being asked to look at it next.

### Three distinct states, three different protocols

| State | Definition | What it requires |
|---|---|---|
| **`status:in-progress`** | You are actively working | Commits/comments/PRs every ≤2 hours |
| **`status:blocked`** | External dependency genuinely prevents progress: hardware down, unmerged dependency issue, missing credentials, server unreachable | Five-question gate (below) + claim another backlog issue *in the same runtime* |
| **`status:in-progress` with a posted "stuck" note** | You tried, code or logic defeated you, you need human input | Posts a comment naming exactly what you tried, with raw output of failures. Stays in-progress; not "blocked." Human decides. |

What does NOT exist as a legitimate state: **"abandoned because hard."** If you stopped without a real external block and without naming what defeated you, you have not finished. You are stalling.

### The five-question gate for `status:blocked`

Before applying `status:blocked` you must post a comment answering all five questions verbatim, with raw evidence not summary:

1. **What did you try?** Paste raw command output (the actual stderr/error/log), not a paraphrase.
2. **What alternative paths exist?** List at least 2.
3. **Which alternatives did you actually try?** With raw output for each attempt.
4. **What specifically would unblock you?** Name the action, the actor, and the artifact (e.g. "Spark0 SSH restored," "issue #1208 closed with the corrected baseline number," "user provides the model manifest path").
5. **What did you claim from backlog instead?** Cite the issue number. If nothing in backlog is compatible with your free hardware, name two issues you would like to see filed.

A `status:blocked` comment missing any of these five is **invalid**. The work item stays `status:in-progress` and you keep working.

### Backlog claim is mandatory before idle exit

The autonomous loop's "idle exit" branch is only legitimate if all of these are true:

- You posted the five-question comment.
- You ran `scripts/lane_claim_next.sh <your-N> hw:none,<any-other-free-hw>` and it returned `none`.
- Your idle comment on #1190 names at least one specific backlog gap (an issue that would let you work if it existed).

If `lane_claim_next.sh` returns an issue, you claim it. Period. You do not get to look at the backlog, decide it's not interesting enough, and exit. The backlog is in priority order; the top item is the next item.

### Stall thresholds

- **Soft check-in:** every 2 hours during `status:in-progress`, post a comment with current step + next sub-step. Silence past 2 hours is itself an anti-pattern.
- **Hard reaper:** 4 hours without commit/comment activity → any other track may comment `/release-stalled track:<N>` and the issue returns to `track:backlog` + `status:queued`. The reaping track gets first claim on the next round.
- **Repeat offenders:** if a track triggers `/release-stalled` twice in 24 hours, the work item is also de-prioritized to make the pattern visible. The dashboard `Stall ledger` records these.

### Concrete examples of valid vs invalid blocker comments

**Invalid (current pattern, do not do this):**
> /block: could not figure out how to discover preloaded models on Spark2. Posting blocker comment.

This is abandonment. You did not list what you tried, you did not try alternatives, you did not claim from backlog, you did not name what would unblock you.

**Valid:**
> Five-question gate per LANES.md:
> 1. What I tried: `ssh spark2 'ls ~/models/ /opt/models/ /var/cache/huggingface/'` returned `<raw 12-line output here>`. Then `ssh spark2 'find / -name "*.gguf" 2>/dev/null | head'` returned `<raw output>`.
> 2. Alternatives: (a) read `~/.cache/huggingface/hub` directly; (b) query the running vLLM API at `/v1/models`; (c) ask user for a manifest.
> 3. Tried (a): `<output showing 14 GGUF models found>`. Tried (b): `<output: connection refused, vLLM not running on spark2>`.
> 4. Unblock action: I can proceed using approach (a), 14 GGUF files. The HF-hub-only inventory may be incomplete relative to what's actually preloaded; user clarification on whether more models exist outside HF cache would help, but does not block this iteration.
> 5. Claimed from backlog: #1208 (vLLM regression investigation) since it's P0 and `hw:spark-3-4-5` is compatible with my session.
>
> Continuing on #1213 with approach (a). NOT applying `status:blocked` because I have a path forward.

The second example is twice as long but represents work; the first is twenty seconds of typing.

## PR linkage (mandatory)

Every PR body must include `Closes #<issue-number>` referencing its issue. PR merge auto-closes the issue. PRs that do not link an issue do not count as work — they will be requested-changes.

Multiple commits per issue are fine; multiple PRs per issue are fine if each is small. But every PR must close at least one issue.

## Acceptance evidence (mandatory)

Every issue's acceptance gates demand **raw program output in the PR body**, not summaries you authored. If acceptance asks for "real tokens from Spark5," the PR body has the literal `ssh spark5 ./cmd` output pasted in. If it asks for measured tok/s, the PR body has the JSON measurement file with timestamps.

Fixtures you authored by hand are not evidence. Fixtures that are the artifact-output of an executed run are evidence.

## Forbidden patterns

- **Treating `track:N` as a job description or workstream specialty.** Track is an agent slot handle, not a role. Backlog claiming is cross-area by default. See "Cross-track claiming is the default."
- **Refusing to claim a hardware-compatible top-priority backlog issue because it's outside the area you have past PRs in.** Not a legitimate exit. Idle is only legitimate when `lane_claim_next.sh` returns `none`.
- **Doing one small piece of work on an issue, then posting `/block` or declaring done.** Acceptance gates determine completion, not your sense of engagement. If you began work, the work is `status:in-progress` until gates pass.
- **Writing "vXX notes," "iteration N status," "lane progress ledger" documents.** These are the dogfood-anti-pattern. The work is the deliverable.
- **Treating `status:blocked` as a completion state.** It is a handoff request. See the Anti-stall protocol. Posting a blocker comment and stopping is abandonment with paperwork.
- **Calling code/logic problems "blocked."** If the build error is confusing, that is `status:in-progress with a stuck note`, not blocked. Blocked is reserved for genuine external dependencies (hardware down, unmerged dep, missing credential).
- **Exiting idle without first claiming from backlog.** `lane_claim_next.sh` must return `none` before idle is legitimate.
- **Closing an issue with `status:in-progress` without a merged PR.** If you can't finish, transition to `status:blocked` with the full five-question gate.
- **Adding more contract/artifact schemas to dodge writing code.** If a working PR would require >2 new JSON shapes before any code runs, you are stalling.
- **`try/except ImportError` fallbacks** or any silent-degradation pattern. Dependencies must be installed; crash loudly if missing.
- **Guessing C struct fields** in any patch. View the file, cite line numbers.

## Decision tree summary (memorize)

```
in-progress for me?       → resume work, post 2-hr check-in
  no
claimed for me?           → transition to in-progress, start
  no
backlog top + free hw?    → claim it (priority order, no cherry-picking)
  no compatible item
hit a blocker just now?   → five-question gate, claim from backlog, continue
  no
backlog has anything?     → CLAIM IT, even at hw:none lowest priority
  truly nothing
                          → post idle comment naming gap, exit
```

That is the entire loop. "I don't feel like the top backlog item" is not a branch. "I wrote a blocker comment so I'm done" is not a branch. The only legitimate exits are merged PR or fully-gated idle.
