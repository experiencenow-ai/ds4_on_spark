# Baseline Fixtures

This repo does not vendor model weights. Baseline scripts intentionally avoid downloading large artifacts.

## Fixture Policy

- **No automatic downloads**: scripts refuse to fetch GGUF/HF weights unless you explicitly run the upstream tooling yourself.
- **Record everything**: for every baseline, record *paths*, *file sizes*, and *hashes* (sha256) of the model artifacts used.
- **Prefer small smoke fixtures first**: validate toolchains and CUDA paths with a small GGUF before attempting DS4-class weights.

## Fixture Inventory (by baseline)

### A) `antirez/ds4` (Mac / Metal and Spark / CUDA reference)

Required upstream artifacts (see upstream `download_model.sh`):

- DS4 Flash GGUF q2 or q4 (large)
- Optional MTP draft GGUF (large)

Notes:

- Upstream defaults to `./ds4flash.gguf` in the ds4 repo directory.
- For Spark comparisons, stage the same fixture on the remote Spark host and
  point `scripts/run_baseline_antirez_ds4_spark.sh` at it with `MODEL_GGUF`.
- The ds4 upstream download script pulls from Hugging Face and may require an auth token; this repo's baseline scripts intentionally do **not** run it automatically.

Local placement guidance:

- Keep all DS4 GGUF artifacts under one directory (example: `~/models/ds4/gguf/`).
- Record:
  - exact upstream commit hash of `antirez/ds4`
  - exact command used to download (if any)
  - sha256 + size of each GGUF
  - backend (`Metal` or `CUDA/Spark`), prompt, context, token count, and thinking mode

### B) `llama.cpp` (Spark / CUDA baseline)

Required local artifact:

- A local GGUF that `llama-cli` can load (start with a small smoke GGUF, then move to larger fixtures).
- For the quantized single-Spark V4 Flash milestone, use the smallest credible
  V4 Flash GGUF first and require a runtime that explicitly supports the
  DeepSeek V4 architecture and its GGUF quant types.

Record:

- runtime repo + commit, especially when using a fork or early-access runtime
- declared base model and quant type
- sha256 + size of GGUF
- any runtime flags that affect memory/perf: context, batch, `-ngl`, `--flash-attn`, etc.

Single-Spark ordering:

1. tiny non-DS4 GGUF to prove the runtime binary can execute on Spark
2. lowest-size V4 Flash quantized GGUF for first token generation
3. higher-quality quant only after memory headroom is measured
4. native FP4/FP8 GGUF for loader compatibility, not as the first success target

### C) vLLM (Spark / Python baseline, reference)

Required local artifacts (large, future):

- Local HF model directory (or equivalent weight artifact) already present on Spark
- Tokenizer/config files used by vLLM

Record:

- exact vLLM version (`python3 -m pip show vllm`)
- exact launch command
- tensor parallel settings

## Fixture Manifest Template

Copy/paste this into a baseline report:

```text
Fixture:
  type: gguf|hf_dir|other
  path: /abs/path
  sha256: <sha256>
  size_bytes: <bytes>
  notes: <quant, source, etc>
```
