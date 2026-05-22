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
2026-05-22 200G mirror pass, the required usable cache is verified on
spark0-spark7:

- 46 DeepSeek V4 Flash HF safetensor shards per node.
- 7 required GGUF files per node.
- The obsolete spark6 `.part` file was removed after the full canonical DS4
  file passed the byte-size check.
- Spark0, spark1, and spark7 were rechecked at `2026-05-22T0030Z` after the
  Spark7 expansion. Each has the same 1,639 usable files, 1,396,051,607,368
  bytes, under `/home/sparkN/models` when `.incomplete` and `.lock` cache
  artifacts are excluded.
- Spark1 still has old DeepSeek `.incomplete`/`.lock` Hugging Face cache
  fragments from a failed download. They are not part of the usable model shelf
  and should not be propagated.

## Candidate Shelf

`sparkmodels.json` is also the DRY candidate manifest. It includes the latest
scan of the Qwen, DeepSeek, Gemma, Mistral, Phi, Llama, GLM, Tencent Hy-MT, and
Kimi Hugging Face organizations as of 2026-05-21.

Use the candidate tiers this way:

- `next_seed_priority`: pull these first. They are text/code/reasoning/translation
  repos that should run on one Spark and are smaller than the current DeepSeek
  V4 footprint. Pull complete repos, not weight-only subsets.
- `single_spark_mirror_policy`: this is the replication gate for any future
  addition to `next_seed_priority`.
- `small_and_mid_llm`, `ministral3_gguf`, `phi4_current`, and similar tiers are
  catalog pools, not automatic mirror queues.
- `large_fast`: catalog only unless a run explicitly needs the model and we have
  a concrete distributed runtime plan.
- `multimodal_audio`, `vision_ocr_math`, speech, OCR, image/video, embedding,
  and reranker tiers are not part of the default mirror-everywhere model shelf.
- Gated families such as Gemma and Llama stay in the manifest even before
  license acceptance. Accept terms once, seed on a node with internet, then
  mirror over the ring.

Default replication rule:

```text
mirror everywhere only if full repo <= 80 GB and the model is text/code/reasoning
```

This deliberately excludes Kimi K2, Llama 405B, DeepSeek V4 Pro, GLM-5 full, and
other huge or distributed-only repos. Those can stay in the catalog but should
not consume every Spark's disk unless a specific run needs them.

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
spark0 -> spark1 -> spark2 -> spark3 -> spark4 -> spark5 -> spark6 -> spark7
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
for h in spark0 spark1 spark2 spark3 spark4 spark5 spark6 spark7; do ssh "$h" 'hostname; du -sh ~/models/* 2>/dev/null'; done
```

For required GGUF files, compare byte sizes first:

```bash
for h in spark0 spark1 spark2 spark3 spark4 spark5 spark6 spark7; do ssh "$h" 'find ~/models -type f -name "*.gguf" -printf "%s %p\n" | sort -nr | head -20'; done
```

For a newly copied large file, compare SHA-256 across the source and destination
before declaring it ready for use.
