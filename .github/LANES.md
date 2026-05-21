# Lane coordination protocol

This document is the autonomous-loop spec every xhigh track reads on startup. The pinned issue **🚦 Lane coordination state — DO NOT CLOSE** is the live source of truth for track ownership and hardware allocation.

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

4. Idle exit
   No compatible work. Post one comment on the coordination issue:
     "track:<N> idle, no compatible work matching free hardware <list>"
   Then exit. Do not generate documentation about being idle. Do not write
   status reports. Exit.
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

## Idle and stall thresholds

- **Soft idle:** no commit or comment from your track on its in-progress issue for >2 hours. You self-detect this on next runtime: post a status update with what's blocking, even if it's "still running, awaiting Spark6 eval completion."
- **Stall (auto-block):** no commit or comment for >4 hours. Any other track may, on next runtime, comment `/release-stalled track:<your-N>` on the stalled issue, after which the stalled issue's track label is moved back to `track:backlog` and `status:queued`. The original track does not get to "reclaim" without a fresh claim.

## PR linkage (mandatory)

Every PR body must include `Closes #<issue-number>` referencing its issue. PR merge auto-closes the issue. PRs that do not link an issue do not count as work — they will be requested-changes.

Multiple commits per issue are fine; multiple PRs per issue are fine if each is small. But every PR must close at least one issue.

## Acceptance evidence (mandatory)

Every issue's acceptance gates demand **raw program output in the PR body**, not summaries you authored. If acceptance asks for "real tokens from Spark5," the PR body has the literal `ssh spark5 ./cmd` output pasted in. If it asks for measured tok/s, the PR body has the JSON measurement file with timestamps.

Fixtures you authored by hand are not evidence. Fixtures that are the artifact-output of an executed run are evidence.

## Forbidden patterns

- **Writing "vXX notes," "iteration N status," "lane progress ledger" documents.** These are the dogfood-anti-pattern. The work is the deliverable.
- **Closing an issue with `status:in-progress` without a merged PR.** If you can't finish, transition to `status:blocked` with a specific blocker comment.
- **Adding more contract/artifact schemas to dodge writing code.** If a working PR would require >2 new JSON shapes before any code runs, you are stalling.
- **`try/except ImportError` fallbacks** or any silent-degradation pattern. Dependencies must be installed; crash loudly if missing.
- **Guessing C struct fields** in any patch. View the file, cite line numbers.

## Cross-repo work

Some issues require work in `experiencenow-ai/centaur` rather than `experiencenow-ai/ds4_on_spark`. The issue body will name the target repo. Open the PR there, but the issue stays in `ds4_on_spark` because this is the coordination repo. The PR's `Closes` line uses the cross-repo form: `Closes experiencenow-ai/ds4_on_spark#N`.

## Decision tree summary (memorize)

```
in-progress for me?  → resume
  no
claimed for me?      → start
  no
backlog + free hw?   → claim top P0
  no
                     → comment idle, exit
```

That is the entire loop. No human instructions required between runtimes. Strategic re-prioritization happens via the human editing issue labels or priorities; you re-read them on next startup.
