# v2 substrate convergence plan

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

## Why this is parallel, not a wholesale replacement

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

The honest path is parallel adoption: v2/ ships now under a self-contained subdir so it can be exercised, calibrated, and proved out. The existing infrastructure keeps running. Migration happens in measured phases as each v2 contract proves itself against real production load.

## Migration phases (file as issues after this merges)

### Phase 1 — exercise the v2 substrate (Spark-side)

- Stand up `ds4-infer queue-work` on one Spark against the existing profiles in `v2/profiles/`
- Submit a small request batch via `ds4-infer queue-submit` and confirm the lifecycle: submit → work → status → poll → notice
- Verify capability routing: `efficient` → Qwen lanes, `smart` → DSV4 lane, `smartest` → grouped vLLM/MTP lane
- Acceptance: round-trip works end-to-end with the `fake` runner; then with the `vllm` and `antirez` runners against a real Spark
- Owner: xhigh task
- Time budget: 90 min

### Phase 2 — migrate sparkrunner_lazy_adapter to ds4-infer

- Today: `sparkrunner_lazy_adapter.sh` POSTs to `http://127.0.0.1:8000/v1/chat/completions` (the lazy proxy)
- Target: a thin shim that writes the request batch to a JSONL file, calls `ds4-infer queue-submit`, polls until complete, writes responses JSONL in the SparkRunner contract
- Acceptance: a Centaur diamond run produces the same `accepted_count > 0, diamond_score > 0` outcome using the new path
- Owner: xhigh task, blocks on Phase 1
- Time budget: 2-3 hours

### Phase 3 — migrate diamond loop to use the queue directly

- Today: `centaur_diamond_loop.sh::_remote_run_diamond` writes requests for SparkRunner; SparkRunner calls the lazy adapter
- Target: skip SparkRunner entirely; the loop calls `ds4-infer queue-submit` then polls the queue
- Acceptance: 24h unattended run produces ≥1 accepted candidate per day
- Owner: xhigh task, blocks on Phase 2
- Time budget: 4-6 hours

### Phase 4 — retire the lazy proxy

- After Phase 3 has been in production for 7 days with no regressions
- Tag the old scripts as archived, leave them in git history
- Owner: xhigh task, blocks on Phase 3 + 7-day soak
- Time budget: 30 min

### Phase 5 — decide on telemetry / CPU service batches / audit reconciliation

- `ds4-tools` registry is the natural home for the CPU service batches from PR #1406
- Spark telemetry could either live as a separate concern (not Centaur-facing) or become a `ds4-tools` entry
- The audit machinery (`scripts/audit_code_rot.py`, `centaur/centaur_complexity.py`, gates) is INDEPENDENT of the substrate — keep it as-is, it's working
- Owner: design discussion, then file follow-up issues
- Time budget: TBD

## What this PR does NOT touch

Explicit anti-actions:

- Does NOT modify any file outside `v2/`
- Does NOT delete `scripts/`, `tests/`, `fixtures/`, `centaur/`, `docs/` at top level
- Does NOT modify `.complexity-baseline.json`, `.audit-baseline.json`, or the CI workflow
- Does NOT change the lazy proxy
- Does NOT change the diamond loop
- Does NOT change SparkRunner adapter
- Does NOT remove any tests
- Does NOT remove any model-contract fixtures

If a future PR wants to start the purge, that's a separate change with explicit deletion review.

## Verification

```bash
cd v2/
PYTHONPATH=src python3 -m unittest discover -s tests
```

Expected:

```
Ran 35 tests in 1.163s
OK
```

All 35 tests pass locally with no external dependencies.

## Self-correction

The original release proposal asked for a wholesale replacement. I'm not doing that — the replacement would delete 4 PRs of merged production work (#1395, #1400, #1401, #1402-#1406) that landed after the v2 release was authored, including a working live diamond run with 13 accepted candidates. Parallel adoption is the honest path: ship v2 now so it can be evaluated, plan a measured migration as each contract proves itself.

If ct wants the purge anyway, the right next step after this PR merges is a separate "purge legacy substrate" PR that explicitly lists every file being deleted and acknowledges what production capabilities are being retired. That decision should be explicit, not implicit in a 96%-LOC-reduction wholesale swap.
