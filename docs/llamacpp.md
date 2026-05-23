# Llamacpp

> Supersedes: `docs/llamacpp-mtp-one-token-draft-probe-impl.md`, `docs/llamacpp-mtp-sidecar-probe.md`, `docs/llamacpp-mtp-sidecar-load.md`

This is the canonical document for this topic. Update this file instead of adding a new overlapping note.

## Scope

- Consolidates 3 previous document(s) into one non-overlapping reference.
- Preserves stable commands, constraints, and source inventory; removes per-iteration narrative duplication.
- Historical probe/status fragments should live in git history, not as active docs.

## Current Guidance

- `llamacpp-mtp-one-token-draft-probe-impl.md`: llama.cpp Spark/CUDA: one-token DeepSeek V4 MTP draft probe (implementation notes) (206 lines).
- `llamacpp-mtp-sidecar-probe.md`: llama.cpp Spark/CUDA: DeepSeek V4 MTP sidecar probe (130 lines).
- `llamacpp-mtp-sidecar-load.md`: llama.cpp Spark/CUDA: making `deepseek4_mtp_support` usable (plan) (209 lines).

## Command Inventory

- `llamacpp-mtp-one-token-draft-probe-impl.md`: `./build/bin/llama-ds4-mtp-sidecar-probe --path /abs/path/to/DeepSeek-V4-Flash-MTP-*.gguf --json --load-weights`
- `llamacpp-mtp-one-token-draft-probe-impl.md`: `python3 scripts/model_contract_validate_mtp_one_token_draft_probe.py --probe-json /path/to/mtp_one_token_probe.json --json`
- `llamacpp-mtp-one-token-draft-probe-impl.md`: `python3 scripts/model_contract_validate_mtp_one_token_draft_probe.py \`
- `llamacpp-mtp-one-token-draft-probe-impl.md`: `python3 scripts/model_contract_probe_mtp_sidecar.py --path /abs/path/to/DeepSeek-V4-Flash-MTP-*.gguf --json --expect-deepseek-v4-flash > /tmp/mtp_sidecar_probe.json`
- `llamacpp-mtp-one-token-draft-probe-impl.md`: `python3 scripts/model_contract_generate_llamacpp_mtp_sidecar_binder.py --sidecar-probe-json /tmp/mtp_sidecar_probe.json > /tmp/deepseek4_mtp_sidecar.hpp`
- `llamacpp-mtp-sidecar-probe.md`: `git clone https://github.com/kamnxt/llama.cpp-deepseek-v4-flash-cuda-spark.git`
- `llamacpp-mtp-sidecar-probe.md`: `git checkout 94073e2`
- `llamacpp-mtp-sidecar-probe.md`: `git apply /path/to/ds4_on_spark/docs/llamacpp-patches/kamnxt-llamacpp-deepseek-v4-flash-cuda-spark-94073e2-mtp-sidecar-probe.patch`
- `llamacpp-mtp-sidecar-probe.md`: `./build/bin/llama-ds4-mtp-sidecar-probe --path /abs/path/to/DeepSeek-V4-Flash-MTP-*.gguf --json`
- `llamacpp-mtp-sidecar-probe.md`: `./build/bin/llama-ds4-mtp-sidecar-probe --path /abs/path/to/DeepSeek-V4-Flash-MTP-*.gguf --json --payload-sample-bytes 64`
- `llamacpp-mtp-sidecar-probe.md`: `./build/bin/llama-ds4-mtp-sidecar-probe --path /abs/path/to/DeepSeek-V4-Flash-MTP-*.gguf --json --load-weights`
- `llamacpp-mtp-sidecar-probe.md`: `./scripts/fetch_upstreams.sh ds4`
- `llamacpp-mtp-sidecar-probe.md`: `python3 scripts/verify_mtp_sidecar_expected_tensors_vs_ds4.py`
- `llamacpp-mtp-sidecar-probe.md`: `python3 scripts/model_contract_probe_mtp_sidecar.py --url https://huggingface.co/.../DeepSeek-V4-Flash-MTP-*.gguf --json`
- `llamacpp-mtp-sidecar-probe.md`: `python3 scripts/model_contract_probe_mtp_sidecar.py --url https://huggingface.co/.../DeepSeek-V4-Flash-MTP-*.gguf --json --payload-sample-bytes 64`
- `llamacpp-mtp-sidecar-probe.md`: `./scripts/model_contract_probe_mtp_sidecar_antirez.sh`
- `llamacpp-mtp-sidecar-load.md`: `python3 scripts/model_contract_probe_mtp_sidecar.py --path /abs/path/to/DeepSeek-V4-Flash-MTP-*.gguf --json --expect-deepseek-v4-flash > /tmp/mtp_sidecar_probe.json`
- `llamacpp-mtp-sidecar-load.md`: `python3 scripts/model_contract_generate_llamacpp_mtp_sidecar_binder.py --sidecar-probe-json /tmp/mtp_sidecar_probe.json > /tmp/deepseek4_mtp_sidecar.hpp`

## Source Map

| Source | Lines | Main heading | Subsections |
|---|---:|---|---|
| `docs/llamacpp-mtp-one-token-draft-probe-impl.md` | 206 | llama.cpp Spark/CUDA: one-token DeepSeek V4 MTP draft probe (implementation notes) | Preconditions (must pass first), Output contract (what to emit), Recommended binary shape (Spark fork), Patch scaffold in this repo (skeleton; draft compute still TODO), Sidecar binding (avoid guessy dims/types) |
| `docs/llamacpp-mtp-sidecar-probe.md` | 130 | llama.cpp Spark/CUDA: DeepSeek V4 MTP sidecar probe | Patch, Apply + build (Spark), Run, Relationship to the Python contract probe |
| `docs/llamacpp-mtp-sidecar-load.md` | 209 | llama.cpp Spark/CUDA: making `deepseek4_mtp_support` usable (plan) | Why the sidecar cannot be “loaded as a model”, Observed upstream state (kamnxt fork @ `9222e55`), Key implementation reuse (kamnxt fork @ `9222e55`), Minimum plan to reach the one-token draft probe, DS4 draft step reference (antirez/ds4) |
