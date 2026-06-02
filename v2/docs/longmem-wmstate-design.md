# LongMem WMState Design

This document designs the working-memory state family for LongMem/HWM
experiments. The goal is not to guess one perfect state shape. The goal is to
generate a set of honest, general WMState candidates ranging from too little to
too much, measure them against failure clusters plus canaries, and promote only
the variants that improve the whole benchmark surface.

The core image is:

- WMEvents are receipts.
- WMState views are balances.
- Every balance is traceable back to the receipts that produced it.
- The reader LLM should see a small balance sheet first, then use deterministic
  tools to inspect any receipt or related receipt set.

For Qwen27-class readers, the target is to reduce the task to recognition,
classification, retrieval, counting, date arithmetic, and simple conflict
resolution. The reader should not be asked to infer a life story from a pile of
semi-random facts.

## Design Principles

1. One event ledger, many state projections.
   All WMState variants must project from the same numbered event ledger. This
   prevents each experiment from inventing incompatible facts.

2. Balances cite receipts.
   A current value, count, preference, relationship, or timeline summary is not
   valid unless it carries the event ids that support it.

3. State is allowed to be plural.
   There should be several WMState candidates. Some should be very conservative
   and low error. Some should be richer and more useful but riskier. The
   experiment system decides which mixture is useful.

4. Richness must come with reconciliation.
   The more ambitious a state projection is, the more it needs double-entry
   checks, conflict labels, and drill-down tools.

5. No benchmark cheating.
   No expected answers, question labels, answer regexes, per-question constants,
   or failure-id-specific behavior may enter model-visible state or prompts.
   All improvements must be expressed as general schemas, projections, tools,
   and validation rules.

6. Prefer parsers and typed structure over brittle strings.
   Number, unit, money, and date handling should be delegated to maintained
   parser libraries or small deterministic adapters around them. Raw regex may
   be used only for tokenization and guardrails, never as an answer strategy.

## Signal-To-Noise Measurement

High reader accuracy depends on high signal-to-noise context. A perfect fact can
still be useless if it is buried in enough distractors that Qwen has to infer,
filter, and count under pressure. Each generated context should therefore be
scored after it is built:

- Signal: answer-bearing terms, cited receipt ids, supporting balance ids,
  relevant exact values, and tool results that expose the answer.
- Noise: all remaining context tokens that do not help identify or verify the
  answer.
- Signal-to-noise ratio: signal hits divided by estimated non-signal tokens.
- Coverage: whether the answer terms and expected supporting receipts are
  present at all.

The signal detector is allowed to use the reference answer, expected evidence
ids, and judge-only metadata because it runs after context generation. It is a
measuring instrument, not a context builder. Its outputs must be marked
post-generation-only and must never be fed back into reader prompts, retrieval,
WMState construction, or packet rendering for the same evaluation item.

This gives us a clean loop:

1. Generate context answer-blind.
2. Freeze and hash the context.
3. Run an answer-contaminated signal detector over the frozen context.
4. Compare WMState variants by answer coverage, evidence coverage,
   signal-to-noise ratio, and reader score.
5. Use aggregate signal measurements to design the next general WMState
   mutation, not to patch an individual question.

This unlocks both deterministic and LLM-driven context generation. A generator
can propose several context packets without seeing the answer; the signal
detector then estimates which packet actually contained the strongest answer
evidence with the least distractor mass. The optimizer may learn from aggregate
signal reports across slices, but the per-question signal report remains
forbidden as reader-visible or same-item generator input.

## Core Data Model

### WMEvent Ledger

The ledger is append-only JSONL. Each event is a typed receipt derived from an
exchange span. It is the source of truth for all WMState projections.

```json
{
  "event_id": "E000123",
  "event_hash": "sha256:...",
  "conversation_id": "longmem-q180",
  "session_id": "s07",
  "exchange_idx": 42,
  "turn_idx": 0,
  "speaker": "user",
  "source_role": "user_statement",
  "source_span": {
    "text_sha256": "sha256:...",
    "char_start": 18,
    "char_end": 71,
    "quote": "I just hit 1300 followers on Instagram"
  },
  "observed_at": "2023-05-11",
  "event_type": "state_update",
  "subject": "user",
  "predicate": "instagram_followers",
  "object": {
    "type": "quantity",
    "value": 1300,
    "unit": "followers",
    "raw": "1300 followers"
  },
  "facets": {
    "domain": ["social_media"],
    "state_kind": "counter_total",
    "assertion_status": "stated",
    "temporal_scope": "current_after_event",
    "authority": "self_report",
    "modality": "actual",
    "polarity": "positive",
    "confidence": "high"
  },
  "links": {
    "updates": ["E000118"],
    "contradicts": [],
    "same_transaction": [],
    "derived_from": []
  },
  "extractor": {
    "name": "wm_event_extractor",
    "version": "v1",
    "model": "qwen27",
    "trace_id": "..."
  }
}
```

Event ids must be stable within a run and sortable by session order. A stable
hash is also stored so later import/replay can detect duplicates or edits.

### Event Types

The event schema should stay broad and general:

| Type | Purpose |
| --- | --- |
| `state_observation` | A value is stated without changing a prior value. |
| `state_update` | A current value supersedes or updates older values. |
| `counter_delta` | A value increments, decrements, earns, spends, gains, loses. |
| `set_add` | A countable item enters an owned/known/seen set. |
| `set_remove` | A countable item leaves a set. |
| `set_replace` | Exchange/return/upgrade where one item replaces another. |
| `event_occurrence` | Dated thing that happened. |
| `plan_or_intent` | User may do something later; not yet a fact. |
| `preference_observation` | Like, dislike, goal, habit, constraint. |
| `relationship_observation` | Person/org/place/project relationship. |
| `assistant_fact` | Specific assistant-provided information. |
| `assistant_advice` | Recommendation or advice, quarantined from user facts. |
| `correction` | User or assistant corrects an earlier statement. |
| `uncertain_or_hedged` | Fact is possible but not reliable enough for current state. |

This is intentionally not LongMem-question-specific. It is a general memory
event vocabulary.

## Facets

Facets are typed metadata that help the reader decide which facts matter without
reading raw exchanges first. They also make tools filterable.

### Required Facets

Every event should carry these facets when knowable:

| Facet | Values | Why it helps |
| --- | --- | --- |
| `source_role` | `user_statement`, `assistant_answer`, `assistant_advice`, `third_party_report`, `system_import` | Separates user facts from assistant content. |
| `authority` | `self_report`, `named_party`, `professional`, `assistant`, `unknown` | Helps resolve conflicts and attribution questions. |
| `modality` | `actual`, `planned`, `hypothetical`, `desired`, `recommended`, `negated` | Prevents plans/advice from becoming facts. |
| `temporal_scope` | `current_after_event`, `past_only`, `future_plan`, `recurring`, `timeless` | Tells current-state projections what can win. |
| `confidence` | `high`, `medium`, `low`, `conflict` | Lets the reader know whether to drill down. |
| `domain` | list of generic topics | Supports search and clustering. |
| `entity_kind` | `person`, `animal`, `org`, `place`, `thing`, `event`, `account`, `project`, `unknown` | Helps entity resolution and count filters. |
| `value_kind` | `text`, `number`, `quantity`, `money`, `date`, `duration`, `set_item`, `boolean` | Drives deterministic tools. |

### High-Value Optional Facets

These are especially useful for hard LongMem questions:

| Facet | Purpose |
| --- | --- |
| `unit_family` | Normalizes miles/kilometers, dollars/points, hours/minutes. |
| `counter_semantics` | Distinguishes total, delta, target, threshold, remaining. |
| `set_role` | Distinguishes owned, borrowed, returned, recommended, desired, consumed. |
| `update_semantics` | Distinguishes supersedes, reinforces, contradicts, refines. |
| `recurrence` | Stores habits like weekly/monthly/daily. |
| `date_anchor` | Stores the session date used to resolve relative dates. |
| `date_resolution` | Stores raw date text, resolved date, and ambiguity. |
| `speaker_target` | Stores who the statement is about when not the user. |
| `advice_scope` | Keeps assistant suggestions separate by task/request. |
| `receipt_quality` | Stores extraction warnings: pronoun, ellipsis, anaphora, partial parse. |

These facets are not a license to hardcode. They are schema fields that should
be filled by general extractors and deterministic validators.

## WMState Candidate Family

Each candidate is a projection over the same WMEvent ledger. Experiments should
choose among these or compose them.

### WMState A: Event Ledger Only

Minimal state. The reader sees a compact event index and must use tools to
search/fetch receipts.

Best for:

- Measuring whether state projections are actually needed.
- Avoiding projection error.
- Testing search/tool quality.

Risk:

- Reader must still infer current values and counts from receipts.
- Hard for Qwen on multi-step update/count questions.

### WMState B: Conservative Current Facts

Keeps only high-confidence current facts:

```json
{
  "balance_id": "B.user.instagram_followers.current",
  "entity": "user",
  "slot": "instagram_followers",
  "value": {"type": "quantity", "value": 1300, "unit": "followers"},
  "policy": "latest_current_after_event_wins",
  "receipts": ["E000118", "E000123"],
  "winning_receipt": "E000123",
  "stale_receipts": ["E000118"],
  "confidence": "high"
}
```

Best for:

- Knowledge-update questions.
- Avoiding stale values.
- Low reader burden.

Risk:

- Can miss facts that do not fit a clean slot.
- Needs excellent update semantics.

### WMState C: Entity Balance Sheets

One balance sheet per entity, with slots grouped by type:

```json
{
  "entity": "user",
  "aliases": ["the user", "I"],
  "current": {...},
  "sets": {...},
  "counters": {...},
  "preferences": {...},
  "relationships": {...},
  "timeline_refs": ["T.user.social_media", "T.user.shopping"],
  "conflicts": []
}
```

Best for:

- Questions asking "what does the user have/like/do/currently know?"
- Entity-specific lookup.

Risk:

- Entity resolution mistakes become central.
- Rich entity sheets can over-merge unrelated facts.

### WMState D: Set and Inventory Ledgers

A specialized state for countable things. It is a real balance sheet, not a
collection of scattered claims.

```json
{
  "set_id": "S.user.musical_instruments.owned",
  "entity": "user",
  "category": "musical_instruments",
  "state": "owned",
  "items": [
    {
      "item_id": "I.korg_b1_digital_piano",
      "name": "Korg B1 digital piano",
      "status": "present",
      "receipts": ["E000031"],
      "facets": {"brand": "Korg", "model": "B1"}
    }
  ],
  "removed_items": [],
  "count": 1,
  "count_receipts": ["E000031"],
  "warnings": []
}
```

Best for:

- Multi-session counting.
- Avoiding two divergent inventory systems.
- Returning enumeration plus count to the reader.

Risk:

- Normalization/anaphora errors can add garbage or drop real items.
- Needs strict receipt drill-down and discrepancy warnings.

### WMState E: Numeric Account Books

Tracks totals, deltas, thresholds, prices, points, follower counts, balances,
durations, and measurements.

```json
{
  "account_id": "N.user.sephora_points",
  "entity": "user",
  "quantity": "sephora_points",
  "unit": "points",
  "current_total": 300,
  "entries": [
    {"event_id": "E000201", "kind": "total", "value": 200},
    {"event_id": "E000214", "kind": "delta", "value": 100}
  ],
  "derived_totals": [
    {"value": 300, "from": ["E000201", "E000214"], "method": "total_plus_delta"}
  ],
  "thresholds": [
    {"value": 300, "event_id": "E000205", "meaning": "reward_needed"}
  ],
  "reconciliation": {"status": "balanced"}
}
```

Best for:

- Points, followers, money, distances, durations, discounts.
- Preventing "earn 100 more" from being treated as a new owned item.

Risk:

- Delta vs total confusion is common.
- Unit normalization mistakes can poison the balance.

### WMState F: Temporal Account Books

A normalized timeline plus event clusters and date math inputs.

```json
{
  "timeline_id": "T.user.exercise",
  "events": [
    {
      "event_id": "E000302",
      "raw_date": "last Tuesday",
      "session_date": "2023-08-12",
      "resolved_date": "2023-08-08",
      "confidence": "high",
      "description": "User went jogging"
    }
  ],
  "order_index": ["E000302"],
  "date_conflicts": []
}
```

Best for:

- "How long since", ordering, first/last, nth event, stale/current dates.

Risk:

- Date resolution must be deterministic and audited.
- Repeated events need deduplication without dropping distinct occurrences.

### WMState G: Knowledge Update Ledger

Tracks old/current/stale/corrected values explicitly.

```json
{
  "slot": "user.instagram_followers",
  "history": [
    {"event_id": "E000118", "value": 1250, "valid_from": "2023-04-15", "valid_to": "2023-05-11"},
    {"event_id": "E000123", "value": 1300, "valid_from": "2023-05-11", "valid_to": null}
  ],
  "current": {"value": 1300, "event_id": "E000123"},
  "stale_values": [{"value": 1250, "event_id": "E000118"}]
}
```

Best for:

- Current-value questions.
- Preventing old answers from surviving in state.

Risk:

- Requires update detection, not just value extraction.

### WMState H: Assistant Advice Quarantine

Separates assistant facts and recommendations from user-owned facts.

```json
{
  "advice_id": "A.sephora.reward_recommendation",
  "user_request_event": "E000410",
  "assistant_events": ["E000411", "E000412"],
  "specific_facts": [
    {"kind": "price", "value": "$25", "event_id": "E000411"}
  ],
  "recommendations": [
    {"text": "Try the moisturizer first", "event_id": "E000412"}
  ],
  "not_user_state": true
}
```

Best for:

- Questions about what the assistant said.
- Avoiding assistant advice pollution of user memory.

Risk:

- Too strict a quarantine can hide useful assistant-provided exact facts.

### WMState I: Preference and Profile Ledger

Tracks likes, dislikes, goals, constraints, habits, memberships, and style
preferences with provenance.

Best for:

- "What does the user prefer/avoid/want?"
- Questions where facts are not numeric or transactional.

Risk:

- Easy to over-infer from casual remarks.
- Must distinguish preference, goal, habit, and one-off event.

### WMState J: Relationship, Project, and Role Graph

Tracks named people, places, orgs, projects, pets, roles, memberships, and
relations.

Best for:

- Entity disambiguation.
- Questions involving who, where, project ownership, family/friend/doctor/etc.

Risk:

- Over-merged names and pronouns cause global confusion.

### WMState K: Hierarchical Summaries With Drill-Down

Builds small summaries at multiple levels:

- exchange summary
- session summary
- topic summary
- entity summary
- account/balance summary

Each summary cites receipts and can be expanded.

Best for:

- Keeping Qwen's context small.
- Letting the reader orient before querying exact receipts.

Risk:

- Summaries can hallucinate or smooth over exceptions.
- Must never be the only evidence path.

### WMState L: Reconciled Dual Ledger

The ambitious state. It keeps two or more independently derived projections and
surfaces discrepancies:

1. Event replay projection: compute balances by replaying WMEvents.
2. Extracted state projection: direct LLM or extractor emits proposed balances.
3. Raw search projection: deterministic search/indexes find candidate receipts.

The reconciler compares them and emits:

```json
{
  "check_id": "R.user.sephora_points",
  "status": "discrepant",
  "event_replay_value": 300,
  "direct_state_value": 200,
  "raw_search_candidates": ["E000201", "E000214"],
  "likely_issue": "direct_state_stale",
  "reader_hint": "Use event replay value unless fetched receipts contradict it."
}
```

Best for:

- Catching stale values, missing deltas, divergent inventories, and assistant
  contamination before the reader answers.

Risk:

- More moving parts.
- Reconciliation output must be concise or it will distract the reader.

## Double-Entry Reconciliation

The double-entry idea should be concrete:

1. Each event posts to one or more accounts.
   `set_add` posts to an inventory set. `counter_delta` posts to a numeric
   account. `state_update` posts to current value and stale history.

2. Each account balance is recomputable from receipts.
   A balance without receipts is invalid.

3. Each receipt knows where it posted.
   The event stores `posted_to` after projection, so orphan events can be found.

4. Independent projections must cross-foot.
   If inventory count is 4, `items.length` must be 4. If current value is 1300,
   the update ledger must have a winning receipt for 1300. If a total is derived
   from deltas, the arithmetic must check.

5. Discrepancies are first-class state.
   Do not hide disagreement. The reader should see compact warnings and fetch
   receipts when needed.

Common discrepancy classes:

| Class | Meaning |
| --- | --- |
| `missing_receipt` | Balance value has no supporting event. |
| `orphan_receipt` | Event did not post to any relevant state. |
| `stale_balance` | Older value still appears current. |
| `double_count` | Same item/event counted twice. |
| `dropped_item` | Raw/event evidence finds an item not in set state. |
| `unit_mismatch` | Values combine incompatible units. |
| `delta_total_confusion` | Delta was treated as total or total as delta. |
| `assistant_contamination` | Assistant advice entered user fact state. |
| `entity_overmerge` | Two entities collapsed into one. |
| `entity_undermatch` | Same entity split across aliases. |
| `date_anchor_conflict` | Relative date resolved against wrong anchor. |

## Reader Packet

The reader should not receive the full WM by default. It should receive:

1. The question.
2. A compact index of the most relevant balances and facets.
3. Discrepancy warnings for those balances.
4. Tool instructions.
5. A small set of candidate receipt ids, not full raw exchanges.

Example:

```text
WORLD MODEL INDEX
Question topic candidates:
- B.user.instagram_followers.current = 1300 followers, receipts=[E000118,E000123], stale=[1250]
- T.user.social_media has 3 events, latest=2023-05-11

Warnings:
- none

Tools:
- wm.search_events
- wm.get_event
- wm.get_balance
- wm.trace_balance
- wm.timeline
- wm.count_set
- wm.compute
```

This keeps the first prompt small while giving Qwen enough structure to ask the
right deterministic question.

## Required Tools

Tools should operate over typed event/state data, not over prompt text.

| Tool | Purpose |
| --- | --- |
| `wm.search_events(query, filters)` | Find receipt ids by entity, domain, date, speaker, value kind. |
| `wm.get_event(event_id)` | Return exact receipt, facets, and source quote. |
| `wm.get_exchange(exchange_idx)` | Return original user/assistant text only when needed. |
| `wm.search_balances(query, filters)` | Find relevant balance/state ids. |
| `wm.get_balance(balance_id)` | Return current balance plus compact history. |
| `wm.trace_balance(balance_id)` | Return all receipts that formed the balance. |
| `wm.timeline(entity_or_topic, filters)` | Return sorted dated events. |
| `wm.count_set(set_id or query)` | Return count plus item enumeration and receipts. |
| `wm.numeric_account(account_id)` | Return totals, deltas, thresholds, arithmetic trace. |
| `wm.resolve_entity(name, context)` | Return aliases and candidate entity ids. |
| `wm.find_conflicts(query)` | Return discrepancy records. |
| `wm.compute(operation, inputs)` | Date math, arithmetic, filtering, sorting. |

The reader should prefer tools over manual reasoning for counts, dates, and
numeric operations.

## Experiment Arms

Generate multiple candidate packets for the same question slice:

| Arm | State Included | Why |
| --- | --- | --- |
| `events_only` | WMState A | Measures search/tool baseline. |
| `current_facts` | A + B | Tests minimal useful balances. |
| `entity_sheets` | A + B + C | Tests entity-oriented lookup. |
| `sets_numeric_time` | A + D + E + F | Targets counting, numeric, temporal failures. |
| `update_quarantine` | A + G + H | Targets stale values and assistant pollution. |
| `profile_graph` | A + I + J | Targets preferences, roles, relationships. |
| `hier_summary` | A + K | Tests compact summaries with receipt drill-down. |
| `dual_reconciled` | A + B + D + E + F + L | Tests richer state with error detection. |
| `full_rich` | All states | Tests the too-much upper bound. |

The point is not to assume richer is better. The experiment harness should
compare:

- fixed failures
- regressed pass canaries
- answer findability
- answer-token coverage and exact answer presence in the frozen context
- supporting receipt coverage
- signal-to-noise ratio and signal density
- tool calls required
- reader confidence
- discrepancy rates
- token cost
- runtime

## Current Signal Results

Snapshot: 2026-05-27, synthetic fixture only. Artifact:
`/private/tmp/longmem-signal-cli-structural-latest.json`.

This is not an official LongMem score and used no reader model, judge model,
paid provider calls, live provider calls, or full500 execution. It is a
post-generation signal measurement over frozen generated contexts. The signal
detector used reference answers only after context generation and stored hashes,
not raw answer values.

Run shape:

- cases: 10
- context arms: 14
- signal reports: 140
- overall answer-token coverage: 0.557143
- overall evidence-ref coverage: 0.674603
- overall signal density: 0.04033
- overall signal-to-noise ratio: 0.046006

Top arms by coverage-first ranking:

| Rank | Arm | Answer Coverage | Evidence Coverage | Signal Density | SNR | Exact Hits |
| --- | --- | ---: | ---: | ---: | ---: | ---: |
| 1 | `reader_tool_context` | 1.000000 | 1.000000 | 0.072255 | 0.080223 | 9 |
| 2 | `full_rich` | 0.800000 | 1.000000 | 0.023906 | 0.025356 | 7 |
| 3 | `dual_reconciled` | 0.800000 | 0.851852 | 0.042302 | 0.046081 | 7 |
| 4 | `tools_only` | 0.800000 | 0.555556 | 0.083194 | 0.096802 | 7 |
| 5 | `packet_plus_tools` | 0.800000 | 0.555556 | 0.021463 | 0.022624 | 7 |
| 6 | `sets_numeric_time` | 0.633333 | 1.000000 | 0.031690 | 0.033563 | 7 |
| 7 | `events_only` | 0.550000 | 1.000000 | 0.044444 | 0.050449 | 6 |
| 8 | `current_facts` | 0.500000 | 0.888889 | 0.032680 | 0.034694 | 6 |

Interpretation:

- `reader_tool_context` is the current no-model upper signal baseline because it
  contains targeted deterministic tool output and receipt handles.
- `full_rich` finds the evidence but is noisy. Its lower density/SNR suggests
  broad dumps will likely hurt Qwen unless paired with a strong selection layer.
- `dual_reconciled` is the best structural lead so far: it keeps strong answer
  coverage while reducing noise versus `full_rich` and exposing reconciliation
  hooks.
- `sets_numeric_time` and `events_only` have full evidence coverage but weaker
  answer coverage, so they need better targeted balance rendering before reader
  testing.
- `packet_only` remains weak; current packets are not yet sufficient without
  tools or structural selection.

## Failure-Curriculum Workflow

The 43 failed items should become a curriculum, not a place to overfit.

1. Cluster the failures by observed cause:
   counting, temporal, stale value, assistant contamination, retrieval miss,
   update miss, entity resolution, numeric arithmetic, abstention.

2. For each cluster, create a slice:
   related fails plus matching canaries from nearby pass cases.

3. Run several WMState arms on each slice.
   Do not run single-question experiments unless debugging a crash.

4. Study early returns.
   If an arm regresses canaries or fails to expose the expected receipts, abort
   the rest of that experiment.

5. Mutate structure, not answers.
   Change event schema, projection policy, reader packet assembly, tools, or
   reconciliation. Do not add question-specific hints.

6. Promote only with regression evidence.
   A candidate that fixes 5 of 10 clustered fails but regresses 3 percent of
   the pass population is probably a net loss.

## Implementation Plan

### Phase 1: Ledger and Receipts

- Define `wm_events.jsonl` schema.
- Assign stable event ids and source hashes.
- Store speaker, exchange, date, raw quote, event type, facets, and links.
- Add validators for required provenance and no answer leakage.

### Phase 2: Conservative Projections

- Build current facts, update history, inventory sets, numeric accounts, and
  temporal timelines from the event ledger.
- Every projection must include receipt ids.
- Add deterministic reconciliation checks.

### Phase 3: Reader Tools

- Implement event search/get and balance search/get/trace.
- Add typed compute helpers for count, sort, date diff, and arithmetic.
- Keep raw exchange fetch as fallback, not primary path.

### Phase 4: Candidate Generator

- Generate the experiment arms above as compact model-visible packets.
- Keep full receipts in sidecar files.
- Record packet hashes and event ledger hashes for reproducibility.

### Phase 5: Experiment Harness

- Run clustered fail slices plus canaries.
- Score frozen generated contexts with the post-generation signal detector.
- Score reader answer with Qwen judge and DSV4 judge when available.
- Track fixed, regressed, unchanged, and invalid.
- Emit early-abort signals when canaries regress or receipt coverage is absent.

## Promotion Gates

A WMState mutation cannot be promoted because it helped a hand-picked subset.
It needs:

- No answer or label leakage.
- No question-id-specific behavior.
- Receipts for every balance shown to the reader.
- Signal reports are evaluator-only, answer-contaminated only after context
  generation, and never reader-visible.
- Reconciliation status for rich projections.
- Improvement on the target cluster.
- Acceptable result on matching canaries.
- Acceptable result on random pass controls.
- A credible estimate of full-500 impact before an expensive gate.

## Expected Useful Varieties

Likely high-value states:

1. Inventory/set ledger with authoritative counts and receipts.
2. Numeric account books for totals/deltas/thresholds.
3. Temporal timeline with resolved dates and raw date anchors.
4. Knowledge-update history with stale/current separation.
5. Assistant advice quarantine.
6. Entity sheets with aliases and relationship graph.
7. Compact hierarchical summaries with traceable receipts.
8. Dual-ledger reconciliation warnings.

Likely low-value or dangerous states unless carefully validated:

1. Large prose summaries without receipt trace.
2. Rich profile inference without modality and authority facets.
3. Single global "world state" blobs that mix current facts, stale facts, and
   assistant advice.
4. Duplicate inventories from different systems.
5. Reader prompts that tell the LLM how to answer a benchmark category instead
   of exposing better state.

## Success Criteria

The design is working when:

- Qwen answers hard questions by looking up compact balances and receipts.
- Counting questions return an enumeration plus count.
- Current-value questions expose stale and winning receipts.
- Temporal questions expose resolved dates and date anchors.
- Assistant advice is available but not mixed into user state.
- Discrepancies are visible before the reader answers.
- Improvements on failure clusters do not silently regress pass canaries.
