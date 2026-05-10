# Upstream: Ling 2.6 Flash (comparison targets)

This note tracks Ling 2.6 Flash checkpoints as Spark-sized comparison targets.
It is metadata-only: no model weights were downloaded while preparing this
document.

- Pinned-at: 2026-05-10 (UTC)
- Safety policy: use `GIT_LFS_SKIP_SMUDGE=1`, Hugging Face API metadata, or local
  Spark paths first; large weight fetches require explicit human approval.

## Targets (HF, pinned)

| Priority | Target | Ref | Commit / SHA | License | Safetensors | Single Spark? | Notes |
| --- | --- | --- | --- | --- | --- | --- | --- |
| 1 | `inclusionAI/Ling-2.6-flash-int4` | `refs/heads/main` | `1bff63aa1f869e89499d52363790a119fd282edf` | `mit` | 60.38 GiB | likely | Smallest pinned Ling 2.6 Flash target; treat as a candidate single-Spark comparator if runtime support is available. |
| 2 | `inclusionAI/Ling-2.6-flash-fp8` | `refs/heads/main` | `8bc416b60fe28be33303d57bb77dd826445a1eb1` | `mit` | 101.48 GiB | maybe (tight) | Weight footprint is close to the Spark0 unified-memory envelope; leaves limited headroom for runtime + KV/cache. |
| 3 | `inclusionAI/Ling-2.6-flash` | `refs/heads/main` | `9c861253ede654353d20bf1708182c81aab5f069` | `mit` | 200.23 GiB | no | Reference-only (not single-Spark plausible). |

## DFlash status

As of 2026-05-10, no matching Ling 2.6 Flash DFlash draft checkpoints are
pinned in this repo. Keep Ling as **target-only** until an exact target/draft
pair exists.

## Metadata commands (no downloads)

```sh
./scripts/upstream_hf_api_report.sh inclusionAI/Ling-2.6-flash-int4
./scripts/upstream_hf_api_report.sh inclusionAI/Ling-2.6-flash-int4 --sum-safetensors
./scripts/upstream_hf_api_report.sh inclusionAI/Ling-2.6-flash-fp8 --sum-safetensors
./scripts/upstream_hf_api_report.sh inclusionAI/Ling-2.6-flash --sum-safetensors
```

