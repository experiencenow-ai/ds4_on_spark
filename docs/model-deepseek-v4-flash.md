# DeepSeek V4 Flash (Execution Contract)

This document is **source-derived** from upstream DeepSeek V4 Flash configs and the official reference implementation shipped in the upstream model repo.

## Upstream source of truth

Upstream repo: `deepseek-ai/DeepSeek-V4-Flash`

Pinned upstream commit (from `X-Repo-Commit` on HF `resolve/main/*`): `6976c7ff1b30a1b2cb7805021b8ba4684041f136`

Files used for the contract (snapshotted in `fixtures/model_contract/deepseek_v4_flash/`):

- `DeepSeek_V4.pdf` (technical report; helps define intended CSA/HCA/Flash semantics)
- `config.json` (top-level architecture + per-layer `compress_ratios`)
- `upstream_commit.txt` (pinned upstream git commit hash)
- `contract_summary.json` (repo-generated, source-derived constants for DS4 consumption: topology, attention schedule, cache rules, runtime indexer/HC params, tensor-key invariants, config-field compatibility mappings, oracle requirements, and machine-readable logical tensor shapes; also includes sha256 fingerprints for pinned encoding oracle vectors and the oracle prompt set)
- `model.safetensors.index.json` (authoritative tensor key set)
- `tokenizer.json`, `tokenizer_config.json` (tokenizer implementation + special tokens)
- `encoding/encoding_dsv4.py` + `encoding/tests/*` (chat/tool/thinking message rendering + test vectors)
- `oracle/prompts.json` (prompt cases used by the logit-oracle generator)
- `inference/config.json`, `inference/model.py`, `inference/kernel.py` (reference execution semantics: MLA, sliding/CSA/HCA caches, MoE routing, MTP block)

Notes on config sources:

- `config.json` is the canonical Transformers config and contains all architectural constants.
- `inference/config.json` is the canonical runtime config for the upstream reference code. Some values are duplicated (e.g. `head_dim`), and some runtime-only defaults live there (e.g. `rope_head_dim` naming, `moe_inter_dim`).

## Contract map (machine-readable `contract_summary.json`)

DS4 tooling should treat `fixtures/model_contract/deepseek_v4_flash/contract_summary.json` as the machine-readable contract and use this document as the human explanation.

Key JSON paths by concern:

- Topology (layers/hidden/heads/vocab): `topology.*`
- Sliding/CSA/HCA schedule: `attention_schedule.compress_ratios`, `attention_schedule.type_counts`, and the derived Transformers compatibility arrays under `attention_schedule.transformers_*`
- Cache semantics (allocation + update + sparse-attn masking): `cache.kv_cache_sizes_at_reference_defaults`, `cache.update_semantics.*`, `cache.topk_mask_value`, `cache.sparse_attn_mask_rule`
- MLA positional split + RoPE: `mla.*`, `yarn_rope.*`
- MoE routing (hash vs score): `moe.*` (including `moe.hash_routing.*` and `moe.semantics.*`)
- MTP artifacts + trust gates: `mtp.*` (including `mtp.semantics.*` and `mtp.trust_gates.*`)
- Checkpoint tensor-key invariants + counts: `tensor_keys.*` and `checkpoint_index.*` (including `checkpoint_index.weight_map_prefix_fingerprints.mtp.*` to fingerprint the upstream `mtp.0.*` namespace)
- Quantization / scale-tensor expectations: `quantization.*` (notably `quantization.inference_config.*` and `quantization.linear_tensor_contract.*`)
- Tokenizer + encoding invariants: `tokenizer.*` and `encoding_constants.*` (encoding oracle vectors are pinned via `upstream.fixtures_sha256.*`)
- Correctness oracle requirements: `oracle.*`

Refresh + verify the pinned contract:

```bash
scripts/model_contract_refresh_deepseek_v4_flash.sh
```

When interpreting quantized single-Spark external-runtime results, prefer the contract-aware inspectors:

```bash
python3 scripts/model_contract_inspect_quantized_artifact.py --path /abs/path/to/model.gguf --json
```

## Topology constants (from `config.json` + `inference/config.json`)

- `vocab_size`: 129280
- `hidden_size` / model `dim`: 4096
- `num_hidden_layers` / `n_layers`: 43
- `num_attention_heads` / `n_heads`: 64
- `head_dim`: 512
- `qk_rope_head_dim` / `rope_head_dim`: 64 (RoPE applies to the **trailing** 64 dims of each head)
- `qk_nope_head_dim` / `nope_head_dim`: 448 (`head_dim - rope_head_dim`, non-positional slice)
- `num_key_value_heads`: 1 (shared KV; upstream uses a single latent KV vector per token)
- `q_lora_rank`: 1024
- `o_groups`: 8
- `o_lora_rank`: 1024
- `sliding_window` / `window_size`: 128
- CSA Indexer (from `config.json` + `inference/config.json`):
  - `index_n_heads`: 64
  - `index_head_dim`: 128
  - `index_topk`: 512
- Hyper-Connections (mHC):
  - `hc_mult`: 4
  - `hc_sinkhorn_iters`: 20
  - `hc_eps`: 1e-6
- `num_hash_layers` / `n_hash_layers`: 3 (first 3 MoE layers are hash-routed)
- MoE:
  - `n_routed_experts`: 256
  - `n_shared_experts`: 1
  - `num_experts_per_tok` / `n_activated_experts`: 6
  - `moe_intermediate_size` / `moe_inter_dim`: 2048
  - `swiglu_limit`: 10.0 (clamps expert activations in the reference code)
  - `scoring_func`: `sqrtsoftplus`
  - `routed_scaling_factor` / `route_scale`: 1.5
- MTP:
  - `num_nextn_predict_layers`: 1 (recorded in `contract_summary.json` as `mtp.n_mtp_layers` and `mtp.num_nextn_predict_layers`)
- YaRN / RoPE scaling (from `config.json` `rope_scaling` and `compress_rope_theta`, plus `inference/config.json`):
  - `rope_theta`: 10000
  - `compress_rope_theta`: 160000
  - `original_seq_len` / `original_max_position_embeddings`: 65536
  - `rope_factor`: 16
  - `beta_fast`: 32
  - `beta_slow`: 1

## Attention schedule summary (sliding vs CSA vs HCA)

Upstream encodes the per-layer cache mode as `compress_ratios[]`:

- `compress_ratios` length is `44`:
  - entries `0..42` are the 43 main trunk layers (`layers.{i}.*`)
  - entry `43` is the MTP layer (`mtp.0.*`)
- Main layer type counts (derived from `fixtures/model_contract/deepseek_v4_flash/config.json` and recorded in `contract_summary.json`):
  - sliding-only: 2 layers (`layer_id ∈ {0,1}`)
  - CSA (`compress_ratio == 4`): 21 layers
  - HCA (`compress_ratio == 128`): 20 layers
- Starting at `layer_id == 2`, the upstream schedule alternates `CSA, HCA, CSA, HCA, ...` and ends on CSA at `layer_id == 42`.
- MTP blocks are always sliding-only: `compress_ratios[n_layers + mtp_id] == 0`.

### Transformers schedule compatibility (layer_types / mlp_layer_types)

Transformers’ `DeepseekV4Config` exposes a per-layer schedule via string arrays:

- `config.layer_types[i] ∈ {"sliding_attention","compressed_sparse_attention","heavily_compressed_attention"}`
- `config.mlp_layer_types[i] ∈ {"hash_moe","moe"}`

The official `deepseek-ai/DeepSeek-V4-Flash` `config.json` shipped on HF does not currently include these arrays directly. DS4 therefore treats them as **derived compatibility views** of the pinned upstream contract:

- `fixtures/model_contract/deepseek_v4_flash/contract_summary.json` `attention_schedule.transformers_main_layer_types` derives `layer_types[]` from `compress_ratios[]` (`0→sliding_attention`, `4→compressed_sparse_attention`, `128→heavily_compressed_attention`).
- `fixtures/model_contract/deepseek_v4_flash/contract_summary.json` `attention_schedule.transformers_mtp_layer_types` derives MTP `layer_types[]` from the trailing `compress_ratios[n_layers + mtp_id]` entries (V4 Flash requires these to be `0` → `sliding_attention`).
- `fixtures/model_contract/deepseek_v4_flash/contract_summary.json` `attention_schedule.transformers_compress_rates` records the canonical compression-rate mapping used by the Transformers nomenclature (`CSA→4`, `HCA→128`, `sliding→0`).
- `fixtures/model_contract/deepseek_v4_flash/contract_summary.json` `moe.transformers_mlp_layer_types` derives `mlp_layer_types[]` from `num_hash_layers` (`0..num_hash_layers-1 → hash_moe`, remainder → moe).

Cache note (Transformers naming): non-sliding layers map to cache layer types (`DeepseekV4CSACache` for CSA and `DeepseekV4HCACache` for HCA), while sliding-only layers use sliding KV only.

## Logical parameter shapes (from `inference/model.py` + configs)

These shapes are the **logical (unsharded)** contract. The upstream reference code supports TP sharding (column/row parallel linears), but the checkpoint tensor keys in `model.safetensors.index.json` are expressed in the **global** namespace (see “Tensor key contract” below). The machine-readable shape contract is recorded under `fixtures/model_contract/deepseek_v4_flash/contract_summary.json` `tensor_shapes`.

Top-level:

- `embed.weight`: `[vocab_size, hidden_size]`
- `norm.weight`: `[hidden_size]`
- `head.weight`: `[vocab_size, hidden_size]`
- `hc_head_{fn,base,scale}`: `[hc_mult,hc_mult*hidden_size]`, `[hc_mult]`, `[1]` (Transformer HC head; per-layer HC uses `mix_hc=(2+hc_mult)*hc_mult` and `*.scale` length `3`)

Per-layer attention (`layers.{i}.attn.*`):

- `wq_a.weight`: `[q_lora_rank, hidden_size]` (low-rank Q factor A)
- `q_norm.weight`: `[q_lora_rank]` (RMSNorm in fp32)
- `wq_b.weight`: `[num_attention_heads*head_dim, q_lora_rank]` (low-rank Q factor B)
- `wkv.weight`: `[head_dim, hidden_size]` (shared KV latent)
- `kv_norm.weight`: `[head_dim]`
- `wo_a.weight`: `[o_groups*o_lora_rank, (num_attention_heads*head_dim)/o_groups]` (grouped low-rank O factor A)
- `wo_b.weight`: `[hidden_size, o_groups*o_lora_rank]` (low-rank O factor B)

Per-layer MoE (`layers.{i}.ffn.*`):

- `gate.weight`: `[n_routed_experts, hidden_size]`
- Hash gate (layers `0..n_hash_layers-1`): `gate.tid2eid`: `[vocab_size, n_activated_experts]` (int32)
- Score gate (layers `n_hash_layers..n_layers-1`): `gate.bias`: `[n_routed_experts]` (float32; selection-only)
- Expert FFN (logical shapes for each `experts.{eid}.w{1,2,3}`):
  - `w1`: `[moe_inter_dim, hidden_size]`
  - `w2`: `[hidden_size, moe_inter_dim]`
  - `w3`: `[moe_inter_dim, hidden_size]`

MTP (`mtp.{j}.*`):

- MTP blocks are implemented as `MTPBlock(Block)` in `fixtures/model_contract/deepseek_v4_flash/inference/model.py`, so the block-level shapes under `mtp.{j}.attn.*` / `mtp.{j}.ffn.*` match the trunk per-layer shapes under `layers.{i}.attn.*` / `layers.{i}.ffn.*` (machine-recorded in `contract_summary.json` under `tensor_shapes.mtp_per_layer`).
- MTP adds a small set of extra weights (notably `{e,h}_proj.*` and extra norms / HC head parameters) recorded in `contract_summary.json` under `tensor_shapes.mtp`.

## Quantization + scale tensors (FP8 trunk, FP4 experts)

Upstream sources: `config.json` (`quantization_config`; `expert_dtype` may be absent in some upstream revisions), `inference/config.json` (`expert_dtype`), and `inference/model.py` (`Linear`, `act_quant`, `fp4_gemm`/`fp8_gemm`).

Checkpoint formats:

- Trunk weights use FP8 (`e4m3`) with separate scale tensors:
  - `quantization_config.quant_method`: `fp8`
  - `quantization_config.fmt`: `e4m3`
  - `quantization_config.scale_fmt`: `ue8m0` (power-of-2 scale rounding / MXFP style)
  - `quantization_config.weight_block_size`: `[128,128]`
- Expert weights use FP4 (Flash `inference/config.json` `expert_dtype: fp4`):
  - In the reference `Linear`, FP4 weights are stored packed as `float4_e2m1fn_x2` with shape `[out_features, in_features//2]` (logically `[out_features, in_features]`).
  - FP4 scale tensors are `float8_e8m0fnu` with shape `[out_features, in_features//32]` (1 scale per 32 FP4 K-elements).
- Scale dtype default (source-derived): `inference/model.py` `ModelArgs.scale_dtype` defaults to `fp8`. When `scale_dtype == fp8`, `Transformer.__init__` forces `scale_fmt=ue8m0` and uses `float8_e8m0fnu` scale tensors; this is recorded in `contract_summary.json` under `quantization.inference_config.scale_dtype`.

Activation quantization in the reference runtime:

- GEMM input activations are block-quantized to FP8 in blocks of `block_size=128`.
- KV path uses QAT-style activation quantization on the **non-RoPE** dims only:
  - `act_quant(kv[..., :-rope_head_dim], block_size=64, inplace=True)` (RoPE slice stays BF16 for positional precision).
- KV compression has **two** quantization modes in the upstream reference code:
  - Attention KV compressor (`Attention.compressor`, `Compressor(rotate=false)`): `act_quant(kv[..., :-rope_head_dim], group=64, ...)` (FP8-simulated QAT on non-RoPE dims; RoPE slice stays BF16).
  - CSA Indexer scoring path (`Indexer.compressor`, `Compressor(rotate=true)`): `rotate_activation(kv); fp4_act_quant(kv, fp4_block_size=32, ...)` and `rotate_activation(q); fp4_act_quant(q, fp4_block_size=32, ...)` (Hadamard rotation + FP4 act quantization for the learned indexer’s q·k scoring).

DS4 must treat `*.scale` tensors and the block-size rules above as part of the execution contract; skipping them can preserve shapes but still diverge numerically.

Flash vs Flash-Base compatibility note:

- DeepSeek’s official HF ecosystem also publishes `deepseek-ai/DeepSeek-V4-Flash-Base` which differs in **expert quantization** (`expert_dtype="fp8"` vs Flash `expert_dtype="fp4"`). External runtimes (and conversion pipelines) must not mix these variants: expert dtype changes both the correct expert kernel family and the expected linear scale dtype/format behavior.
- For DS4 contract purposes, treat `quantization.inference_config.expert_dtype` as the canonical “Flash vs Base” switch (source-derived from upstream `inference/config.json`). If an external artifact/runtime cannot expose or preserve this field, treat MoE expert execution as **high risk** until validated by an oracle.

## Attention schedule (sliding vs CSA vs HCA)

Upstream does **not** ship an explicit `layer_types[]` array in `config.json`. Instead, attention type is derived from the per-layer `compress_ratios[]` (see `inference/model.py`, `Attention.compress_ratio = args.compress_ratios[layer_id]`).

Interpretation (from `inference/model.py`):

- `compress_ratio == 0`: **sliding-window attention only**
  - KV cache stores only the local window.
  - YaRN is disabled for these layers (uses base `rope_theta` and `original_seq_len=0`).
- `compress_ratio == 4`: **CSA** (Compressed Sparse Attention)
  - Uses a learned **Indexer** to pick up to `index_topk` compressed positions per query.
  - Compression uses overlapping windows (`Compressor.overlap == true` for `compress_ratio==4`).
  - KV cache has a sliding window segment plus a compressed segment sized by `max_seq_len // 4`.
- `compress_ratio != 0 and != 4` (V4 Flash uses `128`): **HCA** (hybrid compressed attention)
  - No Indexer path; compressed top-k indices come from the deterministic `get_compress_topk_idxs(...)`.
  - Compression uses non-overlapping windows (`Compressor.overlap == false`).
  - KV cache has a sliding window segment plus a compressed segment sized by `max_seq_len // 128`.
  - YaRN is enabled in these layers (uses `compress_rope_theta` and `original_seq_len=65536`).

Layer-by-layer `compress_ratio` schedule for the 43 main blocks:

`0,0,4,128,4,128,4,128,4,128,4,128,4,128,4,128,4,128,4,128,4,128,4,128,4,128,4,128,4,128,4,128,4,128,4,128,4,128,4,128,4,128,4`

There is one extra trailing `compress_ratios[]` entry (value `0`) used by the single MTP block (see “MTP” below).

Counts for the 43 main blocks:

- sliding (`0`): 2 (layers 0–1)
- CSA (`4`): 21
- HCA (`128`): 20

## Cache semantics (sliding + compressed KV)

Reference implementation: `inference/model.py` (`Attention.forward`).

Per-layer KV cache allocation:

- `kv_cache_size = window_size + (max_seq_len // compress_ratio if compress_ratio else 0)`
- Cache buffer name: `layers.{i}.attn.kv_cache` (runtime buffer; **not** in checkpoint)
- Cache buffer shape: `[max_batch_size, kv_cache_size, head_dim]`
  - `kv_cache[:,:window_size]` is a **ring buffer** for the sliding window (index `t % window_size` in decode).
  - `kv_cache[:,window_size:]` is a **linear** compressed segment (index `t // compress_ratio` in decode for `compress_ratio != 0`).

For the upstream reference defaults (`max_seq_len=4096`, `window_size=128`), the resulting per-layer `kv_cache_size` values are:

- sliding (`compress_ratio==0`): `128`
- CSA (`compress_ratio==4`): `128 + 4096//4 = 1152`
- HCA (`compress_ratio==128`): `128 + 4096//128 = 160`

These values (plus the full `kv_cache_size_by_layer[]` schedule) are recorded in `fixtures/model_contract/deepseek_v4_flash/contract_summary.json` under `cache.kv_cache_sizes_at_reference_defaults`.

Runtime update rules:

- **Prefill** (`start_pos == 0`):
  - Sliding KV window stores the most recent `window_size` KV vectors (wrapping behavior when `seqlen > window_size`).
  - If `compress_ratio != 0`, the layer’s `Compressor` may append compressed KV vectors which are concatenated into the KV tensor for sparse attention.
- **Decode** (`start_pos > 0`):
  - Sliding KV window updates at position `(start_pos % window_size)`.
  - If `compress_ratio != 0`, the layer’s `Compressor` updates the compressed KV cache segment in-place.
    - The compressed segment is updated only when the upstream `should_compress` gate fires: `should_compress = (start_pos + 1) % compress_ratio == 0` (decode-phase incremental compression pools exactly `compress_ratio` tokens per compressed KV vector).
    - Between compression steps, the `Compressor` updates its internal decode-state buffers (`kv_state` + `score_state`) but does not write a new compressed KV vector.
    - In prefill, only `seqlen // compress_ratio` compressed vectors are written; any remainder tokens are staged in `kv_state/score_state` so decode continues the partial block correctly.
    - RoPE is applied to the compressed KV using `freqs_cis` slices derived from the upstream expressions (recorded in the contract summary; see below).

These compressor/update semantics are extracted (source-derived) into `fixtures/model_contract/deepseek_v4_flash/contract_summary.json` under `cache.update_semantics.*` so DS4 can enforce them without re-parsing upstream Python.
In particular, the contract pins the exact prefill sliding-window ring-buffer writes for both `seqlen <= window_size` and the wrap case (`prefill_sliding_write_seqlen_{le,gt}_win_expr`), plus the compressor’s view of the compressed segment (`compressed_segment_view_expr`) and the prefill/decode top-k offset selection (`topk_offset_expr`).

Sparse attention index selection:

- Always attends to the sliding window (`get_window_topk_idxs(...)`).
- If `compress_ratio != 0`, concatenates compressed indices:
  - CSA (`ratio==4`): `Indexer(...)` chooses indices.
  - HCA (`ratio==128`): `get_compress_topk_idxs(...)` chooses indices.

Important indexing details (from `Attention.forward`):

- Prefill uses `kv` (length `seqlen`) concatenated with `kv_compress` (length `seqlen // ratio` when present). Compressed indices are offset by `seqlen`.
- Decode uses `kv_cache` directly; compressed indices are offset by `window_size` (the compressed segment starts at `kv_cache[:, window_size:]`).

### Sparse attention masking rule (sentinel indices)

Reference implementation: `inference/kernel.py` (`sparse_attn`).

- Sparse top-k index buffers use `topk_mask_value == -1` as a sentinel.
- When an index is masked (`idx == -1`), the kernel must behave as if `score=-inf` and `kv=0` (i.e. it contributes nothing to the softmax numerator and cannot introduce NaNs via invalid gathers).

These invariants are recorded in `fixtures/model_contract/deepseek_v4_flash/contract_summary.json` under `cache.topk_mask_value` and `cache.sparse_attn_mask_rule`.

### MLA positional semantics (partial RoPE + inverse on output)

Upstream applies RoPE only to the **trailing** `rope_head_dim` slice:

- Query path:
  - `qr = q_norm(wq_a(x))`
  - `q = wq_b(qr)` reshaped to `[B,S,n_heads,head_dim]`
  - `q *= rsqrt(mean(q^2) + eps)` (extra per-token normalization in the reference code)
  - `apply_rotary_emb(q[..., -rope_head_dim:], freqs_cis)`
- KV path (shared KV, no per-head split):
  - `kv = kv_norm(wkv(x))` shaped `[B,S,head_dim]`
  - `apply_rotary_emb(kv[..., -rope_head_dim:], freqs_cis)`
  - `act_quant(kv[..., :-rope_head_dim], group=64, ...)` (non-RoPE dims only; RoPE dims stay BF16)
- Attention output:
  - `o = sparse_attn(q, kv_cache_or_concat, attn_sink, topk_idxs, softmax_scale)`
  - `apply_rotary_emb(o[..., -rope_head_dim:], freqs_cis, inverse=True)` (**de-rotation** via complex conjugate)

DS4 must match the de-rotation step, or logits will diverge even if attention indexing is correct.

These MLA/cache update semantics are also extracted (source-derived) into `fixtures/model_contract/deepseek_v4_flash/contract_summary.json`:

- `mla.*` records the presence of the extra per-token Q normalization and the output de-rotation marker.
- `cache.update_semantics.*` records the decode-time KV ring-buffer update expression (`start_pos % win`) and the compressed-cache update expression (`start_pos // ratio`).

### Attention scaling + activation QAT constants

These constants are **source-derived** from `fixtures/model_contract/deepseek_v4_flash/inference/model.py` and are recorded in `fixtures/model_contract/deepseek_v4_flash/contract_summary.json` under `quantization.inference_model_constants` to avoid accidental drift:

- KV activation QAT group size(s): `kv_act_quant_group_sizes` (expected: `[64]`; enforced by `scripts/model_contract_verify_deepseek_v4_flash.py`)
- Attention softmax scaling expression: `attn_softmax_scale_expr` (expected: `self.head_dim ** -0.5`)
- CSA Indexer per-token weights scaling expression: `indexer_weights_expr` (expected: `self.weights_proj(x) * (self.softmax_scale * self.n_heads ** -0.5)`)

### Attention sink semantics (`attn_sink`)

Reference implementation: `inference/kernel.py` (`sparse_attn`).

- Each attention head has a learned scalar `attn_sink[h]`.
- The sink contributes to the **softmax denominator** as an extra `exp(attn_sink[h])` term (i.e. it is a null/sink logit with no value vector contribution).
- DS4 must treat `layers.{i}.attn.attn_sink` as semantically significant, not a no-op parameter.

## MoE routing semantics (hash + score routing)

Reference implementation: `inference/model.py` (`Gate`, `MoE`).

Shared facts:

- Each MoE layer routes each token to `n_activated_experts=6` routed experts **plus** 1 shared expert.
- Expert outputs are accumulated (and `all_reduce`d across TP ranks) before adding the shared expert output.
- Routing weights:
  - Gate scores are computed in float32 (`linear(x.float(), gate.weight.float())`) even if the trunk runs in lower precision.
  - `scoring_func == sqrtsoftplus` implemented as `sqrt(softplus(linear(...)))`
  - If not softmax, weights are normalized to sum to 1 before multiplying by `route_scale`.

Hash-routed bootstrap layers:

- For layers `0 <= layer_id < n_hash_layers` (here: layers 0–2), routing indices come from a static table:
  - tensor key: `layers.{i}.ffn.gate.tid2eid` (dtype `int32`)
  - logical shape: `[vocab_size, n_activated_experts]` (here: `[129280, 6]`), indexed by `input_ids`
- For these layers, `layers.{i}.ffn.gate.bias` is absent in the checkpoint.
- Even in hash mode, the gate still computes scores and routing weights from hidden state:
  - `tid2eid[input_ids]` selects the expert IDs
  - weights are computed by gathering the **unbiased** `original_scores` at those IDs, normalizing, then applying `route_scale`.

Score-routed layers:

- For layers `layer_id >= n_hash_layers` (here: layers 3–42), routing indices come from score top-k:
  - tensor key: `layers.{i}.ffn.gate.bias` (float32) exists and is applied only for expert selection.
- Routing weights are always gathered from the **unbiased** `original_scores` (bias shifts top-k selection but does not change weights).
- The MTP block is also score-routed and includes `mtp.0.ffn.gate.bias`.

These MoE gating rules are also extracted (source-derived) into `fixtures/model_contract/deepseek_v4_flash/contract_summary.json` under:

- `moe.semantics` (score computation + normalization + scaling expressions)
- `moe.hash_routing` (hash-gating enable/indices expressions + `tid2eid` shape/dtype)

## Hyper-Connections (mHC)

Reference implementation: `inference/model.py` (`Block`).

- Hidden state is represented as `hc_mult` parallel streams: runtime tensor shape `[B, S, hc_mult, dim]`.
- Each block performs:
  1. HC pre-mix → attention → HC post-mix
  2. HC pre-mix → MoE → HC post-mix
- Key checkpoint tensors per block:
  - `layers.{i}.hc_attn_fn`, `layers.{i}.hc_attn_base`, `layers.{i}.hc_attn_scale`
  - `layers.{i}.hc_ffn_fn`, `layers.{i}.hc_ffn_base`, `layers.{i}.hc_ffn_scale`

## MTP (multi-token prediction) artifacts

Reference implementation: `inference/model.py` (`MTPBlock`, `Transformer.mtp`).

- The checkpoint includes an `mtp.*` module namespace (see `model.safetensors.index.json`).
- `Transformer` constructs `args.n_mtp_layers` MTP blocks (default is 1) with `layer_id = args.n_layers + mtp_layer_id`.
  - This makes the MTP block read `compress_ratios[43]`, which is the extra trailing `0` (sliding-only) entry.
- `Transformer.forward(...)` returns normal next-token logits and does **not** invoke `mtp` by default.
  - MTP is a separate callable for speculative/next-n prediction and must be explicitly integrated by DS4.

`MTPBlock.forward(...)` contract (from `inference/model.py`):

- Inputs:
  - `x`: hidden state shaped `[B,S,hc_mult,dim]` (same HC stream layout as the main trunk)
  - `input_ids`: `[B,S]` token ids for the same positions
- Computation:
  1. `e = embed(input_ids)` then `e = enorm(e)`
  2. `x = hnorm(x)`
  3. `x = e_proj(e).unsqueeze(2) + h_proj(x)`
  4. Run the normal `Block` forward (attention + MoE + HC mixing).
  5. Compute logits with a **separate** HC head: `hc_head_{fn,base,scale}` under `mtp.0.*`.

These key MTP expressions are also extracted into `fixtures/model_contract/deepseek_v4_flash/contract_summary.json` under `mtp.semantics` and gated by `scripts/model_contract_verify_deepseek_v4_flash.py`.

DS4 must treat `mtp.*` as a distinct draft-model path with its own HC head weights, not just an alias to the main head.

## Tokenizer + encoding contract

Tokenizer (from `tokenizer_config.json`):

- `tokenizer_class`: `PreTrainedTokenizerFast`
- `model_max_length`: 1048576
- Note: `model_max_length` is a permissive tokenizer cap. Upstream runtime defaults are `max_seq_len=4096` and `window_size=128` (see `fixtures/model_contract/deepseek_v4_flash/inference/config.json` and `fixtures/model_contract/deepseek_v4_flash/contract_summary.json` `runtime.reference_defaults`); KV/cache sizing must use runtime settings, not `model_max_length`.
- `add_bos_token`: false
- `add_eos_token`: false
- BOS token string: `<｜begin▁of▁sentence｜>` (`bos_token_id: 0` in `config.json`)
- EOS token string: `<｜end▁of▁sentence｜>` (`eos_token_id: 1` in `config.json`)
- PAD token is EOS.

Tokenizer backend (from `tokenizer.json`):

- Model: `BPE` (base vocab size 128000 + merges; effective vocab size matches `vocab_size=129280` once added tokens are applied).
- Pre-tokenizer: a `Sequence` of 3 `Split` regex passes followed by `ByteLevel` (this controls the **exact** text → byte-level pieces fed into BPE).
- Post-processor + decoder: `ByteLevel`.

These backend pipeline facts (including the exact `Split` regex patterns and `ByteLevel` flags) are recorded in `fixtures/model_contract/deepseek_v4_flash/contract_summary.json` under `tokenizer.tokenizer_json_summary` so external runtimes can reproduce tokenization without guessing.

Tokenizer added-token ID range note:

- The raw `tokenizer.json` `added_tokens[]` list can include tokens whose IDs are within the base BPE vocab range (e.g. BOS/EOS). For the contiguous “extra IDs above base vocab” range, use `tokenizer.tokenizer_json_summary.{added_token_id_min_ge_base_vocab,added_token_id_max_ge_base_vocab,added_tokens_count_ge_base_vocab}` from `contract_summary.json`.

Message rendering:

- Upstream provides `encoding/encoding_dsv4.py` with templates for:
  - system/user/assistant messages
  - explicit thinking blocks (`<think>...</think>`)
  - DSML tool-call markup (e.g. `｜DSML｜tool_calls` blocks)
- The oracle for this repo is the upstream `encoding/tests/*` vectors.

The upstream string constants used by the encoder (`bos_token`, `eos_token`, `thinking_*`, `dsml_token`, etc.) are also extracted into `fixtures/model_contract/deepseek_v4_flash/contract_summary.json` under `encoding_constants`.

In addition to the special tokens, the contract summary records the **exact upstream message/tool templates** required to reproduce prompt rendering in external runtimes:

- `encoding_constants.{system,user,latest_reminder}_msg_template`
- `encoding_constants.assistant_msg_template` and `encoding_constants.assistant_msg_wo_eos_template`
- `encoding_constants.thinking_template`
- `encoding_constants.tool_call_template` and `encoding_constants.tool_calls_template`
- Role markers: `encoding_constants.{user,assistant,latest_reminder}_sp_token`
- Task-classifier tokens: `encoding_constants.ds_task_sp_tokens`

## Tensor key contract (checkpoint naming)

Authoritative source: `model.safetensors.index.json` (weight map keys).

Key namespaces (top-level prefixes):

- `embed.*`: token embedding
- `layers.{i}.*`: 43 decoder blocks
- `head.*`, `norm.*`: final head/norm
- `hc_head_*`: final HC head mixing parameters
- `mtp.{j}.*`: MTP blocks (here: `mtp.0.*`)

Important conditional tensors:

- `layers.{i}.ffn.gate.tid2eid` exists **only** for `i ∈ {0,1,2}`.
- `layers.{i}.ffn.gate.bias` exists for `i ≥ 3` (40 layers total), plus `mtp.0.ffn.gate.bias`.

Quantized linear layers include per-block scale tensors:

- For FP8 and FP4 weights, each linear has:
  - `{...}.weight`
  - `{...}.scale`

DS4 must treat the `model.safetensors.index.json` key set as authoritative for loader compatibility.

To make the key set easy to reference in downstream tooling (and to detect accidental fixture drift), `fixtures/model_contract/deepseek_v4_flash/contract_summary.json` records a stable fingerprint of the sorted weight-map keys:

- `checkpoint_index.weight_map_num_tensors`
- `checkpoint_index.weight_map_keys_sha256`
- `checkpoint_index.weight_map_prefix_fingerprints` (per top-level prefix, including `layers` and `mtp`)
- `checkpoint_index.weight_map_file_counts` (how many keys map to each shard filename, from `model.safetensors.index.json`)

### Quantization scale tensor semantics (FP8/FP4)

Reference implementation: `inference/model.py` (`Linear`, `linear(...)`).

DeepSeek V4 Flash uses **block-scaled** quantized weights:

- FP8 weights (`torch.float8_e4m3fn`):
  - logical weight shape: `[out_features, in_features]`
  - scale dtype: `torch.float8_e8m0fnu`
  - scale shape: `[(out_features+block_size-1)//block_size, (in_features+block_size-1)//block_size]` (with `block_size=128`)
- FP4 expert weights (`torch.float4_e2m1fn_x2`):
  - storage weight shape: `[out_features, in_features//2]` (packed 2 fp4 per byte)
  - logical weight shape: `[out_features, in_features]`
  - scale dtype: `torch.float8_e8m0fnu`
  - scale shape: `[out_features, in_features//fp4_block_size]` (with `fp4_block_size=32`)

These invariants are recorded in `fixtures/model_contract/deepseek_v4_flash/contract_summary.json` under `quantization.linear_tensor_contract`.

### Tensor key patterns (loader contract)

The weight map contains 69,187 tensor keys. DS4 should validate **patterns**, not enumerate individual keys in source.

Top-level keys:

- `embed.weight`
- `norm.weight`
- `head.weight`
- `hc_head_fn`, `hc_head_base`, `hc_head_scale`

Per-layer keys (for `layers.{i}.*`, `i ∈ [0,42]`):

- Always present:
  - `layers.{i}.attn.attn_sink`
  - `layers.{i}.attn.wq_a.{weight,scale}`
  - `layers.{i}.attn.q_norm.weight`
  - `layers.{i}.attn.wq_b.{weight,scale}`
  - `layers.{i}.attn.wkv.{weight,scale}`
  - `layers.{i}.attn.kv_norm.weight`
  - `layers.{i}.attn.wo_a.{weight,scale}`
  - `layers.{i}.attn.wo_b.{weight,scale}`
  - `layers.{i}.attn_norm.weight`
  - `layers.{i}.ffn.gate.weight`
  - `layers.{i}.ffn.shared_experts.w{1,2,3}.{weight,scale}`
  - `layers.{i}.ffn.experts.{eid}.w{1,2,3}.{weight,scale}` for all `eid ∈ [0,255]`
  - `layers.{i}.ffn_norm.weight`
  - `layers.{i}.hc_attn_{fn,base,scale}`, `layers.{i}.hc_ffn_{fn,base,scale}`
- MoE gate conditional:
  - Hash layers (`i < 3`): `layers.{i}.ffn.gate.tid2eid` present and `layers.{i}.ffn.gate.bias` absent
  - Score layers (`i >= 3`): `layers.{i}.ffn.gate.bias` present and `layers.{i}.ffn.gate.tid2eid` absent
  - Gate parameter semantics (from upstream `Gate` in `inference/model.py`):
    - `ffn.gate.tid2eid`: `int32` lookup table shaped `[vocab_size,n_activated_experts]` that deterministically chooses the top‑k expert IDs per token ID (hash routing).
    - `ffn.gate.bias`: `float32` vector shaped `[n_routed_experts]` that shifts expert *selection* scores (top‑k) without changing the final routing weights (score routing).
- Cache compression conditional:
  - `compress_ratio == 0`: no `layers.{i}.attn.compressor.*` and no `layers.{i}.attn.indexer.*`
  - `compress_ratio == 4` (CSA): must include:
    - `layers.{i}.attn.compressor.{ape,norm.weight,wgate.weight,wkv.weight}`
    - `layers.{i}.attn.indexer.wq_b.{weight,scale}`
    - `layers.{i}.attn.indexer.weights_proj.weight`
    - `layers.{i}.attn.indexer.compressor.{ape,norm.weight,wgate.weight,wkv.weight}`
  - `compress_ratio == 128` (HCA): must include `layers.{i}.attn.compressor.{...}` and must **not** include `layers.{i}.attn.indexer.*`

#### Machine-readable required suffix sets (exact tensor names)

The checkpoint key set is large, but the contract includes an **exact** machine-readable “minimum required suffix set” for each namespace in:

- `fixtures/model_contract/deepseek_v4_flash/contract_summary.json` `tensor_keys.*`

Top-level required keys (`tensor_keys.required_top_level`):

- `embed.weight`
- `norm.weight`
- `head.weight`
- `hc_head_fn`
- `hc_head_base`
- `hc_head_scale`

Per-layer required suffixes (`tensor_keys.required_layer_suffixes`, appended under `layers.{i}.` for all `i ∈ [0,42]`):

- `attn.attn_sink`
- `attn.wq_a.weight`, `attn.wq_a.scale`
- `attn.q_norm.weight`
- `attn.wq_b.weight`, `attn.wq_b.scale`
- `attn.wkv.weight`, `attn.wkv.scale`
- `attn.kv_norm.weight`
- `attn.wo_a.weight`, `attn.wo_a.scale`
- `attn.wo_b.weight`, `attn.wo_b.scale`
- `attn_norm.weight`
- `ffn.gate.weight`
- `ffn.shared_experts.w1.weight`, `ffn.shared_experts.w1.scale`
- `ffn.shared_experts.w2.weight`, `ffn.shared_experts.w2.scale`
- `ffn.shared_experts.w3.weight`, `ffn.shared_experts.w3.scale`
- `ffn_norm.weight`
- `hc_attn_fn`, `hc_attn_base`, `hc_attn_scale`
- `hc_ffn_fn`, `hc_ffn_base`, `hc_ffn_scale`

Expert-key completeness expectation (`contract_summary.json` `tensor_keys.expected_expert_key_count_per_layer`):

- For each layer, there must be `256 experts × 3 linears × 2 tensors (weight+scale) = 1536` expert keys of the form `layers.{i}.ffn.experts.{eid}.w{1,2,3}.{weight,scale}` with `eid ∈ [0,255]`.

Cache-compression required suffixes:

- For any compressed layer (`compress_ratio != 0`), the layer must include (`tensor_keys.required_layer_suffixes_compress_ratio_nonzero`):
  - `attn.compressor.ape`
  - `attn.compressor.norm.weight`
  - `attn.compressor.wgate.weight`
  - `attn.compressor.wkv.weight`
- For CSA layers (`compress_ratio == 4`), the layer must additionally include (`tensor_keys.required_layer_suffixes_compress_ratio_4`):
  - `attn.indexer.wq_b.weight`, `attn.indexer.wq_b.scale`
  - `attn.indexer.weights_proj.weight`
  - `attn.indexer.compressor.ape`
  - `attn.indexer.compressor.norm.weight`
  - `attn.indexer.compressor.wgate.weight`
  - `attn.indexer.compressor.wkv.weight`

MoE gate conditional keys:

- Hash layers: require `ffn.gate.tid2eid` and forbid `ffn.gate.bias` (`tensor_keys.layer_gate.tid2eid_layer_ids == [0,1,2]`).
- Score layers: require `ffn.gate.bias` and forbid `ffn.gate.tid2eid` (`tensor_keys.layer_gate.gate_bias_layer_ids == [3..42]`).

MTP block (`mtp.0.*`):

- Includes the same attention/MoE/HC keys as a score-routed sliding-only layer, plus:
  - `mtp.0.e_proj.{weight,scale}`, `mtp.0.h_proj.{weight,scale}`
  - `mtp.0.enorm.weight`, `mtp.0.hnorm.weight`, `mtp.0.norm.weight`
  - `mtp.0.hc_head_{fn,base,scale}`
- Official checkpoints share the top-level `embed.*`/`head.*` weights with MTP; `mtp.0.embed.*` and `mtp.0.head.*` are not present. This is machine-recorded in `contract_summary.json` via `tensor_keys.mtp_embed_present=false` / `tensor_keys.mtp_head_present=false`, and the additional MTP-only suffixes are listed under `tensor_keys.required_mtp_additional_suffixes`.
- `contract_summary.json` also records the expected per-MTP-layer tensor-key count (`tensor_keys.mtp_expected_tensor_key_count_per_layer`) and the observed counts in the official safetensors index (`tensor_keys.mtp_tensor_key_count_by_layer_id`) so tooling can sanity-check “full upstream `mtp.0.*` preserved?” quickly.

This repo includes a verifier for these invariants: `scripts/model_contract_verify_deepseek_v4_flash.py`.

## Quantized single-Spark compatibility

The first Spark0 token-generation milestone may use a community GGUF or runtime
fork before DS4 has a native loader. Treat that as an execution baseline only:
the source-derived contract above remains authoritative.

For each quantized artifact tested, record:

- artifact format (`GGUF`, HF safetensors, or other) and the inspector `artifact_type` (`gguf.url`, `gguf`, etc.)
- declared quant (`Q2_K`, `Q3_K_M`, native `F8_E4M3 + MXFP4`, etc.)
- declared base model and conversion path
- runtime repo, branch, and commit required to load it
- whether the runtime claims to preserve native FP8/FP4 scales or has
  re-quantized through another representation
- tokenizer/chat-template behavior used for the prompt
- captured quantization metadata from `scripts/model_contract_inspect_quantized_artifact.py`:
  - `tensor_type_counts` (overall GGUF tensor types present)
  - `tensor_type_profile` (expert vs dense type split when keys match known DeepSeek-V4 GGUF naming)
  - `quantization_contract` (when `fixtures/model_contract/deepseek_v4_flash/contract_summary.json` is available: contract-aware “Flash native FP8/FP4-like?” hint derived from `tensor_type_profile` vs `quantization.inference_config`)
  - contract-aware key completeness outputs (emitted when run from this repo or with `--contract-summary`):
    - `mtp_namespace` (`has_mtp0`, `expected_layer_ids`, `expected_complete`)
    - `mtp_contract` (`checked`, `complete`, `missing_required_count`, `forbidden_present`)
    - `mtp_trust` (`status`; always untrusted until an oracle includes MTP)
    - `trunk_contract` (`checked`, `complete`) when tensor keys preserve `layers.{i}.*`
    - `topology_contract.mismatches` when GGUF header metadata is present

Any successful external-runtime output must still be followed by a contract
check: prompt rendering must match the encoding oracle, and native DS4 logits
must eventually be validated against official-source oracle fixtures.

### MTP + quantized artifacts

Official-source safetensors **do** include the MTP namespace:

- `fixtures/model_contract/deepseek_v4_flash/model.safetensors.index.json` contains `mtp.0.*` (1,575 tensor keys as of the pinned upstream commit).

As of 2026-05-11, metadata-only inspections of pinned community GGUF trunk artifacts (see `docs/quantized-single-spark.md`) reported `mtp_present=false` and `tensor_key_namespace_guess=llama.cpp`, i.e. they did not preserve the upstream `mtp.0.*` tensor namespace.

Recorded probe outputs (range-read header + tensor table only; no full downloads):

- `docs/gguf-inspect-preyazz-6c6d74c-q4-k-m.json`
- `docs/gguf-inspect-nsparks-0b34e0b-fp4-fp8-native.json`
- `docs/gguf-inspect-antirez-9cb905d-iq2xxs-chat-v2.json`
- The nsparks “native FP4/FP8” GGUF includes DeepSeek4 fork `ggml_type` tensors like `F8_E4M3_B128` (commonly type code `42`) and MoE experts as `MXFP4`, but the pinned artifact is still a **mixed** type set (many `F32`/`BF16` tensors). Treat this as non-authoritative for “Flash-native” quant semantics unless `quantization_contract.{dense_fp8_like,expert_fp4_like}` is satisfied.
- These three pinned trunk GGUFs report `mtp_present=false`, `mtp_namespace.has_mtp0=false`, and `mtp_trust.status=absent` (i.e. they do **not** preserve the upstream `mtp.0.*` namespace).
- To refresh the pinned probe JSON outputs reproducibly (metadata-only Range reads; refuses servers that don’t honor Range), run: `scripts/model_contract_refresh_v4flash_gguf_inspects.sh`.

Pinned GGUF MTP status snapshot (as of 2026-05-11; derived from the JSON probe outputs above):

| Artifact set | Probe JSON | `mtp_present` | `mtp_namespace.has_mtp0` | `mtp_contract.complete` | `mtp_trust.status` |
|---|---|---:|---:|---:|---|
| Preyazz trunk (`Q4_K_M`) | `docs/gguf-inspect-preyazz-6c6d74c-q4-k-m.json` | false | false | — | absent |
| nsparks trunk (mixed `F32` + `F8_E4M3_B128`; experts `MXFP4`) | `docs/gguf-inspect-nsparks-0b34e0b-fp4-fp8-native.json` | false | false | — | absent |
| antirez trunk (IQ2XXS/Q2_K/Q8_0 mix) | `docs/gguf-inspect-antirez-9cb905d-iq2xxs-chat-v2.json` | false | false | — | absent |
| antirez MTP sidecar (separate file) | `docs/gguf-inspect-antirez-9cb905d-mtp-sidecar.json` | true | true | false | incomplete |

For external/quantized artifacts:

- Do **not** assume `mtp.0.*` survives conversion into GGUF or other derived formats.
- Some community GGUF conversions ship `mtp.0.*` as a **separate sidecar** file rather than embedding it in the trunk GGUF. Treat MTP presence as a property of the artifact **set**, not just one file.
- At least one pinned candidate (`docs/upstream-quantized-v4-flash.md`: `antirez/deepseek-v4-gguf`) explicitly publishes an MTP sidecar GGUF; expect the trunk GGUF to be missing `mtp.0.*` unless both files are supplied to the runtime.
- Treat MTP as **disabled/untrusted** unless the artifact is inspected and proven to contain `mtp.0.*` weights (and, ideally, MTP passes an oracle check; see below).
- Record whether the runtime can expose draft logits or draft token IDs.
- A successful MTP speedup is not enough by itself; the acceptance path must be
  reproducible under deterministic sampling and must be disableable for oracle
  comparisons.

To inspect a trunk+sidecar pair, pass both paths:

```sh
python3 scripts/model_contract_inspect_quantized_artifact.py --path /abs/path/to/trunk.gguf --path /abs/path/to/mtp_sidecar.gguf --json
```

For Hugging Face-hosted GGUFs, `model_contract_inspect_quantized_artifact.py` can also do range-read inspection (header + tensor table only; no full download). Record the `url_prefix_bytes`:

```sh
python3 scripts/model_contract_inspect_quantized_artifact.py --url https://huggingface.co/<repo>/resolve/<rev>/<file>.gguf --json
```

When run from this repo (or when `--contract-summary` points at `fixtures/model_contract/deepseek_v4_flash/contract_summary.json`), the JSON output also includes `mtp_namespace`, `mtp_contract`, and `mtp_trust`.

When multiple `--path` values are provided, the tool emits both:

- per-artifact `topology_contract` (computed from that artifact's captured GGUF header metadata, when present)
- a `combined.topology_contract` computed from the GGUF path with the most tensors (`combined.topology_contract_source_path` records which)

Some DS4-tuned MTP sidecars (notably `antirez/deepseek-v4-gguf`) are published as a compact 32‑tensor `mtp.0.*` table with `general.architecture=deepseek4_mtp_support` (not a full official `mtp.0.*` checkpoint). Validate these sidecars explicitly before trying to load them in external runtimes:

```sh
python3 scripts/model_contract_probe_mtp_sidecar.py --path /abs/path/to/DeepSeek-V4-Flash-MTP-*.gguf --json
# Or, for metadata-only validation without a full download:
python3 scripts/model_contract_probe_mtp_sidecar.py --url https://huggingface.co/.../DeepSeek-V4-Flash-MTP-*.gguf --json
```

Recorded example output (pinned antirez sidecar): `docs/mtp-sidecar-probe-antirez-9cb905d.json`.
Recorded `model_contract_inspect_quantized_artifact.py` output (same pinned antirez sidecar; metadata-only range read): `docs/gguf-inspect-antirez-9cb905d-mtp-sidecar.json`.

As of 2026-05-11, metadata-only inspection of the pinned antirez sidecar (`scripts/model_contract_inspect_quantized_artifact.py --url ... --json`) reports `mtp_present=true` but `mtp_contract.complete=false` with only `mtp_tensor_count=32` (i.e. the sidecar is **not** a full upstream `mtp.0.*` checkpoint).
- The same inspection reports `mtp_namespace.has_mtp0=true` and `mtp_trust.status=incomplete` (the `mtp.0.*` prefix exists, but the tensor set does not satisfy the upstream MTP contract).

- Require `mtp_contract.checked == true` and `mtp_contract.complete == true` before claiming an artifact “preserves MTP”.
- If `mtp_present == true` but `mtp_contract.complete == false`, treat MTP as **incomplete** (disabled/untrusted) until proven otherwise.
- When `--contract-summary` is available, `scripts/model_contract_inspect_quantized_artifact.py` also emits `mtp_trust` (driven by `contract_summary.json` `mtp.trust_gates`) to make trust gates explicit in JSON (including namespace failures like `namespace_incomplete` / `namespace_missing_mtp0`).
- Also record and review:
  - `tensor_key_namespace_guess` (many GGUF conversions rename tensor keys; `trunk_contract` is only meaningful when `trunk_contract.checked == true`)
  - `trunk_contract.complete == true` (upstream tensor-key completeness for `embed.*` + `layers.{i}.*`; only meaningful when `trunk_contract.checked == true`)
  - `topology_contract.mismatches` (GGUF header metadata vs expected topology); non-empty mismatches make the artifact suspect until explained.

MTP acceptance gates (high-performance / quantized path):

- Structural gate: `mtp_contract.complete == true` (and `mtp_namespace.has_mtp0 == true`) is necessary to claim the artifact preserves upstream `mtp.0.*`.
- Oracle gate: even if structurally complete, treat MTP as **untrusted** until a logits oracle that includes MTP traces is generated and passed (`scripts/model_contract_generate_deepseek_v4_flash_oracle.py --include-mtp`; compare both prefill + decode; top-k IDs must match exactly; see `contract_summary.json` `mtp.trust_gates`).

## Next steps (oracle + remaining unknowns)

- The encoding oracle is fully local and is executed by `scripts/model_contract_verify_deepseek_v4_flash.py`.
- A Spark-side logit oracle generator is provided:
  - Prompt cases: `fixtures/model_contract/deepseek_v4_flash/oracle/prompts.json`
  - Generator (weights required): `scripts/model_contract_generate_deepseek_v4_flash_oracle.py`
  - Output (commit only after review): `fixtures/model_contract/deepseek_v4_flash/oracle/logits_oracle.json`
- The verifier enforces that any committed `logits_oracle.json` matches the pinned `upstream_commit.txt` and records core runtime metadata (TP size, seed, tokenizer hashes).
- Upstream reference defaults are `max_seq_len=4096` and `max_batch_size=4` (see `fixtures/model_contract/deepseek_v4_flash/contract_summary.json` `runtime.reference_defaults`), but Spark baselines may override them; record the exact values used since KV cache sizing depends on them.

Before relying on MTP for speculative decoding, extend the logit oracle to cover the `mtp` path (weights required) and gate DS4’s `mtp` implementation against it.

The oracle generator supports this by adding `--include-mtp`, which records `cases[].mtp_trace[]` (draft logits from `MTPBlock.forward(...)`) alongside the main trunk `cases[].trace[]`.
