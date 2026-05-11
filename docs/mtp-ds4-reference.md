# antirez/ds4 MTP reference (DeepSeek V4 Flash)

This document records **source pointers** into the pinned `antirez/ds4` upstream so we can implement the same MTP draft/verify/rollback semantics in other runtimes (e.g. Spark/CUDA `llama.cpp`) without guessing.

Upstream repo + pin:

- Repo: `https://github.com/antirez/ds4`
- Commit: `99a5c13ba82e05bd2e47a90cdf4825fc7840cf96` (see `docs/upstream-ds4.md`)
- File: `upstreams/ds4/ds4.c` (fetched via `./scripts/fetch_upstreams.sh ds4`, ignored by git)

Convenience: to print the current pin’s key MTP entrypoints (binder + `gamma=1` draft helpers) with line numbers, run:

```bash
ALLOW_FETCH=1 scripts/extract_ds4_mtp_gamma1_steps.sh
```

## Tensor bindings (`mtp.0.*` contract)

`ds4` binds the MTP sidecar tensors by name into a typed table (`ds4_mtp_weights`) and then refuses to proceed unless layout checks pass:

- `ds4_mtp_weights` fields: `upstreams/ds4/ds4.c` (`ds4_mtp_weights` struct)
- Binding function: `upstreams/ds4/ds4.c` (`mtp_weights_bind(ds4_mtp_weights *w, const ds4_model *m)`)
  - This is the authoritative list of the 32 tensor keys expected under `mtp.0.*` for the DS4 MTP support model.
  - Current pin (see `docs/upstream-ds4.md`) location: `upstreams/ds4/ds4.c:2638` (search for `static void mtp_weights_bind(`).

For the repo-side MTP sidecar validator (range-read / metadata-only), see `scripts/model_contract_probe_mtp_sidecar.py`.

To verify ds4_on_spark’s expected 32-tensor list stays synced to the pinned `antirez/ds4` binder:

```bash
./scripts/fetch_upstreams.sh ds4
python3 scripts/verify_mtp_sidecar_expected_tensors_vs_ds4.py --ds4-c upstreams/ds4/ds4.c --python-probe scripts/model_contract_probe_mtp_sidecar.py
```

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
  - Current pin location: `upstreams/ds4/ds4.c:12612` (search for `static bool metal_graph_eval_mtp_draft_from_hc(`).

Draft logits are produced by a dedicated MTP output head helper:

- Output-head helper: `upstreams/ds4/ds4.c` (`metal_graph_encode_output_head_mtp(...)`)
  - Current pin location: `upstreams/ds4/ds4.c:9962` (search for `static bool metal_graph_encode_output_head_mtp(`).

Key semantics to preserve:

- Draft embeds the current token using the **trunk** embedding table, then runs the MTP block and produces draft logits via the MTP head.
- Draft advances the MTP raw-cache frontier (`mtp_n_raw`) independently of the trunk cache.

This is the minimal behavior the `docs/mtp-one-token-draft-probe.md` gate is intended to validate in other runtimes.

## `gamma=1` draft step (operation order, DS4 source of truth)

For a single draft token (`gamma=1`), DS4’s Metal path (pinned `upstreams/ds4/ds4.c`) implements the draft step in `metal_graph_eval_mtp_draft_from_hc(...)` and then produces logits in `metal_graph_encode_output_head_mtp(...)`.

High-level sequence (names match the sidecar tensor table and DS4 helper names; do not guess shapes/dims, use the binder + contract probe):

1) **Token embed (trunk)**: embed the draft input token using the trunk embedding table (`base_weights->token_embd`).
2) **`enorm` + `e_proj`**: apply RMSNorm with `mtp.0.enorm.weight`, then project with `mtp.0.e_proj.weight` to `n_embd`.
3) **Repeat to HC**: repeat/broadcast the projected `n_embd` vector across `n_hc` to form an `hc_dim = n_embd * n_hc` input slice.
4) **`hnorm` + `h_proj`**: apply RMSNorm rows on the provided `prev_hc` (the “target hidden buffer”, pre-`hc_head`), using `mtp.0.hnorm.weight`, then project each HC row with `mtp.0.h_proj.weight`.
5) **Add (`e_proj_hc` + `h_proj_hc`)**: sum the repeated embed projection and the projected `prev_hc` to form the MTP block input (`mtp_input_hc`).
6) **MTP block**: run one DeepSeek V4 Flash decoder block using `mtp.0.{attn_*,hc_attn_*,ffn_*,hc_ffn_*}` weights, against a **separate** MTP raw-cache frontier (not the trunk KV/cache).
7) **MTP output head + trunk vocab projection**:
   - build a flattened HC stream, apply RMSNorm (plain) and `mtp.0.hc_head_*` to compute HC mixture weights
   - weighted-sum HC streams into `n_embd`, RMSNorm with `mtp.0.norm.weight`
   - project to logits using the trunk vocab matrix (`base_weights->output`)
8) **Select draft token**: choose `top_id` (DS4 uses argmax in its probe path).

Implication for external runtimes (Spark/CUDA llama.cpp): for the one-token probe, it’s not enough to “load the sidecar”. The probe must run this full sequence (including a distinct MTP cache frontier) and emit `mtp_draft_token_id` deterministically.

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
