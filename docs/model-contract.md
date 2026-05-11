# Model Contract

This repo targets **source-derived** execution contracts. Do not guess tensor names, layer schedules, cache semantics, or tokenization behavior — derive them from upstream configs and official reference implementations, then pin the upstream commit in `fixtures/`.

## What “contract” means here

The contract is the minimum set of **exact, testable** facts DS4 must implement to match upstream:

- **Model topology**: layer counts, hidden sizes, head dims, MoE configuration, MTP configuration.
- **Attention schedule**: which layers are sliding-only vs compressed (CSA/HCA), and the per-layer cache semantics.
- **Parameter naming**: exact tensor keys expected in checkpoints (or GGUF equivalents), including quant scale tensors.
- **Tokenizer + chat encoding**: special tokens, templates, and any upstream test vectors we can run locally.
- **Correctness oracles**: what fixtures we must produce (logits / traces) and the rules for comparing.

## DeepSeek V4 Flash

- Contract doc: `docs/model-deepseek-v4-flash.md`
- Upstream metadata source (HF configs only; no weights): `docs/upstream-deepseek-v4-flash.md`
- Fixtures: `fixtures/model_contract/deepseek_v4_flash/`
  - Source trace: see `docs/model-deepseek-v4-flash.md` “Source trace (official → pinned fixtures → DS4 contract)” for where each contract fact is derived (config vs reference code vs checkpoint key set vs tokenizer/encoding).
  - Includes `DeepSeek_V4.pdf` (technical report; metadata-only) as an additional official reference alongside `config.json` and `inference/*`.
- Derived fixture: `fixtures/model_contract/deepseek_v4_flash/contract_summary.json` (built from pinned configs + reference code; includes attention schedule, cache offsets + masking semantics, tokenizer + encoding constants, quantization metadata (including FP8/FP4 scale-tensor shape rules), upstream reference defaults (`max_seq_len`, `max_batch_size`), YaRN per-layer rule, runtime indexer/HC params, tensor-key invariants, config-field compatibility mappings for interpreting external runtimes, Transformers-compatible derived schedules (`attention_schedule.transformers_*` and `moe.transformers_mlp_layer_types`), and machine-readable oracle requirements (`oracle.*.required` + `oracle.*.weights_required`))
  - Also records machine-readable logical tensor shapes (`tensor_shapes`) and correctness oracle requirements (`oracle`) so downstream tooling can validate without re-parsing upstream code.
  - Also records machine-readable **tensor-key invariants** (`tensor_keys.required_top_level` and the `tensor_keys.required_layer_suffixes*` sets) and MTP trust gates (`mtp.trust_gates`) so tooling can enforce “exact tensor names” and “MTP is trusted only if…” policies without re-parsing docs.
  - Also records per-layer trunk key helpers (`tensor_keys.layer_required_nonexpert_suffixes_by_layer_id` and `tensor_keys.layer_*_tensor_key_count_by_layer_id*`) so DS4 implementers can validate “exact tensor names” and per-layer key counts without reconstructing the CSA/HCA schedule logic.
  - Compat mappings also cover MTP (`num_nextn_predict_layers`) and `config.json` quantization knobs (`quantization_config.*`) so external runtime configs can be normalized without guessing.
  - Compat mappings also record a small Transformers-specific cache-layer note (`compat.transformers_cache_layers`) so external-runtime logs can be interpreted without guessing CSA vs HCA cache class behavior.
  - Tokenizer section also records a `tokenizer.tokenizer_json_summary` snapshot (BPE backend + exact pre-tokenizer `Split` regex patterns + `ByteLevel` flags) so external runtimes can reproduce tokenization without guessing.
    - Note: `tokenizer.json`’s `added_tokens[]` list can include tokens whose IDs are *within* the base BPE vocab range. Use `tokenizer.tokenizer_json_summary.*_ge_base_vocab` fields for the contiguous “extra token IDs above base vocab” range.
  - `scripts/model_contract_verify_deepseek_v4_flash.py` also cross-checks tokenizer invariants against the pinned fixtures (BOS/EOS token IDs, `add_bos_token/add_eos_token`, `model_max_length`, and “PAD is EOS”) so contract consumers can treat these as enforced facts, not just documentation.
  - Cache section also records `kv_cache_size` values computed at the upstream reference defaults (helps interpret single-Spark KV/cache headroom without guessing).
  - Cache section also pins the exact sparse-attention top-k index helper definitions from the upstream reference (`cache.topk_index_helpers`) so external runtimes can reproduce index matrices (including `-1` sentinel placement) without guessing.
  - Checkpoint section records a stable fingerprint of the `model.safetensors.index.json` key set (`checkpoint_index.weight_map_keys_sha256`) so contract consumers can detect fixture drift without enumerating every key.
  - It also records per-prefix fingerprints (`checkpoint_index.weight_map_prefix_fingerprints`) so consumers can independently sanity-check the `layers.*` and `mtp.*` namespaces (useful when evaluating whether an artifact set plausibly preserves upstream `mtp.0.*`).
  - Convenience fields: `checkpoint_index.weight_map_layers_keys_sha256`, `checkpoint_index.weight_map_mtp_keys_sha256`, `checkpoint_index.weight_map_top_level_keys_sha256`, and `mtp.checkpoint_key_fingerprint.*`.
  - Upstream section records sha256 of the pinned upstream commit (`upstream_commit.txt`), encoding oracle vectors (`encoding/tests/*`), and oracle prompt set (`oracle/prompts.json`) to keep drift machine-detectable.
- Contract summary also records small but correctness-critical reference expressions (e.g. attention scaling and activation-QAT group sizes) from `inference/model.py` so DS4 can validate external runtime assumptions without guessing.
- Fetch/refresh script: `scripts/model_contract_fetch_deepseek_v4_flash.sh`
- One-shot refresh + verify: `scripts/model_contract_refresh_deepseek_v4_flash.sh`
- Contract-summary builder: `scripts/model_contract_build_deepseek_v4_flash_contract.py`
- Contract verifier: `scripts/model_contract_verify_deepseek_v4_flash.py`
  - Includes the encoding oracle (`fixtures/model_contract/deepseek_v4_flash/encoding/tests/*`).
  - Also gates `contract_summary.json` `mtp.semantics` (source-derived `MTPBlock.forward(...)` expressions) so MTP path drift is detected even when tensor keys remain stable.
  - Enforces Flash-variant quantization semantics (`expert_dtype`, `scale_fmt`, and related config fields) so external-runtime results can be interpreted without silently mixing Flash vs Flash-Base.
    - Note: `expert_dtype` may be omitted from upstream `config.json` in some revisions; the contract treats `fixtures/.../inference/config.json` `expert_dtype` as canonical and marks the Transformers key as optional in `contract_summary.json` `compat.fields`.

## Correctness Oracles (requirements)

Numeric logits require weights, so they are *not* generated by default in this repo. The baseline expectation:

- **Tokenizer oracle**: upstream `encoding/tests/*` vectors must pass locally (no weights needed).
- **Logit oracle** (when weights are available on Spark): generate and commit *small* logit fixtures
  (short prompts + a few decode steps) from the pinned upstream reference code, then gate DS4 against them.

DeepSeek V4 Flash specifics:

- Prompt cases live in `fixtures/model_contract/deepseek_v4_flash/oracle/prompts.json`.
- Oracle generator (weights required): `scripts/model_contract_generate_deepseek_v4_flash_oracle.py`
  - Refuses to download weights.
  - Emits `fixtures/model_contract/deepseek_v4_flash/oracle/logits_oracle.json` containing:
    - `prompt_tokens[]` (already tokenized; no tokenizer dependency for verification)
    - per-step `topk_ids[]` + `topk_logits[]` (default `topk=64`)
  - Add `--include-mtp` to also record MTP (`mtp.0.*`) draft traces (`cases[].mtp_trace[]`).

MTP (multi-token prediction) oracle requirements:

- If DS4 enables speculative decoding via `mtp.0.*`, treat MTP as a **separate execution path** with its own acceptance gate.
  - Before trusting MTP on any artifact (especially GGUF or other quantized conversions):
  - Verify the artifact preserves the `mtp.0.*` tensor namespace (official safetensors do; conversions may not). For GGUF, use `scripts/model_contract_inspect_quantized_artifact.py` and record:
    - `tensor_type_counts` + `mtp_tensor_type_counts` (GGUF quant types present)
    - `tensor_type_profile` (best-effort expert vs dense split for known DeepSeek-V4 GGUF naming; includes `hints.flash_variant_hint` when experts appear primarily `MXFP4`)
    - `quantization_contract` (when `--contract-summary` is available: contract-aware “Flash native FP8/FP4-like?” hint derived from `tensor_type_profile` vs `fixtures/model_contract/.../contract_summary.json` `quantization.inference_config`)
    - Note: some DeepSeek-V4-capable GGUF forks extend `ggml_type` beyond the upstream GGUF spec. For example, nsparks’ “native FP4/FP8” DeepSeek4 GGUF includes `F8_E4M3_B128` (type code `42`) and `MXFP4` experts; the inspector maps these when `metadata["general.architecture"] == "deepseek4"` (see the pinned `docs/gguf-inspect-nsparks-0b34e0b-fp4-fp8-native.json`), but the pinned artifact is still mixed (many `F32`/`BF16` tensors), so prefer `quantization_contract` over assuming fully native Flash quant semantics.
    - `tensor_key_namespace_guess` (whether the artifact appears to preserve upstream `layers.{i}.*` / `mtp.0.*` key namespaces; many GGUF conversions are `llama.cpp`)
    - `mtp_namespace.has_mtp0` + `mtp_namespace.expected_complete` (whether the artifact set appears to preserve the expected `mtp.{id}.*` namespace prefixes)
    - `metadata.general.*` (provenance)
    - `weight_keys_sha256` (stable fingerprint of the artifact’s tensor key set). When `mtp_present == true`, also record `mtp_keys_sha256` (stable fingerprint of the `mtp.*` subset).
    - `topology_contract` mismatches (GGUF header metadata vs expected topology, including RoPE `dimension_count` / `freq_base` when present)
    - `trunk_contract.complete == true` (structural trunk tensor-key completeness; interpret via `trunk_contract.kind`):
      - `kind="deepseek-upstream"`: checks upstream-style `layers.{i}.*` keys (safetensors index or a GGUF that preserves upstream tensor names)
      - `kind="llama.cpp"`: checks DeepSeek4 GGUF-style `blk.{i}.*` keys (compat-only signal for quantized artifacts; does not imply semantic correctness)
    - `mtp_contract.complete == true` when `mtp_present == true` (MTP tensor-key completeness)
  - For Hugging Face-hosted GGUFs, `model_contract_inspect_quantized_artifact.py` also supports metadata-only inspection via range reads (no full download). Record the `url_prefix_bytes` used:
    - `python3 scripts/model_contract_inspect_quantized_artifact.py --url https://huggingface.co/<repo>/resolve/<rev>/<file>.gguf --json`
    - If it fails with “unable to parse ... within max_bytes”, increase `--max-bytes` cautiously (it only fetches the header + tensor table, but large MoE GGUFs can have a large tensor directory).
    - Recorded examples: `docs/gguf-inspect-preyazz-6c6d74c-q4-k-m.json`, `docs/gguf-inspect-nsparks-0b34e0b-fp4-fp8-native.json`, `docs/gguf-inspect-antirez-b0c3326-iq2xxs-chat-v2.json`.
    - These pinned trunk GGUFs currently report `mtp_present=false` and `mtp_namespace.has_mtp0=false` (i.e. the upstream `mtp.0.*` namespace was dropped in conversion).
    - To refresh the pinned example JSON outputs reproducibly (metadata-only Range reads; refuses servers that don’t honor Range), run: `scripts/model_contract_refresh_v4flash_gguf_inspects.sh`.
  - Some community conversions ship MTP weights as a **sidecar** GGUF separate from the main trunk GGUF. In that case, inspect *both* files and treat “MTP present” as a property of the artifact **set**:
    - `python3 scripts/model_contract_inspect_quantized_artifact.py --path /abs/path/to/trunk.gguf --path /abs/path/to/mtp_sidecar.gguf --json`
    - For artifact sets, also record `combined.weight_keys_union_sha256` and (when present) `combined.mtp_keys_union_sha256` to fingerprint the union key set across trunk + sidecar inputs.
  - Some DS4-tuned sidecars (e.g. `antirez/deepseek-v4-gguf`) are not full official `mtp.0.*` checkpoints; they use a compact 32‑tensor `mtp.0.*` table for DS4’s MTP path and advertise `general.architecture=deepseek4_mtp_support`. Before attempting to load these in external runtimes, validate the sidecar header/tensor directory (no full model download required):
    - For the upstream reference semantics (tensor binding, MTP raw cache, draft/verify/rollback), see `docs/mtp-ds4-reference.md` (pinned `antirez/ds4`).
    - Local file: `python3 scripts/model_contract_probe_mtp_sidecar.py --path /abs/path/to/DeepSeek-V4-Flash-MTP-*.gguf --json --expect-deepseek-v4-flash`
    - Convenience runner (local file or `https://` URL, writes a small Markdown + JSON artifact bundle under `/private/tmp`): `scripts/run_mtp_sidecar_contract_probe_local.sh /abs/path/to/DeepSeek-V4-Flash-MTP-*.gguf`
    - Hugging Face URL (range-reads only the header/tensor table): `python3 scripts/model_contract_probe_mtp_sidecar.py --url https://huggingface.co/<repo>/resolve/<rev>/<file>.gguf --json --expect-deepseek-v4-flash`
    - The sidecar probe also computes `payload_bytes` per tensor (ggml row-size math for `F32`, `Q8_0`, `Q4_K`) and validates that tensor payload spans do not overlap and do not run past `file_size` when available.
    - When `deepseek4.*` metadata params are present, the probe records them as `metadata_params` and cross-checks them against the tensor-derived `derived_params` (catches “header says one thing, tensor table says another”).
      - It also sanity-checks `deepseek4.mtp_layer_count` / `deepseek4.nextn_predict_layers` when present: this compact sidecar is expected to be `1` layer (`mtp.0.*` only).
    - Stronger pinning gate (still no full download): compare per-tensor `--payload-sample-bytes 64` hashes against the pinned antirez reference:
      - `python3 scripts/model_contract_probe_mtp_sidecar.py --url https://.../DeepSeek-V4-Flash-MTP-*.gguf --json --expect-deepseek-v4-flash --payload-sample-bytes 64 > /tmp/mtp_sidecar_probe.json`
      - `python3 scripts/verify_mtp_sidecar_payload_fingerprint.py --probe-json /tmp/mtp_sidecar_probe.json`
    - Recorded example output (pinned antirez sidecar): `docs/mtp-sidecar-probe-antirez-b0c3326.json`
    - Recorded `model_contract_inspect_quantized_artifact.py` output (range-read header + tensor table only): `docs/gguf-inspect-antirez-b0c3326-mtp-sidecar.json`
    - llama.cpp Spark/CUDA local sanity check (metadata-only, no tensor payload alloc): `docs/llamacpp-mtp-sidecar-probe.md`
    - Metadata-only inspection confirms these sidecars can be `mtp_present == true` but still **incomplete** relative to the upstream `mtp.0.*` contract (example: pinned antirez sidecar has `mtp_tensor_count == 32` and `mtp_contract.complete == false`).
  - Generate an oracle that exercises the `MTPBlock.forward(...)` path and compare DS4 MTP logits against it.
  - Next gating experiment once an external runtime can load the sidecar: `docs/mtp-one-token-draft-probe.md` (one-token draft wiring probe; do not jump to acceptance metrics first).
    - Validate the probe JSON shape with: `python3 scripts/model_contract_validate_mtp_one_token_draft_probe.py --probe-json ...`

Pinned quantized/MTP status snapshot (metadata-only; **no full GGUF downloads**) (as of 2026-05-11; refreshed via `scripts/model_contract_refresh_v4flash_gguf_inspects.sh`):

Machine-readable view:

- `fixtures/model_contract/deepseek_v4_flash/pinned_gguf_inspects_summary.json` summarizes the pinned `docs/gguf-inspect-*.json` into a small fixture for tooling.
  - MTP namespace preservation: `items[].mtp_namespace.present_prefixes` (for example `["mtp.0."]` when an artifact set actually preserves the upstream `mtp.0.*` namespace).
  - Quant-format compatibility: `items[].quantization_contract.status` plus `items[].quantization_contract.notes_sample` (helps interpret single-Spark external-runtime results when artifacts are re-quantized or non-native).

| Pinned probe output | Artifact kind | `mtp_present` | `mtp_contract.complete` | Note |
|---|---|---:|---:|---|
| `docs/gguf-inspect-preyazz-6c6d74c-q4-k-m.json` | trunk GGUF | false | n/a | conversion dropped upstream `mtp.0.*` |
| `docs/gguf-inspect-nsparks-0b34e0b-fp4-fp8-native.json` | trunk GGUF | false | n/a | conversion dropped upstream `mtp.0.*` |
| `docs/gguf-inspect-antirez-b0c3326-iq2xxs-chat-v2.json` | trunk GGUF | false | n/a | conversion dropped upstream `mtp.0.*` |
| `docs/gguf-inspect-antirez-b0c3326-mtp-sidecar.json` | MTP sidecar GGUF | true | false | sidecar preserves `mtp.0.*` prefix (`mtp_namespace.present_prefixes=["mtp.0."]`) but remains incomplete + `mtp_keys_sha256` mismatch vs official `mtp.0.*` |
| `docs/gguf-inspect-antirez-b0c3326-iq2xxs-chat-v2-mtp-set.json` | trunk+sidecar set | true | false | combined artifact-set view (union key fingerprints); still incomplete MTP |

Machine-readable summary (built from the pinned `docs/gguf-inspect-*.json` files, so tools/CI can reason about “does this preserve upstream `mtp.0.*`?” without scraping Markdown):

- `fixtures/model_contract/deepseek_v4_flash/pinned_gguf_inspects_summary.json` (generated by `scripts/model_contract_summarize_v4flash_pinned_gguf_inspects.py`)

Refresh the pinned probe outputs reproducibly (header + tensor table Range reads only; refuses servers that don’t honor Range):

```bash
scripts/model_contract_refresh_v4flash_gguf_inspects.sh
```

Recommended DS4 comparison rule (when enabling DS4 gating):

- Compare **top-k token IDs** exactly and logits within a tolerance appropriate for FP8/FP4 kernels.
- Ensure the oracle covers both prefill (`start_pos == 0`) and decode (`start_pos > 0`) so KV-cache semantics are exercised.

Machine-readable MTP gating:

- `fixtures/model_contract/deepseek_v4_flash/contract_summary.json` records `mtp.trust_gates` so tooling can enforce a consistent “MTP is trusted only if…” policy.
- `scripts/model_contract_inspect_quantized_artifact.py` emits `mtp_trust` derived from `mtp_contract` + `mtp.trust_gates` (structural completeness is necessary but not sufficient; an MTP logits oracle is still required before enabling MTP in DS4).
- When `mtp_present==true`, `mtp_trust.reasons` also flags when `mtp_keys_sha256` does not match the official MTP subset fingerprint (`contract_summary.json` `mtp.checkpoint_key_fingerprint.keys_sha256`), which is a strong signal the artifact does not preserve the official checkpoint’s `mtp.0.*` key set.

## Comparator models (Ling / Qwen / DFlash pairs)

When Ling 2.6 Flash or Qwen-family models are used as baseline comparators, keep their notes **lightweight** and separate from DeepSeek V4 Flash MTP claims:

- Comparator doc: `docs/model-comparators.md`
- Metadata-only fixture fetcher (no weights): `scripts/model_contract_fetch_comparator_metadata.sh`
- Comparator fixtures live under: `fixtures/model_contract/comparators/`

For speculative-decoding “target + DFlash” baselines, keep DFlash draft assumptions in `docs/model-comparators.md` and avoid mixing them into DeepSeek V4 Flash MTP trust claims.
