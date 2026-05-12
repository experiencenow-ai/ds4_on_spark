# llama.cpp Spark/CUDA: making `deepseek4_mtp_support` usable (plan)

This repo can validate the DS4-tuned MTP sidecar (`general.architecture=deepseek4_mtp_support`) and provides a llama.cpp **metadata-only** probe (`docs/llamacpp-mtp-sidecar-probe.md`), but **Spark/CUDA llama.cpp forks do not yet implement the DeepSeek V4 MTP draft model**.

This document records the concrete, code-pointer-backed gap analysis and the minimum patch plan required before attempting the one-token draft wiring gate (`docs/mtp-one-token-draft-probe.md`).

For the upstream reference semantics (tensor binding, MTP raw cache, draft/verify/rollback), use `docs/mtp-ds4-reference.md` (pinned `antirez/ds4`).

## Why the sidecar cannot be “loaded as a model”

The sidecar is not a trunk model GGUF. It contains a compact 32‑tensor table under `mtp.0.*` plus a small amount of DeepSeek4 metadata. Treating it as a normal model triggers:

- `unknown model architecture: deepseek4_mtp_support`

The probe patch in `docs/llamacpp-patches/` exists to validate the file without pretending it is a full model.

## Observed upstream state (kamnxt fork @ `9222e55`)

In `kamnxt/llama.cpp-deepseek-v4-flash-cuda-spark@9222e55`:

- DeepSeek V4 **trunk** execution exists (see `src/models/deepseek4.cpp` and `LLM_ARCH_DEEPSEEK4` handling in `src/llama-model.cpp`).
- “NextN/MTP” support is explicitly not implemented:
  - `src/llama-arch.cpp` documents that NextN/MTP tensors are “currently ignored”.
  - `src/llama-model.cpp` contains multiple “TODO: when MTP is implemented …” notes near `nextn_predict_layers` plumbing.
- The DS4 sidecar’s tensor namespace (`mtp.0.*`) is **not** part of llama.cpp’s model-tensor naming for any existing `llm_arch` (it is neither DeepSeek4 trunk’s tensor set nor the existing NextN tensor names).

Net: even after solving the “unknown architecture” error, the fork still needs *new functionality* (not just loader tweaks) to do MTP draft/verify.

If you have a local checkout of the fork and want fast, grep-able pointers (with line numbers) to the relevant reuse points (HC mix, attention path, MoE, output head, NextN placeholders), run:

```bash
LLAMA_DIR=$HOME/src/llama.cpp-deepseek-v4-flash-cuda-spark \
scripts/extract_llamacpp_deepseek4_mtp_reuse_points.sh
```

## Key implementation reuse (kamnxt fork @ `9222e55`)

The Spark/CUDA fork already contains the DeepSeek V4 hyper-connection building blocks that DS4’s MTP sidecar expects:

- Hyper-connection pre/post/head helpers: `src/models/deepseek4.cpp`
  - `dsv4_hc_pre(...)`
  - `dsv4_hc_post(...)`
  - `dsv4_hc_head(...)`
- Trunk output path uses: `model.output_hc_{fn,scale,base}`, `model.output_norm`, and `model.output` (vocab projection).

DS4’s MTP output head differs from trunk output in exactly two places:

1) it uses the **sidecar** `mtp.0.hc_head_{fn,scale,base}` instead of trunk `model.output_hc_*`
2) it uses the **sidecar** `mtp.0.norm.weight` instead of trunk `model.output_norm`

But it still uses the **trunk vocab matrix** for logits (`model.output` in llama.cpp; `base_weights->output` in `antirez/ds4`).

## Minimum plan to reach the one-token draft probe

### Step 0: validate the sidecar contract (Spark-safe, no downloads)

Before touching llama.cpp code, validate the sidecar file you intend to use:

- Repo-side (Hugging Face URL, metadata-only range reads + optional payload sampling): `scripts/model_contract_probe_mtp_sidecar_antirez.sh`
- Local convenience runner (local file or `https://` URL; writes a small Markdown + JSON bundle under `/private/tmp`): `scripts/run_mtp_sidecar_contract_probe_local.sh /abs/path/to/DeepSeek-V4-Flash-MTP-*.gguf`
- Local combined runner (Python contract + optional llama.cpp probe + cross-check; no fetch/build): `scripts/run_mtp_sidecar_loader_probe_local.sh /abs/path/to/DeepSeek-V4-Flash-MTP-*.gguf`
- Spark-side (local file already staged on Spark; no downloads): use the *narrow* Spark contract runner:

```bash
REMOTE_MTP_SIDECAR_ENV='ALLOW_RUN=1 MTP_SIDECAR_GGUF=/abs/path/to/DeepSeek-V4-Flash-MTP-*.gguf' \
scripts/run_mtp_sidecar_contract_probe_spark.sh spark0@<spark-host>
```

If you are already running the baseline existing-runtime loop, it can optionally record the same sidecar contract probe section, but prefer the narrow runner above for day-to-day sidecar validation.

If Spark0 already has the pinned sidecar staged at
`/home/spark0/models/ds4/DeepSeek-V4-Flash-MTP-Q4K-Q8_0-F32.gguf`, the runner
defaults `MTP_SIDECAR_GGUF` to that path when it is readable. Override by adding
`MTP_SIDECAR_GGUF=/abs/path/to/your-sidecar.gguf` to `REMOTE_MTP_SIDECAR_ENV`.

Optional stronger check: pin the expected byte size for the staged sidecar (still no trunk load or downloads):

```bash
SIDECAR_EXPECT_FILE_SIZE=3807602400 \
REMOTE_MTP_SIDECAR_ENV='ALLOW_RUN=1' \
scripts/run_mtp_sidecar_contract_probe_spark.sh spark0@<spark-host>
```

This runner also accepts an `https://` URL for `MTP_SIDECAR_GGUF` and will validate the sidecar using HTTP range reads (no full download), but it is gated: set `ALLOW_URL=1` explicitly on Spark:

```bash
REMOTE_MTP_SIDECAR_ENV='ALLOW_RUN=1 ALLOW_URL=1 MTP_SIDECAR_GGUF=https://host/path/to/DeepSeek-V4-Flash-MTP-*.gguf' \
scripts/run_mtp_sidecar_contract_probe_spark.sh spark0@<spark-host>
```

If you also want the llama.cpp-side probe (optionally with `LOAD_WEIGHTS=1`) in
the same report, use:

```bash
REMOTE_MTP_SIDECAR_ENV='ALLOW_RUN=1' \
REMOTE_LLAMA_MTP_SIDECAR_PROBE_ENV='ALLOW_FETCH=1 ALLOW_PATCH=1 ALLOW_BUILD=1 ALLOW_RUN=1 JSON_ONLY=1 LOAD_WEIGHTS=1' \
scripts/run_mtp_sidecar_loader_probe_spark.sh spark0@<spark-host>
```

This runner writes additional artifacts next to the Markdown report:

- `contract_probe.json`: full Python contract probe JSON (when parseable)
- `contract_probe_fingerprint_gate.json`: local pinned antirez payload fingerprint gate result
- `loader_probe.json`: full llama.cpp probe JSON (when extracted)
- `contract_vs_loader_probe_parse.json`: local cross-check summary (`ok=true` only when both probes agree on dims/type/offset/nbytes)
- `deepseek4_mtp_sidecar.hpp`: generated binder skeleton (only when the contract probe reports `ok=true`)

By default this Spark-only runner also samples 64 bytes from each tensor payload (`--payload-sample-bytes 64`) to catch truncated/corrupt uploads without loading full weights. Override with `REMOTE_MTP_SIDECAR_ARGS='--json --expect-deepseek-v4-flash --payload-sample-bytes 0'` if you need a strictly header-only check.

If the probe does not return `ok=true` with `missing_tensors=[]` and `extra_tensors=[]`, do not proceed to loader work.

Optional stronger check: `scripts/model_contract_probe_mtp_sidecar_antirez.sh` defaults to sampling 64 bytes from each tensor payload via HTTP range reads (`--payload-sample-bytes 64`) and validating the pinned file size, still avoiding full weight downloads. When payload sampling is enabled, it also runs the pinned payload fingerprint gate (`scripts/verify_mtp_sidecar_payload_fingerprint.py`) and prints the gate JSON to stderr. Disable with `FINGERPRINT_GATE=0` or `PAYLOAD_SAMPLE_BYTES=0`. The recorded probe output is `docs/mtp-sidecar-probe-antirez-b0c3326-payload64.json`.

### Step 1: sidecar weight loader (not a model loader)

Add a dedicated loader that:

- opens a `deepseek4_mtp_support` GGUF as a sidecar (not as `llama_model_loader`)
- validates the 32 tensor names (reuse the probe’s expected name list)
- loads tensor payloads (`gguf_init_from_file(..., no_alloc=false)`) into a `ggml_context`
- exposes the `ggml_tensor *` handles for the 32 weights by name

Status in this repo: the patch in `docs/llamacpp-mtp-sidecar-probe.md` now supports `--load-weights`, which loads the entire sidecar tensor blob into RAM and validates that all 32 `mtp.0.*` tensors have non-null `data` pointers. This is a Spark-safe “does the file actually load?” gate, but it does not yet provide a reusable `deepseek4_mtp_sidecar` binder for forward/kv work.
It also emits a per-tensor `tensors[]` inventory in JSON mode (offsets, dims, and type codes), which is a useful input when turning the probe into an actual sidecar binder module.

Optional helper: generate a C++ “binder skeleton” directly from the repo-side contract probe JSON (avoids guessy dims/types when wiring a `deepseek4_mtp_sidecar` struct in a Spark/CUDA llama.cpp fork):

```bash
python3 scripts/model_contract_probe_mtp_sidecar.py --path /abs/path/to/DeepSeek-V4-Flash-MTP-*.gguf --json --expect-deepseek-v4-flash > /tmp/mtp_sidecar_probe.json
python3 scripts/model_contract_generate_llamacpp_mtp_sidecar_binder.py --sidecar-probe-json /tmp/mtp_sidecar_probe.json > /tmp/deepseek4_mtp_sidecar.hpp
```

Design target: a `struct deepseek4_mtp_sidecar` holding pointers for:

- head: `hc_head_{base,fn,scale}`
- input projections + norms: `e_proj`, `h_proj`, `enorm`, `hnorm`, `norm`
- hyper-connection mix: `hc_attn_{base,fn,scale}`, `hc_ffn_{base,fn,scale}`
- attention (MLA-ish low-rank): `attn_norm`, `attn_q_a`, `attn_q_a_norm`, `attn_q_b`, `attn_kv`, `attn_kv_a_norm`, `attn_sinks`, `attn_output_a`, `attn_output_b`
- ffn (MoE): `ffn_norm`, `ffn_gate_inp`, `exp_probs_b.bias`, `ffn_{gate,up,down}_exps`, `ffn_{gate,up,down}_shexp`

## DS4 draft step reference (antirez/ds4)

DS4’s one-step draft path is concrete and already names the exact tensors used:

- Draft entrypoint: `upstreams/ds4/ds4.c` `metal_graph_eval_mtp_draft_from_hc(...)`
- Draft output head: `upstreams/ds4/ds4.c` `metal_graph_encode_output_head_mtp(...)`

At a high level, DS4’s draft step does:

1) reuse trunk embedding table to embed the current token
2) `enorm` → `e_proj` (sidecar) and repeat/expand to HC (`n_hc * n_embd`)
3) `hnorm` → `h_proj` (sidecar) on the previous HC state and add to the embedded HC input
4) run one DeepSeek V4 decoder block using the **sidecar** `mtp.0.*` weights and a **separate** MTP KV/raw-cache state
5) compute draft logits using the **sidecar** `hc_head_*` + `norm`, but the **trunk** vocab projection

This is the exact behavior the one-token wiring gate (`docs/mtp-one-token-draft-probe.md`) should prove on Spark/CUDA llama.cpp before we attempt acceptance metrics.

### Step 2: MTP KV/cache/state model

MTP is a draft model, not a pure MLP head. It needs attention over the prompt prefix.

To be correct, a Spark/CUDA llama.cpp fork needs:

- a draft KV cache for the MTP layer(s), separate from the trunk KV cache (the weights differ, so the cached keys/values differ)
- deterministic state reset/rollback hooks so rejected drafts do not corrupt state

This is the largest unknown in the Spark/CUDA fork because DeepSeek V4’s trunk already has a complex KV story (compressed caches and multiple attention regimes).

### Step 3: implement the DeepSeek V4 MTP forward + logits

Implement the DS4-style MTP interface:

- reuse trunk embedding table to compute `inputs_embeds` (the sidecar does **not** ship an embedding table)
- build the HC-shaped draft input from `(inputs_embeds, prev_hc)` using sidecar `enorm/e_proj` and `hnorm/h_proj` (see DS4 `metal_graph_eval_mtp_draft_from_hc(...)`)
- run one DeepSeek V4 decoder block using sidecar `mtp.0.*` weights with a separate MTP KV/raw-cache state
- compute draft logits using:
  - sidecar `mtp.0.hc_head_{fn,scale,base}` and `mtp.0.norm.weight`
  - trunk vocab projection (`model.output` in llama.cpp, `base_weights->output` in DS4)

Important: the DS4 sidecar does **not** ship an embedding table. The MTP path must reuse trunk token embeddings (or take `inputs_embeds` from caller).

### Step 4: one-token wiring probe (gamma=1)

Only after steps 1–3 exist, add a minimal probe binary (or `llama-cli` flag path) that:

- loads trunk GGUF (baseline loop artifact)
- loads MTP sidecar GGUF
- runs 1 verify step and computes 1 draft token (gamma=1)
- emits the JSON contract described in `docs/mtp-one-token-draft-probe.md`

## Acceptance metrics (explicitly out of scope until probe passes)

Do not claim acceptance rates or speedups until:

1. The one-token draft probe runs deterministically.
2. A correctness oracle exists for MTP draft/verify behavior (see `docs/model-contract.md` MTP gating).
