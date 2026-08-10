# Smart skeletons for comment-free code context

This design describes how to give an LLM a compact, source-grounded view of a
large C/CUDA codebase after inline comments have been removed to prevent drift.
The code stays clean; generated sidecars and skeletons carry the semantic map.

## Goals

- Keep source files comment-free and avoid semantic drift in the main repo.
- Let an LLM quickly understand what the codebase, module, file, and function
  do without loading the whole tree.
- Anchor every generated fact to source hashes and symbol locations.
- Make stale context obvious when code changes.
- Keep query context small by assembling only the skeleton layers needed for the
  task.

## Non-goals

- Do not create prose docs that must be manually maintained.
- Do not trust a summary that is not tied to a source hash.
- Do not replace line-level source inspection for edits, audits, or invariant
  claims.
- Do not make one huge repo summary and hope retrieval finds the right paragraph.

## Artifact layers

The effective structure is a pyramid:

1. Function sidecars: one row per function or top-level callable unit.
2. File skeletons: one row per source/header file, generated from its function
   sidecars and light AST metadata.
3. Module skeletons: one row per directory/category boundary.
4. Repo capsule: a tiny top-level map of subsystems and runtime flows.
5. Retrieval packs: query-specific bundles assembled from the previous layers.

The LLM usually receives:

```text
repo capsule
+ 2-5 relevant module skeletons
+ relevant file skeletons
+ exact function sidecars for touched symbols
+ source snippets only when editing or verifying
```

## Function sidecar contract

Function sidecars are the semantic atoms. They should already exist as JSONL
rows with stable IDs and source hashes.

Required fields:

```json
{
  "format": "centaur-function-sidecar-v1",
  "sidecar_id": "fside-...",
  "category": "dataflow_core",
  "source_file": "df/src/dataflow_batch.c",
  "line_start": 1200,
  "line_end": 1264,
  "source_sha256": "sha256:...",
  "signature": "static int32_t example(...)",
  "function_name": "example",
  "summary": "One compact purpose/effect statement.",
  "protocol_role": "Where this function sits in runtime/protocol flow.",
  "state_effects": ["Reads/writes persistent state, files, network, cache, etc."],
  "invariants": ["Facts an edit must preserve."],
  "liveness_risks": ["Deadlock, stall, retry, blocking, and loop hazards."],
  "edit_hazards": ["Known ways future edits can break it."],
  "lookup_tags": ["dense", "symbol", "protocol", "state", "terms"],
  "confidence": 0.95
}
```

Quality rule: a sidecar row is final only when it is a parsed success row.
Raw/error rows are repair work, even if they have a valid `sidecar_id`.

## File skeleton contract

File skeletons make the codebase legible at scan speed. They summarize the
ownership and local call surface without restating function details.

Recommended schema:

```json
{
  "format": "centaur-file-skeleton-v1",
  "source_file": "ledger/src/ledger_hourly.c",
  "source_sha256": "sha256:whole-file",
  "sidecar_ids": ["fside-..."],
  "category": "ledger_ufc",
  "purpose": "The file-level responsibility in one or two sentences.",
  "owned_concepts": ["pending inject queue", "hourly ledger restore"],
  "entry_points": [
    {
      "symbol": "ledger_hourly_restore",
      "sidecar_id": "fside-...",
      "role": "Loads persisted hourly state."
    }
  ],
  "internal_flow": [
    "Parse/load state",
    "Validate bounds and hashes",
    "Expose state to hourly execution"
  ],
  "state_surfaces": ["files touched", "global structs", "network/cache state"],
  "external_dependencies": ["called modules", "protocol structs", "file paths"],
  "invariants": ["File-wide semantic constraints."],
  "edit_hazards": ["High-risk edits in this file."],
  "lookup_tags": ["dense terms for retrieval"],
  "token_budget_hint": 450
}
```

Generation inputs:

- All successful function sidecars for the file.
- File-level AST/symbol metadata: includes, globals, typedefs, exported symbols.
- Optional dependency graph edges from static analysis.

## Module skeleton contract

Module skeletons explain subsystem boundaries. They should be short enough to
load freely when a query touches the subsystem.

Recommended schema:

```json
{
  "format": "centaur-module-skeleton-v1",
  "module_id": "ledger_ufc",
  "paths": ["ledger/", "ufc/"],
  "file_skeleton_ids": ["ledger/src/ledger_hourly.c"],
  "purpose": "Subsystem responsibility.",
  "runtime_flows": [
    {
      "name": "snapshot restore",
      "steps": ["read persisted state", "validate", "rehydrate runtime"]
    }
  ],
  "owned_state": ["persistent queues", "indexes", "cache files"],
  "public_entry_points": ["symbols or CLI/API surfaces"],
  "cross_module_contracts": ["calls into DF", "called by vpoint"],
  "critical_invariants": ["The small set that must be kept in mind."],
  "known_risks": ["Failure modes and audit hot spots."],
  "lookup_tags": ["dense retrieval terms"],
  "token_budget_hint": 700
}
```

## Repo capsule

The repo capsule is the first thing the model sees. Keep it tiny: roughly 500 to
1000 tokens.

It should contain:

- What the codebase is.
- Major subsystems and their path/module IDs.
- Runtime lifecycle in 8 to 15 ordered steps.
- Where state lives.
- Where network, persistence, consensus, and test harnesses live.
- How to expand context: which module skeleton to pull for which task.

## Retrieval indexes

Store generated skeletons as JSONL, then build lightweight indexes:

```text
sidecars/functions.jsonl
skeletons/files.jsonl
skeletons/modules.jsonl
skeletons/repo.json
indexes/symbols.sqlite
indexes/lookup_tags.sqlite
indexes/source_hashes.sqlite
```

Minimum index tables:

```text
symbols(symbol, kind, source_file, sidecar_id, category)
lookup_tags(tag, artifact_type, artifact_id, source_file, category)
source_hashes(path, sha256, artifact_type, artifact_id)
dependencies(src_artifact_id, dst_artifact_id, edge_kind)
```

Use lexical lookup first for exact symbols and paths. Use embedding search only
after exact lookup misses, and include the exact lookup terms in the final
retrieval pack for transparency.

## Staleness model

Every artifact carries the source hash it was generated from.

Staleness checks:

- Function sidecar stale when its function source hash changes.
- File skeleton stale when file hash changes or any child function sidecar is
  stale.
- Module skeleton stale when any child file skeleton is stale.
- Repo capsule stale when any module skeleton changes enough to alter the top
  map.

The retrieval layer must label stale artifacts and prefer fresh source snippets
over stale generated summaries for edits or audits.

## Generation pipeline

1. Extract symbols and function spans with a parser, not regex-only discovery.
2. Generate or repair function sidecars.
3. Finalize sidecars with success-aware validation.
4. Generate file skeletons from successful sidecars plus AST metadata.
5. Generate module skeletons from file skeletons and dependency edges.
6. Generate the repo capsule from module skeletons.
7. Build symbol/tag/hash indexes.
8. Run retrieval-pack smoke tests against representative questions.

## Retrieval policy

For a user query, build the pack in this order:

1. Always include the repo capsule.
2. Add exact symbol/path matches.
3. Add module skeletons for matched categories.
4. Add file skeletons for matched files.
5. Add function sidecars for symbols directly referenced or likely edited.
6. Add source snippets only when the task asks for edits, audits, or line-level
   claims.

Hard rule: if the model is going to edit code or assert exact behavior, it must
read the source span after loading the skeleton.

## Prompt shape for skeleton generation

Skeleton generation prompts should be terse and schema-locked:

```text
Use only the provided successful sidecars and metadata.
Do not invent APIs, structs, fields, or runtime behavior.
If the sidecars disagree, record the disagreement in known_risks.
Return exactly one JSON object matching the schema.
Keep purpose and flow compact; preserve invariants and edit hazards.
```

## Validation gates

Before a skeleton corpus is publishable:

- `missing_sidecars == 0`.
- `raw_rows == 0`.
- `worker_error_rows == 0`.
- Every skeleton references only existing child IDs.
- Every referenced source hash matches the current checkout snapshot.
- Retrieval pack tests find the expected module/file/function for sampled
  symbols, protocols, and failure modes.

## Rollout plan

Phase 1: finalize function sidecars.

- Finish all category annotations.
- Repair raw/error rows.
- Produce final parsed JSONL and report artifacts.

Phase 2: build file skeletons.

- Generate file skeletons for the completed corpus.
- Validate child sidecar references and source hashes.
- Inspect a sample of high-risk files manually.

Phase 3: build module skeletons and repo capsule.

- Use the category plan as the first module boundary.
- Add dependency edges from includes, calls, and shared state names.
- Generate the top capsule.

Phase 4: integrate retrieval.

- Add a small query-time assembler.
- Route exact symbols and paths before semantic search.
- Keep emitted context budgeted and explainable.

Phase 5: drift automation.

- On source change, invalidate only affected sidecars and ancestor skeletons.
- Regenerate the minimal stale set.
- Refuse to serve stale skeletons for edit/audit tasks unless explicitly marked.

## Open decisions

- Where the final skeleton artifacts live in the main repo versus generated
  scratch space.
- Whether module boundaries should remain category-based or move to a stricter
  path/package graph.
- Whether the retrieval assembler should be a Centaur service endpoint, a local
  CLI, or both.
- How aggressively to compress large test harness functions before sidecar
  generation.
