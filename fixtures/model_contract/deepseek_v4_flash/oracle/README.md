# DeepSeek V4 Flash correctness oracles (weights required)

This directory defines **small, reviewable** correctness fixtures for DS4 once
someone has access to V4 Flash weights on Spark.

This repo must not commit checkpoint shards. The intended workflow is:

1. A human (or approved job) provides a *local* converted checkpoint directory
   containing `model{rank}-mp{mp}.safetensors` plus tokenizer files.
2. Run `scripts/model_contract_generate_deepseek_v4_flash_oracle.py` on Spark.
3. Commit the resulting oracle JSON back into this directory.

Files:

- `prompts.json`: prompt cases for oracle generation (no weights needed).
- `logits_oracle.json`: generated output (not committed until weights are available).

## `logits_oracle.json` contract (format_version=1)

This file is meant to be a **stable, reviewable** correctness signature for DS4
once weights are available on Spark.

Required top-level keys:

- `format_version`: `1`
- `upstream_commit`: must match `../upstream_commit.txt`
- `world_size`: tensor-parallel size used to load `model{rank}-mp{world_size}.safetensors`
- `seed`: generator seed (must be recorded)
- `reference.model_args`: minimal runtime parameters recorded from `ModelArgs`
- `runtime_versions`: `python/torch/transformers/safetensors` versions used
- `tokenizer_sha256`: sha256 hashes for `tokenizer.json` and `tokenizer_config.json` (when present in the checkpoint dir)
- `cases[]`: list of case traces

Each `cases[]` entry must include:

- `id`: case identifier from `prompts.json`
- `thinking_mode`: `chat` or `thinking` (upstream encoding mode)
- `prompt_tokens[]`: encoded prompt token ids
- `trace[]`: per-step decode trace with `argmax_id`, `topk_ids[]`, `topk_logits[]`
