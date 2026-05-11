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

## Minimum plan to reach the one-token draft probe

### Step 0: validate the sidecar contract (Spark-safe, no downloads)

Before touching llama.cpp code, validate the sidecar file you intend to use:

- Repo-side (Hugging Face URL, metadata-only range reads + optional payload sampling): `scripts/model_contract_probe_mtp_sidecar_antirez.sh`
- Local file convenience runner (writes a small Markdown + JSON bundle under `/private/tmp`): `scripts/run_mtp_sidecar_contract_probe_local.sh /abs/path/to/DeepSeek-V4-Flash-MTP-*.gguf`
- Spark-side (local file already staged on Spark; no downloads): run the baseline runner with:

```bash
REMOTE_MTP_SIDECAR_ENV='ALLOW_RUN=1 MTP_SIDECAR_GGUF=/abs/path/to/DeepSeek-V4-Flash-MTP-*.gguf' \
scripts/run_baseline_existing_runtime.sh spark0@<spark-host>
```

If you want a narrower Spark-only probe (no llama.cpp/vLLM baselines), use:

```bash
REMOTE_MTP_SIDECAR_ENV='ALLOW_RUN=1' \
scripts/run_mtp_sidecar_contract_probe_spark.sh spark0@<spark-host>
```

If Spark0 already has the pinned sidecar staged at
`/home/spark0/models/ds4/DeepSeek-V4-Flash-MTP-Q4K-Q8_0-F32.gguf`, the runner
defaults `MTP_SIDECAR_GGUF` to that path when it is readable. Override by adding
`MTP_SIDECAR_GGUF=/abs/path/to/your-sidecar.gguf` to `REMOTE_MTP_SIDECAR_ENV`.

This runner also accepts an `https://` URL for `MTP_SIDECAR_GGUF` and will validate the sidecar using HTTP range reads (no full download):

```bash
REMOTE_MTP_SIDECAR_ENV='ALLOW_RUN=1 MTP_SIDECAR_GGUF=https://host/path/to/DeepSeek-V4-Flash-MTP-*.gguf' \
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
- `loader_probe.json`: full llama.cpp probe JSON (when extracted)
- `deepseek4_mtp_sidecar.hpp`: generated binder skeleton (only when the contract probe reports `ok=true`)

By default this Spark-only runner also samples 64 bytes from each tensor payload (`--payload-sample-bytes 64`) to catch truncated/corrupt uploads without loading full weights. Override with `REMOTE_MTP_SIDECAR_ARGS='--json --expect-deepseek-v4-flash --payload-sample-bytes 0'` if you need a strictly header-only check.

If the probe does not return `ok=true` with `missing_tensors=[]` and `extra_tensors=[]`, do not proceed to loader work.

Optional stronger check: `scripts/model_contract_probe_mtp_sidecar_antirez.sh` now defaults to sampling 64 bytes from each tensor payload via HTTP range reads (`--payload-sample-bytes 64`), still avoiding full weight downloads. The recorded output is `docs/mtp-sidecar-probe-antirez-9cb905d-payload64.json`.

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

### Step 2: MTP KV/cache/state model

MTP is a draft model, not a pure MLP head. It needs attention over the prompt prefix.

To be correct, a Spark/CUDA llama.cpp fork needs:

- a draft KV cache for the MTP layer(s), separate from the trunk KV cache (the weights differ, so the cached keys/values differ)
- deterministic state reset/rollback hooks so rejected drafts do not corrupt state

This is the largest unknown in the Spark/CUDA fork because DeepSeek V4’s trunk already has a complex KV story (compressed caches and multiple attention regimes).

### Step 3: implement the DeepSeek V4 MTP forward + logits

Implement the vLLM-style MTP interface:

- `hidden = e_proj(enorm(inputs_embeds)) + h_proj(hnorm(prev_hidden))`
- pass through a DeepSeek V4 decoder layer using the sidecar weights
- compute draft logits via the sidecar `hc_head_*` head (not the trunk head)

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
