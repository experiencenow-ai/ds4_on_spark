# Model Comparators (Lightweight Contract Notes)

This repo’s **source-derived** execution contract work is centered on DeepSeek V4 Flash. When we run baseline comparisons against other models (e.g. Ling or Qwen-family), we only need a **lightweight** metadata contract so results are interpretable without pulling weights.

Goals for comparator notes:

- make baseline run reports reproducible (pin upstream commit + config)
- record tokenizer/chat-template invariants needed to reproduce prompts
- avoid mixing comparator assumptions with DeepSeek V4 Flash MTP claims
- **do not download weights** as part of comparator bookkeeping

## What to record (any comparator model)

Minimum fields needed to interpret “target-only”, “Qwen target-only”, “Ling target-only”, and “target + DFlash” results:

- HF `repo_id` + `rev` (or explicit commit hash)
- HF `X-Repo-Commit` for `config.json` at that rev
- `config.json` topology knobs (layers, hidden sizes, heads, MoE shape, context)
- tokenizer invariants:
  - `bos/eos/pad` token IDs (from `config.json` and/or `special_tokens_map.json`)
  - chat template source (`chat_template.jinja` or `tokenizer_config.json` `chat_template`)
  - `model_max_length` (tokenizer default vs runtime KV sizing are not the same; record both when available)
- runtime assumptions required to interpret results:
  - “trust remote code” required? (custom model types)
  - whether the runtime uses a chat template or raw prompt
  - which quant format / dtype was actually executed (BF16/FP8/INT4/etc)

## Metadata-only fetch (fixtures)

Use `scripts/model_contract_fetch_comparator_metadata.sh` to snapshot comparator metadata into `fixtures/model_contract/comparators/<name>/`:

```bash
scripts/model_contract_fetch_comparator_metadata.sh \
  --repo-id inclusionAI/Ling-2.6-flash \
  --rev main \
  --out-dir fixtures/model_contract/comparators/ling_2_6_flash
```

The script fetches only small metadata files (no weights) and generates `metadata_summary.json` for use in run reports.

## Ling 2.6 Flash

Fixture folder:

- `fixtures/model_contract/comparators/ling_2_6_flash/`
  - `metadata_summary.json` is the single “what did we pin?” view (repo/rev, `X-Repo-Commit`, key topology fields, and tokenizer invariants).

Notes:

- Ling is a **custom** Transformers model type (remote code). Always record the exact repo commit and the runtime’s `--trust-remote-code` / equivalent setting.
- Ling reports `num_nextn_predict_layers` in `config.json`. Treat this as “MTP artifacts exist”, but do **not** assume any particular MTP tensor namespace or speculative decode semantics without a model-specific oracle.

## Qwen-family (generic)

We do not pin a single Qwen variant in fixtures by default. When a specific Qwen model becomes a baseline comparator, create a fixture folder and record the same metadata set.

Keep Qwen comparator notes separate from DeepSeek V4 Flash MTP claims:

- Qwen results are used as “target-only” comparators (prompting + tokenizer + runtime behavior).
- DeepSeek V4 Flash MTP namespace / trust gates remain defined by `fixtures/model_contract/deepseek_v4_flash/contract_summary.json` and related tooling.
