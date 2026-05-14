# Centaur / DS4 Prefix KV Contract

Centaur should own the semantic prompt plan. DS4 should own the physical KV
realization. The boundary is a token-identical prefix artifact plus a suffix
packet that DS4 can append to a cached prefix state.

## KV Semantics

A KV cache entry is not reusable text. It is the layer-by-layer key/value tensor
state produced by one exact token prefix under one exact runtime configuration:

- model weights and quantization;
- tokenizer and chat/template renderer;
- token IDs, order, and count;
- RoPE/position settings and context length rules;
- KV dtype/layout and runtime cache format.

DS4 can append to a cached prefix only when the request tokens are exactly:

```text
cached_prefix_tokens || suffix_tokens
```

The append operation means DS4 runs the suffix tokens through the model while
using the cached prefix KV as history. It does not mean two independently built
KV caches can be concatenated. Independently built fragments have wrong
positions and attention history unless they were computed as one continuous
sequence.

## Recommended Centaur Shape

Centaur already has `hyor-prefix` for token-identical static prefixes and
`context-packet` for compact task context. DS4 should align with that split:

1. `hyor-prefix` builds a deterministic project skeleton prefix.
2. DS4 tokenizes and realizes that prefix into a physical KV snapshot.
3. Smartwalker returns selected DRY files and task instructions as an ordered
   suffix packet.
4. DS4 forks or resumes the skeleton KV, appends the suffix tokens, then decodes.

This gives the best economics for the current Centaur idea: cache the full
skeleton once, keep common skeleton KV hot on GPU when possible, and append the
small DRY files after it.

## DS4 Prefix Manifest V1

DS4 should accept a manifest like this from Centaur or produce the same fields
when it materializes a prefix:

```json
{
  "format": "ds4-prefix-manifest-v1",
  "centaur_prefix_format": "centaur-hyor-prefix-v1",
  "model_id": "deepseek-v4-flash-iq2xxs",
  "model_sha256": "...",
  "tokenizer_sha256": "...",
  "renderer_id": "centaur-static-prefix-v1",
  "rope_config_hash": "...",
  "kv_format": "ds4-kv-v1",
  "prefix_hash": "...",
  "prefix_token_count": 12345,
  "prefix_token_sha256": "...",
  "prefix_text_sha256": "...",
  "cache_key": "sha256(all identity fields above)",
  "cache_policy": "prefer_gpu",
  "created_at_unix": 1778760000
}
```

The token hash is the critical field. Text hashes are useful for debugging, but
token identity is what makes KV reuse valid.

## Context Packet V1

Centaur should send DS4 a task packet that keeps the prefix identity separate
from the suffix:

```json
{
  "format": "centaur-ds4-context-packet-v1",
  "request_id": "...",
  "prefix_cache_key": "...",
  "prefix_required": false,
  "suffix_token_sha256": "...",
  "suffix_token_count": 2048,
  "suffix_sections": [
    {"kind": "dry_file", "path": "src/foo.c", "sha256": "...", "order": 0},
    {"kind": "task", "path": "", "sha256": "...", "order": 1}
  ],
  "estimated_output_tokens": 128,
  "latency_class": "interactive"
}
```

If `prefix_required` is true and DS4 cannot prove a token-identical hit, DS4
should reject or defer the task. If it is false, DS4 may rebuild the prefix and
report the miss.

## DS4 Runtime API Sketch

The first useful API can be narrow:

```text
prefix_prepare(manifest, prefix_tokens) -> prefix_handle
prefix_pin(prefix_handle, tier=gpu|cpu|ssd) -> cache_status
prefix_fork(prefix_handle, request_id) -> session_handle
session_append(session_handle, suffix_tokens) -> append_status
session_decode(session_handle, decode_options) -> token_stream
session_release(session_handle)
prefix_release(prefix_handle)
```

DS4 can implement this with SSD snapshots first, then add GPU residency and
copy-on-write/forking. Centaur should not depend on the storage tier.

## Cache Tiers

- GPU hot tier: full skeleton prefixes and very common active sessions.
- CPU tier: warm prefixes that can be copied to GPU faster than recompute.
- SSD tier: cold snapshots and large skeletons.

Antirez putting KV on SSD is compatible with this contract. SSD is a storage
tier, not the semantic owner of the prefix. DS4 still has to load or page the KV
needed for active attention into GPU-accessible memory.

## Fragment Caching Rule

Common DRY files are tempting to cache as independent KV fragments, but they are
only KV-reusable at the same position after the same prefix. Until DS4 supports a
more advanced continuation tree, Centaur should maximize reuse by:

- keeping the static skeleton byte- and token-identical;
- sorting suffix DRY sections deterministically;
- placing highly common DRY sections early and consistently;
- treating arbitrary file snippets as token/text cache hits, not KV hits.

## Telemetry DS4 Should Return

Every completion should report:

- `prefix_cache_key`;
- `prefix_hit`: true/false;
- `prefix_tier`: `gpu`, `cpu`, `ssd`, `rebuilt`, or `none`;
- `prefix_load_ms`;
- `suffix_prefill_ms`;
- `decode_tokens_per_second`;
- `kv_bytes_reserved`;
- `gpu_kv_bytes_resident`;
- `queue_wait_ms`;
- `model_id` and `tokenizer_sha256`.

This is enough for Centaur to learn whether full-skeleton caching beats a more
selective smartwalker packet for each workload.
