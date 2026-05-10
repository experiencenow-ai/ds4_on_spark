# antirez/ds4 MTP reference (DeepSeek V4 Flash)

This document records **source pointers** into the pinned `antirez/ds4` upstream so we can implement the same MTP draft/verify/rollback semantics in other runtimes (e.g. Spark/CUDA `llama.cpp`) without guessing.

Upstream repo + pin:

- Repo: `https://github.com/antirez/ds4`
- Commit: `8e7575be0ef44bd97c5ebaccf49ef85e05048b7b` (see `docs/upstream-ds4.md`)
- File: `upstreams/ds4/ds4.c` (fetched via `./scripts/fetch_upstreams.sh ds4`, ignored by git)

## Tensor bindings (`mtp.0.*` contract)

`ds4` binds the MTP sidecar tensors by name into a typed table (`ds4_mtp_weights`) and then refuses to proceed unless layout checks pass:

- `ds4_mtp_weights` fields: `upstreams/ds4/ds4.c` (`ds4_mtp_weights` struct)
- Binding function: `upstreams/ds4/ds4.c` (`mtp_weights_bind(ds4_mtp_weights *w, const ds4_model *m)`)
  - This is the authoritative list of the 32 tensor keys expected under `mtp.0.*` for the DS4 MTP support model.

For the repo-side MTP sidecar validator (range-read / metadata-only), see `scripts/model_contract_probe_mtp_sidecar.py`.

## Separate MTP raw cache + speculative state

`ds4` treats MTP as a **draft model** whose KV/cache state is **not** the same as the trunk’s KV/cache state.

The Metal graph state includes dedicated MTP tensors and a distinct raw cache frontier:

- Graph struct fields: `upstreams/ds4/ds4.c` (`ds4_metal_graph` struct)
  - `mtp_raw_cache`, `mtp_n_raw`, plus a set of `mtp_*` work tensors used only by the drafter.
  - Comments explain why MTP needs its own cache: it runs on speculative future tokens while the target KV state is updated only after verification accepts.

Implication for Spark/CUDA `llama.cpp`: MTP cannot safely reuse the trunk KV cache; it needs a draft cache and a rollback/commit story.

## Draft generation (one-token gate)

The MTP draft step is executed via dedicated graph helpers:

- Draft kernel entrypoint: `upstreams/ds4/ds4.c` (`metal_graph_eval_mtp_draft(...)`)
- Lower-level helper (explicit HC in/out tensors): `upstreams/ds4/ds4.c` (`metal_graph_eval_mtp_draft_from_hc(...)`)

Key semantics to preserve:

- Draft embeds the current token using the **trunk** embedding table, then runs the MTP block and produces draft logits via the MTP head.
- Draft advances the MTP raw-cache frontier (`mtp_n_raw`) independently of the trunk cache.

This is the minimal behavior the `docs/mtp-one-token-draft-probe.md` gate is intended to validate in other runtimes.

## Verification + partial accept + rollback

`ds4`’s speculative decoding loop is explicitly a state machine (draft → verify → accept/rollback), not a replacement sampler:

- State machine comment + entrypoint: `upstreams/ds4/ds4.c` (`ds4_session_eval_speculative_argmax(...)`)
- Verifier helpers:
  - `upstreams/ds4/ds4.c` (`metal_graph_verify_suffix_tops(...)`)
  - `upstreams/ds4/ds4.c` (`metal_graph_verify_decode2_exact(...)`)
- Partial-accept (cheap rewind to prefix-1 for the N=2 verifier case):
  - `upstreams/ds4/ds4.c` (`spec_frontier_commit_prefix1(...)`)

Design note: the fast path relies on being able to either (a) commit verified speculative state or (b) restore saved “frontier” state without replaying an entire prefix decode.

## Acceptance / probe logging (don’t confuse with metrics)

`ds4` includes a light “MTP probe” that tracks whether the draft token matches the subsequently accepted target token:

- Draft probe bookkeeping: `upstreams/ds4/ds4.c` (`ds4_session_eval_internal(...)`)
  - Controlled via env vars like `DS4_MTP_PROBE` and `DS4_MTP_FULL_LOGITS`.

This is useful for debugging wiring, but it is **not** a replacement for the repo’s correctness oracle / acceptance-metrics work, which must only be attempted after the one-token draft probe is implemented and deterministic.

