# Baseline Fixtures

This repo does not vendor model weights. Baseline scripts intentionally avoid downloading large artifacts.

## Fixture Policy

- **No automatic downloads**: scripts refuse to fetch GGUF/HF weights unless you explicitly run the upstream tooling yourself.
- **Record everything**: for every baseline, record *paths*, *file sizes*, and *hashes* (sha256) of the model artifacts used.
- **Prefer small smoke fixtures first**: validate toolchains and CUDA paths with a small GGUF before attempting DS4-class weights.

## Fixture Inventory (by baseline)

### A) `antirez/ds4` (Mac / Metal reference)

Required upstream artifacts (see upstream `download_model.sh`):

- DS4 Flash GGUF q2 or q4 (large)
- Optional MTP draft GGUF (large)

Local placement guidance:

- Keep all DS4 GGUF artifacts under one directory (example: `~/models/ds4/gguf/`).
- Record:
  - exact upstream commit hash of `antirez/ds4`
  - exact command used to download (if any)
  - sha256 + size of each GGUF

### B) `llama.cpp` (Spark / CUDA baseline)

Required local artifact:

- A local GGUF that `llama-cli` can load (start with a small smoke GGUF, then move to larger fixtures).

Record:

- sha256 + size of GGUF
- any runtime flags that affect memory/perf: context, batch, `-ngl`, `--flash-attn`, etc.

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

