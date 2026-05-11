# llama.cpp Spark/CUDA: one-token DeepSeek V4 MTP draft probe (implementation notes)

This document is a **narrow implementation guide** for adding a real `gamma=1` one-token MTP draft probe to a Spark/CUDA llama.cpp DeepSeek V4 Flash fork (for example `kamnxt/llama.cpp-deepseek-v4-flash-cuda-spark@9222e55`).

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

- `docs/llamacpp-patches/kamnxt-llamacpp-deepseek-v4-flash-cuda-spark-9222e55-mtp-sidecar-probe.patch`

and run:

```sh
./build/bin/llama-ds4-mtp-sidecar-probe --path /abs/path/to/DeepSeek-V4-Flash-MTP-*.gguf --json --load-weights
```

This ensures all 32 `mtp.0.*` tensors exist and have readable payloads, without involving the trunk GGUF.

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

This repo ships a **skeleton** patch against the pinned Spark fork (`9222e55`) that adds a `llama-ds4-mtp-one-token-draft-probe` binary which:

- loads the trunk GGUF and runs the single verify step (`verify_step_idx=0`) to compute `base_next_token_id`
- opens the MTP sidecar GGUF in **metadata-only** mode and validates the exact 32 `mtp.0.*` tensors via a generated binder header
- emits the required JSON contract, but currently reports `ok=false` with a TODO error until the real MTP draft compute is implemented

Patch file:

- `docs/llamacpp-patches/kamnxt-llamacpp-deepseek-v4-flash-cuda-spark-9222e55-mtp-one-token-draft-probe-skeleton.patch`

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
