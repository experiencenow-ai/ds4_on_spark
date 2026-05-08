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

