# One-Token MTP Draft Probe (llama.cpp Spark/CUDA)

Goal: once the Spark CUDA llama.cpp fork can **load** an `antirez/deepseek-v4-gguf` MTP sidecar (`general.architecture=deepseek4_mtp_support`), run a minimal **one-verify-step** probe that proves the draft path is wired correctly before we attempt acceptance metrics or performance tuning.

This is intentionally narrow:

- **1 prompt**
- **1 verify step**
- **`gamma=1` draft token** (one-token draft)
- deterministic settings (`temperature=0.0`, fixed seed)

## Inputs

- Trunk GGUF (DeepSeek V4 Flash): the main model artifact already used by the baseline runtime loop.
- MTP sidecar GGUF (DS4-tuned 32‑tensor table): e.g. `DeepSeek-V4-Flash-MTP-Q4K-Q8_0-F32.gguf`.
  - Use `scripts/model_contract_probe_mtp_sidecar.py` first; it must return `ok=true`.

## Required probe output

Emit a single JSON object (stdout or file) containing at least:

- `runtime_repo`, `runtime_commit`
- `trunk_gguf_path`, `mtp_sidecar_path`
- `prompt` (or `prompt_sha256` + a stable prompt ID if privacy is needed)
- `seed`, `temperature`, `top_k`, `top_p`
- `verify_step_idx` (always `0` for this probe)
- `base_next_token_id` and decoded token string (tokenizer-dependent)
- `mtp_draft_token_id` and decoded token string
- `mtp_params` derived from the sidecar tensor table:
  - `n_embd=4096`, `n_head=64`, `n_head_dim=512`, `n_hc=4`, `n_lora_q=1024`, `n_out_group=8`, `n_lora_o=1024`, `n_expert=256`, `n_ff_exp=2048`
- `ok` boolean + `errors[]` on failure

Keep this probe *fast*: it should stop after the first verify step and draft computation.

## Semantics (reference)

For DeepSeek V4, the MTP module uses separate `e_proj` / `h_proj` projections and applies the `hc_head_*` head in `compute_logits` for draft token selection. Reference: vLLM API docs `vllm.model_executor.models.deepseek_v4_mtp` (DeepSeek V4 MTP draft model).

## Acceptance gate (not in this probe)

Do **not** claim speedups or acceptance rates until:

1. The one-token draft probe runs deterministically and emits the required JSON.
2. A multi-prompt correctness sweep exists that compares MTP draft/verify behavior against an oracle (or a trusted implementation) under fixed decoding.

This probe is only a wiring check, not a correctness proof.
