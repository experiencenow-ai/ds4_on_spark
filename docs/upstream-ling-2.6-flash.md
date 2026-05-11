# Upstream: Ling 2.6 Flash (comparison targets)

This note tracks Ling 2.6 Flash checkpoints as Spark-sized comparison targets.
It is metadata-only: no model weights were downloaded while preparing this
document.

- Pinned-at: 2026-05-11 (UTC)
- Safety policy: use `GIT_LFS_SKIP_SMUDGE=1`, Hugging Face API metadata, or local
  Spark paths first; large weight fetches require explicit human approval.

## Targets (HF, pinned)

| Priority | Target | Ref | Commit / SHA | License | Safetensors | Single Spark? | Notes |
| --- | --- | --- | --- | --- | --- | --- | --- |
| 1 | `inclusionAI/Ling-2.6-flash-int4` | `refs/heads/main` | `1bff63aa1f869e89499d52363790a119fd282edf` | `mit` | 60.38 GiB | likely | Smallest pinned Ling 2.6 Flash target; treat as a candidate single-Spark comparator if runtime support is available. |
| 2 | `inclusionAI/Ling-2.6-flash-fp8` | `refs/heads/main` | `8bc416b60fe28be33303d57bb77dd826445a1eb1` | `mit` | 101.48 GiB | maybe (tight) | Weight footprint is close to the Spark0 unified-memory envelope; leaves limited headroom for runtime + KV/cache. |
| 3 | `inclusionAI/Ling-2.6-flash` | `refs/heads/main` | `9c861253ede654353d20bf1708182c81aab5f069` | `mit` | 200.23 GiB | no | Reference-only (not single-Spark plausible). |

## Community GGUF (Spark provenance, pinned)

Spark0 already has a community Ling GGUF staged at:

- `/home/spark0/models/ling/Ling-2.6-flash-IQ4_NL-bailing_hybrid-20260505-LJ.gguf`

Pin the upstream here so the staged artifact has a reproducible public source
(metadata-only; no GGUF was downloaded while preparing this doc).

| Priority | Upstream | Ref | Commit / SHA | License | Smallest GGUF (metadata) | Size | Single Spark? | Notes |
| --- | --- | --- | --- | --- | --- | --- | --- | --- |
| 1 | `ljupco/Ling-2.6-flash-GGUF` | `refs/heads/main` | `5bdbd5ca603bd48488ccca06ec17e0e1312764f3` | `apache-2.0` | `Ling-2.6-flash-IQ4_NL-bailing_hybrid-20260505-LJ.gguf` | 56.96 GiB | likely | GGUF header reports `general.architecture=bailing_hybrid`; the current pinned V4-capable llama.cpp forks do **not** recognize this architecture (see `docs/baseline-ling-gguf-bailing-hybrid-spark0-2026-05-11.md`). |

## DFlash status

As of 2026-05-11, no matching Ling 2.6 Flash DFlash draft checkpoints are
pinned in this repo. Keep Ling as **target-only** until an exact target/draft
pair exists.

## Public quality prior (model card, metadata-only)

The pinned Ling model cards (INT4 + FP8) describe strong agent-benchmark performance but do not publish a single “official” scalar score in plain text (most results appear as figures). Treat these as a **prior** only, and record the exact model-card revision when comparing against local Spark runs.

From the `inclusionAI/Ling-2.6-flash-int4` model card (`1bff63aa1f869e89499d52363790a119fd282edf`, `last_modified=2026-04-28T13:08:03Z`):

- Benchmarks explicitly named: `BFCL-V4`, `TAU2-bench`, `SWE-bench Verified`, `Claw-Eval`, `PinchBench`.
- Source/compat notes included in the model card:
  - `PinchBench`: comparative scores taken from the **official PinchBench leaderboard** (as of **2026-04-20**).
  - `Claw-Eval`: comparative scores taken from the **official Claw-Eval leaderboard** (version dated **2026-03-25**).
  - `TAU2-bench`: run using official `v1.0.0` code/datasets with prompt adjustments; uses a user-agent model (model card notes).
  - `IFBench`: some baseline scores sourced from the **Artificial Analysis** leaderboard; others are internal evaluation.

Sources (pinned revisions):

- `https://huggingface.co/inclusionAI/Ling-2.6-flash-int4/blob/1bff63aa1f869e89499d52363790a119fd282edf/README.md`
- `https://huggingface.co/inclusionAI/Ling-2.6-flash-fp8/blob/8bc416b60fe28be33303d57bb77dd826445a1eb1/README.md`

## Metadata commands (no downloads)

```sh
./scripts/upstream_hf_api_report.sh inclusionAI/Ling-2.6-flash-int4
./scripts/upstream_hf_api_report.sh inclusionAI/Ling-2.6-flash-int4 --sum-safetensors
./scripts/upstream_hf_api_report.sh inclusionAI/Ling-2.6-flash-fp8 --sum-safetensors
./scripts/upstream_hf_api_report.sh inclusionAI/Ling-2.6-flash --sum-safetensors
./scripts/upstream_hf_api_report.sh ljupco/Ling-2.6-flash-GGUF
./scripts/upstream_hf_smallest_gguf.sh ljupco/Ling-2.6-flash-GGUF --group-shards --limit 20
```
