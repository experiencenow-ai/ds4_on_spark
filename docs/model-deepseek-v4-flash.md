# DeepSeek V4 Flash (Execution Contract)

This document is **source-derived** from upstream DeepSeek V4 Flash configs and the official reference implementation shipped in the upstream model repo.

## Upstream source of truth

Upstream repo: `deepseek-ai/DeepSeek-V4-Flash`

Pinned upstream commit (from `X-Repo-Commit` on HF `resolve/main/*`): `6976c7ff1b30a1b2cb7805021b8ba4684041f136`

Files used for the contract (snapshotted in `fixtures/model_contract/deepseek_v4_flash/`):

- `config.json` (top-level architecture + per-layer `compress_ratios`)
- `model.safetensors.index.json` (authoritative tensor key set)
- `tokenizer.json`, `tokenizer_config.json` (tokenizer implementation + special tokens)
- `encoding/encoding_dsv4.py` + `encoding/tests/*` (chat/tool/thinking message rendering + test vectors)
- `inference/config.json`, `inference/model.py`, `inference/kernel.py` (reference execution semantics: CSA/HCA caches, MoE routing, MTP block)

## Topology constants (from `config.json`)

- `vocab_size`: 129280
- `hidden_size` / model `dim`: 4096
- `num_hidden_layers` / `n_layers`: 43
- `num_attention_heads`: 64
- `head_dim`: 512
- `num_key_value_heads`: 1 (MQA: one KV head shared by all Q heads)
- `q_lora_rank`: 1024
- `o_groups`: 8
- `o_lora_rank`: 1024
- `sliding_window` / `window_size`: 128
- `num_hash_layers` / `n_hash_layers`: 3 (first 3 MoE layers are hash-routed)
- MoE:
  - `n_routed_experts`: 256
  - `n_shared_experts`: 1
  - `num_experts_per_tok` / `n_activated_experts`: 6
  - `moe_intermediate_size` / `moe_inter_dim`: 2048
  - `scoring_func`: `sqrtsoftplus`
  - `routed_scaling_factor` / `route_scale`: 1.5
- MTP:
  - `num_nextn_predict_layers`: 1

## Attention schedule (sliding vs CSA vs HCA)

Upstream does **not** ship an explicit `layer_types[]` array in `config.json`. Instead, attention type is derived from the per-layer `compress_ratios[]` (see `inference/model.py`, `Attention.compress_ratio = args.compress_ratios[layer_id]`).

Interpretation (from `inference/model.py`):

- `compress_ratio == 0`: **sliding-window attention only**
  - KV cache stores only the local window.
  - YaRN is disabled for these layers (uses base `rope_theta`).
- `compress_ratio == 4`: **CSA** (Compressed Sparse Attention)
  - Uses a learned **Indexer** to pick `index_topk` compressed blocks per query.
  - KV cache has a sliding window segment plus a compressed segment sized by `max_seq_len // 4`.
- `compress_ratio != 0 and != 4` (V4 Flash uses `128`): **HCA** (hybrid compressed attention)
  - No Indexer path; compressed top-k indices come from the deterministic `get_compress_topk_idxs(...)`.
  - KV cache has a sliding window segment plus a compressed segment sized by `max_seq_len // 128`.
  - YaRN is enabled in these layers (uses `compress_rope_theta` and `original_seq_len`).

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
- Cache buffer name: `layers.{i}.attn.kv_cache` (runtime buffer; not in checkpoint)

Runtime update rules:

- **Prefill** (`start_pos == 0`):
  - Sliding KV window stores the most recent `window_size` KV vectors (wrapping behavior when `seqlen > window_size`).
  - If `compress_ratio != 0`, the layer’s `Compressor` may append compressed KV vectors which are concatenated into the KV tensor for sparse attention.
- **Decode** (`start_pos > 0`):
  - Sliding KV window updates at position `(start_pos % window_size)`.
  - If `compress_ratio != 0`, the layer’s `Compressor` updates the compressed KV cache segment in-place.

Sparse attention index selection:

- Always attends to the sliding window (`get_window_topk_idxs(...)`).
- If `compress_ratio != 0`, concatenates compressed indices:
  - CSA (`ratio==4`): `Indexer(...)` chooses indices.
  - HCA (`ratio==128`): `get_compress_topk_idxs(...)` chooses indices.

## MoE routing semantics (hash + score routing)

Reference implementation: `inference/model.py` (`Gate`, `MoE`).

Shared facts:

- Each MoE layer routes each token to `n_activated_experts=6` routed experts **plus** 1 shared expert.
- Expert outputs are accumulated (and `all_reduce`d across TP ranks) before adding the shared expert output.
- Routing weights:
  - `scoring_func == sqrtsoftplus` implemented as `sqrt(softplus(linear(...)))`
  - If not softmax, weights are normalized to sum to 1 before multiplying by `route_scale`.

Hash-routed bootstrap layers:

- For layers `0 <= layer_id < n_hash_layers` (here: layers 0–2), routing indices come from a static table:
  - tensor key: `layers.{i}.ffn.gate.tid2eid` (dtype `int32`)
- For these layers, `layers.{i}.ffn.gate.bias` is absent in the checkpoint.

Score-routed layers:

- For layers `layer_id >= n_hash_layers` (here: layers 3–42), routing indices come from score top-k:
  - tensor key: `layers.{i}.ffn.gate.bias` (float32) exists and is applied only for expert selection.
- The MTP block is also score-routed and includes `mtp.0.ffn.gate.bias`.

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

## Tokenizer + encoding contract

Tokenizer (from `tokenizer_config.json`):

- `tokenizer_class`: `PreTrainedTokenizerFast`
- `model_max_length`: 1048576
- `add_bos_token`: false
- `add_eos_token`: false
- BOS token string: `<｜begin▁of▁sentence｜>` (`bos_token_id: 0` in `config.json`)
- EOS token string: `<｜end▁of▁sentence｜>` (`eos_token_id: 1` in `config.json`)
- PAD token is EOS.

Message rendering:

- Upstream provides `encoding/encoding_dsv4.py` with templates for:
  - system/user/assistant messages
  - explicit thinking blocks (`<think>...</think>`)
  - DSML tool-call markup (e.g. `｜DSML｜tool_calls` blocks)
- The oracle for this repo is the upstream `encoding/tests/*` vectors.

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

## Next steps (oracle + remaining unknowns)

- Add a Spark-side logit oracle generator that runs the upstream reference implementation against a small prompt set **when weights are locally available** (do not auto-download shards).
- Record the exact `max_seq_len` and `max_batch_size` used for Spark baselines, since KV cache sizing depends on them.
