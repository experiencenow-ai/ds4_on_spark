# v2 substrate convergence record

Status: completed on 2026-05-25. The legacy top-level v1 substrate is purged
from live main, and `v2/` is the active DS4 service surface.

## What this directory is

`v2/` is a from-scratch, self-contained service substrate proposed as a clean replacement for the accreted top-level scripts/tests/fixtures. It is `version = "0.3.0"` of the `ds4-on-spark` package and ships:

| Contract | Owns |
|---|---|
| `ds4-infer` | inference queue with capability routing, static Spark topology, profile registry |
| `ds4-tools` | lattice-addressed tool registry with stable IDs and schema validation |
| `ds4-agent` | bounded model+tool loop |
| `ds4-calibrate` | profile calibration plans |
| `ds4-transfer` | direct Spark-to-Spark 200G transfers (no controller hairpin) |
| `ds4-spark-chat` | resident vLLM/MTP CLI with optional spark7 tool access |

2,929 LOC, 35 tests, zero external dependencies, pure stdlib.

## Why this stopped being parallel

The original proposal was framed as a full replacement of the existing tree. That can't be done cleanly today because the existing tree contains live, working systems that landed AFTER the v2 release was authored:

| Live system | Lives in | Depends on |
|---|---|---|
| Lazy vLLM proxy + 27-model inventory | `scripts/ds4_vllm_lazy_proxy.{py,sh}` | (PR #1395) |
| SparkRunner lazy adapter | `scripts/sparkrunner_lazy_adapter.sh` | lazy proxy (PR #1400, first live Spark7 run produced 13 accepted candidates) |
| Centaur diamond loop | `scripts/centaur_diamond_loop.sh` + `centaur_diamond_helpers.py` | sparkrunner adapter + lazy proxy (PR #1401) |
| Centaur target discovery | `scripts/audit_code_rot.py` + `scripts/score_repo_complexity.py` + `centaur/centaur_complexity.py` | the audit gate + `.complexity-baseline.json` |
| CPU service batches | DS4 model gateway | (PR #1406) |
| Spark telemetry monitor | `scripts/spark_telemetry_*.{py,sh}` + systemd | (PRs #1403-1405) |
| Test infrastructure | 113 tests, ~15,700 LOC | the audit machinery, model-contract fixtures |
| Audit baseline machinery | `.complexity-baseline.json` + `.audit-baseline.json` + `.github/workflows/code_rot_audit.yml` | scripts/ + centaur/ |

A wholesale purge would delete the lazy proxy that just produced 13 accepted candidates with diamond_score=167.5. It would delete the audit baseline that PR #1401's gate fix just refreshed. It would delete 456 fixture files referenced by model-contract verification. It would delete the diamond loop one day after it merged.

Those Centaur-owned pieces have now moved to the Centaur repository, and the
remaining ds4-owned live surfaces have v2 replacements. The repository can
therefore take the explicit purge path.

## Migration phases

### Phase 1 — exercise the v2 substrate (Spark-side)

- Stand up `ds4-infer queue-work` on one Spark against the existing profiles in `v2/profiles/`
- Submit a small request batch via `ds4-infer queue-submit` and confirm the lifecycle: submit → work → status → poll → notice
- Verify capability routing: `efficient` → Qwen lanes, `smart` → DSV4 lane, `smartest` → grouped vLLM/MTP lane
- Acceptance: round-trip works end-to-end with the `fake` runner; then with the `vllm` and `antirez` runners against a real Spark
- Status: completed by `ds4-infer` queue lifecycle tests plus Spark-side smoke.

### Phase 2 — migrate sparkrunner_lazy_adapter to ds4-infer

- Status: completed by `ds4-sparkrunner-queue` and
  `v2/scripts/sparkrunner_queue_adapter.sh`.

### Phase 3 — migrate diamond loop to use the queue directly

- Status: completed as a ds4 interface: the queue adapter can emit raw
  `ds4-inference-result-v1` JSONL with `--response-format inference`, so
  Centaur can bypass the SparkRunner contract entirely.

### Phase 4 — retire the lazy proxy

- Status: completed by deleting the lazy proxy from live files. Git history is
  the archive.

### Phase 5 — decide on telemetry / CPU service batches / audit reconciliation

- Status: completed in `docs/legacy-reconciliation.md`.

## Purge boundary

The live ds4 repository keeps `v2/` plus minimal root metadata. Deleted v1 files
remain available from Git history. Centaur-owned archive, audit, and
diamond-making code moved to the Centaur repository before this purge.

## Verification

```bash
cd v2/
PYTHONPATH=src python3 -m unittest discover -s tests
```

The tests run locally with no external dependencies.
