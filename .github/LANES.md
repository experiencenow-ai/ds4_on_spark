# Lane coordination protocol

This document is the autonomous-loop spec every xhigh track reads on startup. The pinned issue **🚦 Lane coordination state — DO NOT CLOSE** (#1190) is the live source of truth for track ownership and hardware allocation. For where each component of the Centaur system sits in overall progress, see [`docs/CENTAUR_DASHBOARD.md`](../docs/CENTAUR_DASHBOARD.md).

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

There are four persistent tracks: `track:1`, `track:2`, `track:3`, `track:4`. Tracks are stable identifiers; the work assigned to a track changes over time. When you start a session, you have been told your track. Run the autonomous loop below — do not wait for human instructions.

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
   gh issue list --label "track:backlog" --label "status:queued" --state open \
     --json number,labels,title,body --jq '.[]' \
   → filter to issues whose `hw:*` label matches currently free hardware
     (read the coordination issue's hardware table).
   → sort by prio (P0 > P1 > P2). Pick top.
   → claim atomically:
       gh issue edit <N> \
         --remove-label "track:backlog" --add-label "track:<your-N>" \
         --remove-label "status:queued" --add-label "status:claimed"
   → re-fetch to verify the edit succeeded and the labels are now yours
     (another track may have claimed in parallel; if so, retry with next).
   → post a "claiming" comment with your name and an ETA.

4. Idle exit (gated)
   You may exit idle ONLY if all three are true:
     a. You posted the five-question comment from the Anti-stall protocol
        on whatever you were just doing (if you were working).
     b. lane_claim_next.sh <your-N> with EVERY free hw label you can use,
        including hw:none, returned "none".
     c. Your idle comment on #1190 names at least one specific backlog gap
        (an issue that would let you work if it existed). Do not just say
        "no compatible work."

   If any of (a)(b)(c) is not satisfied, you have not earned idle exit.
   Go back to step 3. The decision tree does not have an "I don't feel
   like the available work" branch.
```

## Claim atomicity

GitHub's label edits are not transactional. The protocol is:

1. Read the issue, verify it is `status:queued` and `track:backlog` and unassigned to any other track label.
2. Apply your edit.
3. Re-read the issue. If your track label is now the only `track:*` label and `status:claimed`, you have it. If another `track:*` label appeared between your read and write, you lost the race — remove your label and try the next issue.

This is a soft contention model. With four tracks claiming from a backlog of ~10, collisions are rare.

## Hardware reservation

Hardware contention is enforced by two mechanisms working together:

**1. The `hw:*` label on each work issue.** Valid values:
- `hw:none` — no hardware needed, pure code work
- `hw:any-1` — needs exactly one Spark, any will do
- `hw:any-3` — needs exactly three Sparks, any group will do
- `hw:spark-2-3-4`, `hw:spark-3-4-5` — specific PP=3 layouts
- `hw:spark-6` — isolated Spark6 only (for ds4-eval baselines)

**2. The hardware table in the coordination issue.** Before claiming an issue with a non-`hw:none` label, read the table. If the required Sparks are owned by another track, do not claim. Pick a different issue.

On claim, edit the coordination table via a new comment with the full updated table. **Latest comment is authoritative.** On PR merge or task completion, comment again releasing the hardware.

Never `--add-label` directly to the coordination issue's hw rows. The table-in-comment pattern is the protocol.

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
