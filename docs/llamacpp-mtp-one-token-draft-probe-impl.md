# llama.cpp Spark/CUDA: one-token DeepSeek V4 MTP draft probe (implementation notes)

This document is a **narrow implementation guide** for adding a real `gamma=1` one-token MTP draft probe to a Spark/CUDA llama.cpp DeepSeek V4 Flash fork (for example `kamnxt/llama.cpp-deepseek-v4-flash-cuda-spark@94073e2`).

It is the “next step” after the sidecar **contract + loader probe** gates described in:

- `docs/llamacpp-mtp-sidecar-load.md`
- `docs/llamacpp-mtp-sidecar-probe.md`
- `docs/mtp-one-token-draft-probe.md`

Goal: make it possible to run `scripts/run_mtp_one_token_draft_probe_spark.sh` with a real `MTP_ONE_TOKEN_CMD` and produce a single JSON object that validates under:

- `python3 scripts/model_contract_validate_mtp_one_token_draft_probe.py --probe-json ...`

Non-goals (explicitly out of scope for this probe):

- acceptance-rate measurements
- speculative decode throughput claims
- multi-prompt correctness sweeps

## Preconditions (must pass first)

1) The intended MTP sidecar GGUF is staged on Spark and passes the metadata-only contract probe:

```sh
REMOTE_MTP_SIDECAR_ENV='ALLOW_RUN=1' \
scripts/run_mtp_sidecar_contract_probe_spark.sh spark0@<spark-host>
```

2) The sidecar is validated on the llama.cpp fork side (optional but strongly recommended) using the probe patch in this repo:

- `docs/llamacpp-patches/kamnxt-llamacpp-deepseek-v4-flash-cuda-spark-94073e2-mtp-sidecar-probe.patch`

and run:

```sh
./build/bin/llama-ds4-mtp-sidecar-probe --path /abs/path/to/DeepSeek-V4-Flash-MTP-*.gguf --json --load-weights
```

This ensures all 32 `mtp.0.*` tensors exist and have readable payloads, without involving the trunk GGUF.

3) (Recommended) Extract the fork’s DeepSeek4 “reuse points” with line numbers from your local checkout so the one-token MTP patch can call existing primitives (HC mix, attention path, MoE, output head) instead of re-implementing them:

```bash
LLAMA_DIR=$HOME/src/llama.cpp-deepseek-v4-flash-cuda-spark \
scripts/extract_llamacpp_deepseek4_mtp_reuse_points.sh
```

## Output contract (what to emit)

The probe binary/command must emit **exactly one JSON object** to stdout matching `docs/mtp-one-token-draft-probe.md`, at minimum:

- `runtime_repo`, `runtime_commit`
- `trunk_gguf_path`, `mtp_sidecar_path`
- `prompt` or `prompt_sha256`
- deterministic decode knobs (`seed`, `temperature=0.0`, `top_k=1`, `top_p=1.0`)
- `verify_step_idx=0`
- `base_next_token_id`, `base_next_token`
- `mtp_draft_token_id`, `mtp_draft_token`
- `mtp_params` (from sidecar-derived params)
- `ok` + `errors[]`

Validate the JSON with:

```sh
python3 scripts/model_contract_validate_mtp_one_token_draft_probe.py --probe-json /path/to/mtp_one_token_probe.json --json
```

Optionally cross-check `mtp_params` against the sidecar probe output:

```sh
python3 scripts/model_contract_validate_mtp_one_token_draft_probe.py \
  --probe-json /path/to/mtp_one_token_probe.json \
  --sidecar-probe-json /path/to/mtp_sidecar_probe.json \
  --json
```

## Recommended binary shape (Spark fork)

Add a dedicated probe command (recommended as a new example binary rather than a `llama-cli` flag path):

- example name: `llama-ds4-mtp-one-token-draft-probe`
- CLI args:
  - `--model /abs/path/to/trunk.gguf`
  - `--sidecar /abs/path/to/DeepSeek-V4-Flash-MTP-*.gguf`
  - `--prompt '...'` (or `--prompt-file`)
  - `--seed N` (default fixed)
  - `--json`

Hard requirements:

- runs quickly (single prompt, single verify step, `gamma=1`)
- emits JSON only (no banners / logs on stdout)
- uses deterministic decode knobs (`temperature=0.0`, `top_k=1`, `top_p=1.0`)

## Patch scaffold in this repo (skeleton; draft compute still TODO)

This repo ships a **skeleton** patch against the pinned Spark fork (`94073e2`) that adds a `llama-ds4-mtp-one-token-draft-probe` binary which:

- loads the trunk GGUF and runs the single verify step (`verify_step_idx=0`) to compute `base_next_token_id`
- commits `base_next_token_id` once (mirrors DS4 “accept one target token, then draft” sequencing) and captures the trunk **pre-`hc_head`** HC tensor via `cb_eval` (`result_pre_hc_head`)
- opens the MTP sidecar GGUF in **metadata-only** mode by default and validates the exact 32 `mtp.0.*` tensors via a generated binder header
  - optional: pass `--load-sidecar-weights` to load sidecar tensor payloads into the GGUF ggml context (large; use only when needed)
- optional (still not a real draft): when `--load-sidecar-weights` is set and binding succeeds, computes a **stub** “MTP output head norm” tensor by applying the sidecar `hc_head_*` + `norm.weight` to the captured trunk `result_pre_hc_head` and emits:
  - `mtp_stub_input_hc_{fnv64,nbytes,shape}` (stub pre-block input computed from sidecar `enorm/e_proj` + `hnorm/h_proj` + add, using captured `result_token_embd` and `result_pre_hc_head`)
  - `mtp_stub_head_norm_fnv64`
  - `mtp_stub_head_norm_nbytes`
  - `mtp_stub_head_norm_shape`
- optional (still not a real draft): when stub head-norm exists, it best-effort projects that vector through the trunk vocab matrix (`output.weight`) and takes `argmax`, reporting the result via `mtp_draft_token_id` / `mtp_draft_token` (still `ok=false` until the full MTP block + cache exists)
- emits the required JSON contract, including optional debug keys `trunk_pre_hc_head_fnv64`, `trunk_pre_hc_head_nbytes`, and `trunk_pre_hc_head_shape`, but currently reports `ok=false` with a TODO error until the real MTP draft compute is implemented

Patch files:

- `docs/llamacpp-patches/kamnxt-llamacpp-deepseek-v4-flash-cuda-spark-94073e2-mtp-one-token-draft-probe-skeleton.patch`
- Legacy: `docs/llamacpp-patches/kamnxt-llamacpp-deepseek-v4-flash-cuda-spark-9222e55-mtp-one-token-draft-probe-skeleton.patch`

Convenience runner (clone/patch/build/run are all gated behind `ALLOW_*` env vars):

- `scripts/llamacpp_mtp_one_token_draft_probe_patch.sh`

## Sidecar binding (avoid guessy dims/types)

Do not hand-write the 32 tensor names, dims, or ggml types. Generate a binder skeleton from the repo-side sidecar probe JSON:

```sh
python3 scripts/model_contract_probe_mtp_sidecar.py --path /abs/path/to/DeepSeek-V4-Flash-MTP-*.gguf --json --expect-deepseek-v4-flash > /tmp/mtp_sidecar_probe.json
python3 scripts/model_contract_generate_llamacpp_mtp_sidecar_binder.py --sidecar-probe-json /tmp/mtp_sidecar_probe.json > /tmp/deepseek4_mtp_sidecar.hpp
```

Then integrate the generated `bind_deepseek4_mtp_sidecar(...)` checks into the Spark fork’s sidecar loader module.

## Minimum functional wiring (what must be implemented)

The “one-token” probe is not just a weight-load test. It must run a real draft computation:

1) **Trunk verify step**: run the normal DeepSeek V4 trunk path for `verify_step_idx=0`, producing `base_next_token_id`.
2) **Draft step (`gamma=1`)**: run the DeepSeek V4 MTP draft model using the **sidecar** weights and a **separate** draft KV/raw-cache state, producing `mtp_draft_token_id`.
3) **Rollback safety**: ensure the draft state can be reset/rolled back without corrupting trunk state (even if the first probe uses a short prompt).

Reference semantics and tensor usage are pinned to `antirez/ds4`:

- `docs/mtp-ds4-reference.md` (pointers into `upstreams/ds4/ds4.c`)

Important invariant:

- the sidecar does **not** ship a token embedding table; the MTP draft uses the trunk embedding (or `inputs_embeds` supplied by the trunk caller).

## DS4 `gamma=1` draft sequence (concrete reference)

When implementing the one-token probe in the Spark/CUDA fork, use DS4 as the source of truth for **operation order** and which weights participate in the draft step.

Pinned DS4 implementation locations (see `docs/mtp-ds4-reference.md` for the upstream pin and additional context):

- `upstreams/ds4/ds4.c:12612`: `metal_graph_eval_mtp_draft_from_hc(...)` (draft-step orchestration; embed/proj + MTP block + logits readback)
- `upstreams/ds4/ds4.c:9962`: `metal_graph_encode_output_head_mtp(...)` (MTP output head + trunk vocab projection)

High-level DS4 sequence (for `gamma=1`) that the llama.cpp probe should mirror:

1) **Trunk embed**: embed the draft input token using the trunk embedding table (sidecar does not provide embeddings).
2) **`enorm` + `e_proj`**: RMSNorm with `mtp.0.enorm.weight`, then project via `mtp.0.e_proj.weight`.
3) **Repeat to HC**: broadcast the `n_embd` vector across `n_hc` to form `eproj_hc` (`hc_dim = n_embd * n_hc`).
4) **`hnorm` + `h_proj`**: RMSNorm rows on `prev_hc` (the target hidden buffer, pre-`hc_head`) with `mtp.0.hnorm.weight`, then project each row via `mtp.0.h_proj.weight`.
5) **Add**: `mtp_input_hc = eproj_hc + hproj_hc`.
6) **MTP block**: run one decode block using the `mtp.0.{attn_*,hc_attn_*,ffn_*,hc_ffn_*}` weights, against a **separate** MTP KV/raw-cache frontier (not the trunk KV cache).
7) **Output head (MTP) + trunk logits**:
   - apply the MTP head `mtp.0.hc_head_*` + `mtp.0.norm.weight` to produce a normalized `n_embd` stream
   - project to logits using the trunk vocab matrix (`base_weights->output`)
8) **Select token**: deterministic `argmax` for the probe (`temperature=0.0`, `top_k=1`, `top_p=1.0`).

Mapping to the current skeleton patch in this repo:

- `base_next_token_id` is already computed from trunk logits and then **committed** (mirrors DS4’s “accept 1 target token, then draft” sequencing).
- `result_pre_hc_head` capture is intended to correspond to DS4’s `prev_hc` input (the “target hidden buffer”, pre-`hc_head`).
- The remaining TODO is to implement steps (1)-(8) above inside the fork (including a distinct MTP cache), then emit `mtp_draft_token_id` with `ok=true`.

## Spark runner wiring

Once the fork exposes the probe command, run it on Spark using the repo runner:

```sh
REMOTE_MTP_ONE_TOKEN_ENV="ALLOW_RUN=1" \
REMOTE_MTP_ONE_TOKEN_CMD="/abs/path/to/llama-ds4-mtp-one-token-draft-probe --json --model /abs/trunk.gguf --sidecar /abs/mtp_sidecar.gguf --prompt 'Hello.'" \
scripts/run_mtp_one_token_draft_probe_spark.sh spark0@<spark-host>
```

If you already have a sidecar probe JSON on Spark, you can pass it for cross-checking:

```sh
REMOTE_MTP_ONE_TOKEN_ENV="ALLOW_RUN=1" \
REMOTE_MTP_ONE_TOKEN_CMD="..." \
REMOTE_SIDE_CAR_PROBE_JSON="/abs/path/to/mtp_sidecar_probe.json" \
scripts/run_mtp_one_token_draft_probe_spark.sh spark0@<spark-host>
```

## Remaining risks (correctness/perf)

Even after this probe passes, MTP is not “trusted” until a correctness oracle exists:

- acceptance/rollback must match the reference semantics
- multi-prompt comparisons must be deterministic under `temperature=0.0`

Track these under the MTP trust gates in `docs/model-contract.md` before enabling MTP in any performance path.
