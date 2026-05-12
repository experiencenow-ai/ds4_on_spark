# One-Token MTP Draft Probe (llama.cpp Spark/CUDA)

Goal: once the Spark CUDA llama.cpp fork can **load** an `antirez/deepseek-v4-gguf` MTP sidecar (`general.architecture=deepseek4_mtp_support`), run a minimal **one-verify-step** probe that proves the draft path is wired correctly before we attempt acceptance metrics or performance tuning.

This is intentionally narrow:

- **1 prompt**
- **1 verify step**
- **`gamma=1` draft token** (one-token draft)
- deterministic settings (`temperature=0.0`, fixed seed)

## Inputs

- Trunk GGUF (DeepSeek V4 Flash): the main model artifact already used by the baseline runtime loop.
- MTP sidecar GGUF (DS4-tuned 32‑tensor table): e.g. `DeepSeek-V4-Flash-MTP-Q4K-Q8_0-F32.gguf`.
  - Use `scripts/model_contract_probe_mtp_sidecar.py` first; it must return `ok=true`.
  - Optional stronger integrity gate (recommended when using a staged sidecar): compare payload sample fingerprints against the pinned antirez reference:

```bash
python3 scripts/verify_mtp_sidecar_payload_fingerprint.py --probe-json /path/to/mtp_sidecar_probe.json --json
```

  - Optional llama.cpp-side sanity check (local file): apply `docs/llamacpp-mtp-sidecar-probe.md` and run `llama-ds4-mtp-sidecar-probe --json` (must also return `ok=true`).
    - Optional stronger loader gate: add `--load-weights` to ensure the sidecar tensor blob actually loads and all 32 tensors have non-null payload pointers.

## Required probe output

Emit a single JSON object (stdout or file) containing at least:

- `runtime_repo`, `runtime_commit`
- `trunk_gguf_path`, `mtp_sidecar_path`
- `prompt` (or `prompt_sha256` + a stable prompt ID if privacy is needed)
- `seed`, `temperature`, `top_k`, `top_p`
- `verify_step_idx` (always `0` for this probe)
- `base_next_token_id` and decoded token string (tokenizer-dependent)
- `mtp_draft_token_id` and decoded token string
- `mtp_params` derived from the sidecar tensor table:
  - `n_embd=4096`, `n_head=64`, `n_head_dim=512`, `n_hc=4`, `n_lora_q=1024`, `n_out_group=8`, `n_lora_o=1024`, `n_expert=256`, `n_ff_exp=2048`
- `ok` boolean + `errors[]` on failure

Keep this probe *fast*: it should stop after the first verify step and draft computation.

Template JSON (for implementers): `docs/mtp-one-token-draft-probe-template.json`.

Optional debug keys (non-normative; used by the skeleton patch to stage wiring work and by the oracle for diffs):

- `mtp_input_hc_{fnv64,nbytes,shape}` (MTP block input after `(e_proj_hc + h_proj_hc)`; see `docs/mtp-ds4-reference.md` step 5)
- `mtp_block_out_hc_{fnv64,nbytes,shape}` (MTP block output stream before the MTP output head; step 6)
- `mtp_head_norm_{fnv64,nbytes,shape}` (post-`mtp.0.hc_head_*` mixture + `mtp.0.norm.weight`, before trunk vocab projection; step 7)

Notes:

- Prefer fingerprinting intermediate tensors over dumping raw floats/logits. Fingerprints are stable, small, and diff-friendly.
- Avoid dumping full vocab logits (huge + tokenizer/runtime-dependent); fingerprint the normalized head stream instead and require exact `mtp_draft_token_id` equality.

## Validation

After capturing the JSON, validate its shape (and optionally cross-check `mtp_params` against the sidecar’s derived params):

```bash
python3 scripts/model_contract_validate_mtp_one_token_draft_probe.py --probe-json /path/to/mtp_one_token_probe.json
python3 scripts/model_contract_validate_mtp_one_token_draft_probe.py --probe-json /path/to/mtp_one_token_probe.json --sidecar-probe-json /path/to/mtp_sidecar_probe.json
```

## Oracle diff (required before acceptance sweeps)

Once you have **two** probe JSON blobs (oracle + candidate), diff them before running any acceptance/throughput experiments:

```bash
python3 scripts/diff_mtp_one_token_draft_probe.py --a /path/to/oracle_probe.json --b /path/to/candidate_probe.json --json
```

By default this requires:

- `base_next_token_id` match
- `mtp_draft_token_id` match
- `runtime_repo`, `runtime_commit`, `trunk_gguf_path`, and `mtp_sidecar_path` are required to be present in both probes, but do not need to match (oracle vs candidate runs will often differ); differences are recorded as `notes[]` in the diff output.
- when present, any optional debug capture fingerprints match (all keys ending in `*_fnv64`, plus matching `*_nbytes` and `*_shape` companions). Common early captures:
  - `trunk_token_embd_*` / `trunk_pre_hc_head_*`
  - `mtp_input_hc_*` / `mtp_head_norm_*`
  - once the real draft is implemented: `mtp_block_out_hc_*` (plus the token ID match)

If the candidate probe does not emit the debug capture keys yet, keep the diff tool strict and fix the probe output before acceptance sweeps; otherwise you risk comparing different internal wiring paths without noticing.
The diff tool is strict by default: if neither probe emits any `*_fnv64` capture keys, it falls back to requiring the default capture set and will fail until you add those debug fingerprints.

## Spark runner (llama.cpp skeleton patch; available now)

This repo ships a **gated** Spark runner that can clone/patch/build/run the current llama.cpp *skeleton* one-token probe patch (pinned to `kamnxt/llama.cpp-deepseek-v4-flash-cuda-spark@9222e55`) and then validate the emitted JSON locally:

```bash
REMOTE_LLAMA_MTP_ONE_TOKEN_PROBE_ENV='ALLOW_FETCH=1 ALLOW_PATCH=1 ALLOW_BUILD=1 ALLOW_RUN=1 JSON_ONLY=1' \
scripts/run_llamacpp_mtp_one_token_draft_probe_spark.sh spark0@<spark-host>
```

Notes:

- This runner **loads the trunk GGUF** when `ALLOW_RUN=1` is set. Keep it gated and coordinate with the baseline runtime loop.
- The output directory includes a machine-readable `summary.json` (probe parse + local validator status).
- Default pin is `LLAMA_COMMIT=94073e2` (the runner auto-selects the matching patch). To reproduce the original observed failure commit, set `LLAMA_COMMIT=9222e55` when running the runner.
- As of 2026-05-12, the patch is still a **skeleton**: it validates sidecar binding and can compute a debug-only stub output-head tensor when `LOAD_SIDECAR_WEIGHTS=1`, but it emits `ok=false` with a TODO until the real `gamma=1` draft compute is implemented.

## Spark runner (antirez/ds4 oracle; build + one-token JSON)

This repo also ships a **gated** Spark runner that can clone/patch/build/run `antirez/ds4@3630e64` with the Q4_K + secondary-map fixes and the `--dump-mtp-one-token-json` oracle capture:

```bash
REMOTE_ANTIREZ_DS4_MTP_ORACLE_ENV='ALLOW_FETCH=1 ALLOW_PATCH=1 ALLOW_BUILD=1 ALLOW_RUN=1' \
scripts/run_antirez_ds4_mtp_one_token_oracle_probe_spark.sh spark0@<spark-host>
```

## Spark runner (when the fork has a real one-token command)

When the Spark/CUDA llama.cpp fork has a one-token probe command available, run it on Spark and record artifacts using:

```bash
REMOTE_MTP_ONE_TOKEN_ENV="ALLOW_RUN=1 MTP_ONE_TOKEN_CMD='...'" \
scripts/run_mtp_one_token_draft_probe_spark.sh spark0@<spark-host>
```

Optional convenience: instead of embedding the command string inside `REMOTE_MTP_ONE_TOKEN_ENV`, you can set it as a separate local env var and the runner will forward it as `MTP_ONE_TOKEN_CMD=...` unless already present in `REMOTE_MTP_ONE_TOKEN_ENV`:

```bash
REMOTE_MTP_ONE_TOKEN_ENV="ALLOW_RUN=1" \
REMOTE_MTP_ONE_TOKEN_CMD="..." \
scripts/run_mtp_one_token_draft_probe_spark.sh spark0@<spark-host>
```

Optional cross-check against a previously captured sidecar probe JSON (remote path on Spark):

```bash
REMOTE_MTP_ONE_TOKEN_ENV="ALLOW_RUN=1 MTP_ONE_TOKEN_CMD='...' SIDE_CAR_PROBE_JSON=/abs/path/to/mtp_sidecar_probe.json" \
scripts/run_mtp_one_token_draft_probe_spark.sh spark0@<spark-host>
```

Optional convenience: set the remote sidecar-probe JSON path separately; the runner forwards it as `SIDE_CAR_PROBE_JSON=...` unless already present in `REMOTE_MTP_ONE_TOKEN_ENV`:

```bash
REMOTE_MTP_ONE_TOKEN_ENV="ALLOW_RUN=1 MTP_ONE_TOKEN_CMD='...'" \
REMOTE_SIDE_CAR_PROBE_JSON="/abs/path/to/mtp_sidecar_probe.json" \
scripts/run_mtp_one_token_draft_probe_spark.sh spark0@<spark-host>
```

This runner does not fetch/build. It only runs the provided command, validates the emitted JSON, and saves the report under `/private/tmp`.

Note: the runner assumes the one-token command emits **exactly one JSON object** to stdout (no banners, no logs). Any validation output is written to stderr and captured in the report separately.

The output directory includes a machine-readable `summary.json` (probe parse + remote validator JSON, when available).

Optional sidecar-gated runner: if you want this repo to perform a Spark-side sidecar contract probe first (metadata-only, no trunk load) and then cross-check `mtp_params` against the sidecar’s derived params automatically, use:

```bash
REMOTE_MTP_ONE_TOKEN_ENV="ALLOW_RUN=1 MTP_ONE_TOKEN_CMD='...'" \
REMOTE_MTP_SIDECAR_ENV="ALLOW_RUN=1" \
scripts/run_mtp_one_token_draft_probe_spark_with_sidecar_gate.sh spark0@<spark-host>
```

This runner also attempts (best-effort) to fetch `/tmp/mtp_sidecar_probe.json` back from Spark and run the same payload fingerprint gate locally, writing the result into the report directory as `sidecar_probe_fingerprint_gate.json`.
The output directory includes a machine-readable `summary.json` (probe parse + remote validator + local fingerprint gate).

## Implementation checklist (Spark/CUDA llama.cpp fork)

Before running this probe, the Spark/CUDA fork needs a **real** one-token MTP command (the runner only executes what you provide as `MTP_ONE_TOKEN_CMD`):

1. **Sidecar contract gate passes**: the same `mtp_sidecar_path` must pass the Python contract probe (`ok=true`, `missing_tensors=[]`, `extra_tensors=[]`) and the optional llama.cpp sidecar probe (`llama-ds4-mtp-sidecar-probe --json`, `ok=true`).
2. **Sidecar loader exists (not a trunk model loader)**: load the 32 `mtp.0.*` tensors into a sidecar struct/table (use the repo-generated binder skeleton from `scripts/model_contract_generate_llamacpp_mtp_sidecar_binder.py`; do not guess tensor names/dims).
3. **Trunk embedding is reused**: the MTP path must reuse the trunk token embedding (the sidecar does not ship an embedding table).
4. **Draft step is isolated + deterministic**: run exactly 1 verify step (`verify_step_idx=0`) and compute exactly 1 draft token (`gamma=1`) at `temperature=0.0`, `top_k=1`, `top_p=1.0`, fixed seed.
5. **Separate speculative state**: do not reuse trunk KV/cache state for the draft path; draft state must be independently reset/rolled back (even if the first probe uses a minimal prompt).
6. **Emit the JSON contract**: output a single JSON object matching this doc + validate it with `scripts/model_contract_validate_mtp_one_token_draft_probe.py` before attempting any acceptance-rate experiments.

## Code pointers (DS4 + llama.cpp fork)

When implementing the actual Spark/CUDA one-token command, avoid “guessy” wiring by following these pinned code pointers:

- DS4 reference behavior + tensor usage (source of truth): `upstreams/ds4/ds4.c`
  - Sidecar binding + strict layout checks: `mtp_weights_bind(...)`
  - One-step draft: `metal_graph_eval_mtp_draft_from_hc(...)`
  - Draft output head (sidecar head + trunk vocab projection): `metal_graph_encode_output_head_mtp(...)`
- Spark/CUDA llama.cpp fork building blocks (kamnxt @ `9222e55`):
  - Hyper-connection helpers used by trunk: `src/models/deepseek4.cpp` (`dsv4_hc_pre(...)`, `dsv4_hc_post(...)`, `dsv4_hc_head(...)`)
  - Trunk logits path uses `model.output` as the vocab projection; DS4’s MTP draft head still uses the trunk vocab matrix.

## Semantics (reference)

For DeepSeek V4, the MTP module uses separate `e_proj` / `h_proj` projections and applies the `hc_head_*` head in `compute_logits` for draft token selection. Reference: vLLM API docs `vllm.model_executor.models.deepseek_v4_mtp` (DeepSeek V4 MTP draft model).

## Acceptance gate (not in this probe)

Do **not** claim speedups or acceptance rates until:

1. The one-token draft probe runs deterministically and emits the required JSON.
2. A multi-prompt correctness sweep exists that compares MTP draft/verify behavior against an oracle (or a trusted implementation) under fixed decoding.

This probe is only a wiring check, not a correctness proof.
