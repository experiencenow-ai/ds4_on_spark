# Spark Model Cache

Load `sparkmodels.json` before choosing model paths. The goal is simple: every
Spark should have the same runtime model cache in the same place, so no thread
blocks because it landed on a node missing a model.

## Canonical Root

Use:

```text
/home/sparkN/models
```

where `sparkN` is the login user for that node. Examples:

```text
/home/spark0/models/ds4/DeepSeek-V4-Flash-IQ2XXS-w2Q2K-AProjQ8-SExpQ8-OutQ8-chat-v2.gguf
/home/spark3/models/hf/deepseek-ai/DeepSeek-V4-Flash/
/home/spark6/models/qwen36_mtp_q4/Qwen3.6-27B-MTP-Q4_K_M.gguf
```

Do not use `~/src/llama.cpp*/models` as a runtime cache. Those directories hold
build fixtures and vocab test files, not the canonical cluster model store.

## Required Layout

```text
models/
  hf/deepseek-ai/DeepSeek-V4-Flash/          # 46 safetensor shards
  hf/<org>/<repo>/                           # future HF-format candidate cache
  gguf/<org>/<repo>/                         # future downloaded GGUF repos
  ds4/*.gguf
  ling/*.gguf
  qwen36_mtp/*.gguf
  qwen36_mtp_q4/*.gguf
  smoke/*.gguf
```

Spark0 was the initial superset source on the 2026-05-20 inventory. After the
200G hop-by-hop mirror pass, the required cache is verified on spark0-spark6:

- 46 DeepSeek V4 Flash HF safetensor shards per node.
- 7 required GGUF files per node.
- The obsolete spark6 `.part` file was removed after the full canonical DS4
  file passed the byte-size check.

## Candidate Shelf

`sparkmodels.json` is also the DRY candidate manifest. It includes the latest
scan of the Qwen, DeepSeek, Gemma, Mistral, Phi, Llama, GLM, and Kimi Hugging
Face organizations as of 2026-05-20.

Use the candidate tiers this way:

- `next_seed_priority`: pull these first. They are small, fast, GGUF, FP8, or
  useful support models such as embedding and reranker models.
- `small_and_mid_llm`, `ministral3_gguf`, `phi4_current`, and similar tiers:
  good default local shelf for experiments.
- `large_fast`: pull FP8, GPTQ-Int4, NVFP4, or GGUF variants before full
  BF16/FP16 unless a run specifically needs unquantized weights.
- `multimodal_audio`, `vision_ocr_math`, and similar tiers: cache when the
  workload needs that modality, but do not block text-only inference.
- Gated families such as Gemma and Llama stay in the manifest even before
  license acceptance. Accept terms once, seed on a node with internet, then
  mirror over the ring.

Future HF-format repos go under:

```text
/home/sparkN/models/hf/<org>/<repo>/
```

Future GGUF repos go under:

```text
/home/sparkN/models/gguf/<org>/<repo>/
```

The source scan URLs are recorded in `sparkmodels.json` under
`candidate_sources`; use those before adding or removing candidate IDs.

## Copy Rule

Use the 200G neighbor ring and copy hop-by-hop:

```text
spark0 -> spark1 -> spark2 -> spark3 -> spark4 -> spark5 -> spark6
```

For regular model files:

```bash
scripts/spark_ring_fast_copy.py --engine native --parallel 32 --chunk-mib 512 spark0:/home/spark0/models/ling/Ling-2.6-flash-IQ4_NL-bailing_hybrid-20260505-LJ.gguf spark1:/home/spark1/models/ling/
```

Then continue from the newly seeded neighbor:

```bash
scripts/spark_ring_fast_copy.py --engine native --parallel 32 --chunk-mib 512 spark1:/home/spark1/models/ling/Ling-2.6-flash-IQ4_NL-bailing_hybrid-20260505-LJ.gguf spark2:/home/spark2/models/ling/
```

For a whole directory tree, use the Python engine:

```bash
scripts/spark_ring_fast_copy.py --engine python --parallel 16 --chunk-mib 512 spark0:/home/spark0/models/smoke spark1:/home/spark1/models/
```

## Verification

Quick placement check:

```bash
for h in spark0 spark1 spark2 spark3 spark4 spark5 spark6; do ssh "$h" 'hostname; du -sh ~/models/* 2>/dev/null'; done
```

For required GGUF files, compare byte sizes first:

```bash
for h in spark0 spark1 spark2 spark3 spark4 spark5 spark6; do ssh "$h" 'find ~/models -type f -name "*.gguf" -printf "%s %p\n" | sort -nr | head -20'; done
```

For a newly copied large file, compare SHA-256 across the source and destination
before declaring it ready for use.
