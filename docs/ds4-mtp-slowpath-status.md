# DS4 MTP Slowpath Status

## K=2 direct verifier status

- PR #1125 changes K=2 materially: matched-runtime baseline greedy is 11.02 t/s and MTP draft=2 is 20.55 t/s, a 1.865x speedup, with 84/84 accepted draft tokens and 0 target-next mismatches.
- The K=2 direct verifier is now a real speed path for the measured group-boundary case (`n_predict=126`, `n_predict % 3 == 0`).
- Production eligibility is still false until the controlled matrix covers `n_predict={32,64,126,127,128}`, at least short/code/long prompt shapes, and both stdout-style and `DS4_SUPPRESS_OUTPUT=1` runs.
- Tail cases `n_predict % 3 == 1` and `n_predict % 3 == 2` must produce explicit `ds4-mtp-k2-production-benchmark-v1` artifacts with `tail_acceptance_status=passed`; they must not be inferred from the group-boundary run.
- The row2 continuation must remain exact full-logits/indexer-derived by default. A measured `DS4_MTP_ROW2_TOP1_CONT=1` experiment removed the full-vocab continuation row but dropped acceptance to 70/112 and MTP throughput to 11.59 t/s, so it stays opt-in until the top1 primitive is proven to match the full-logits argmax.
- The next K=2 optimization keeps that exact GPU full-logits/indexer continuation and reads the already-materialized row2 logits instead of rematerializing them. A no-readback experiment changed acceptance, so `DS4_MTP_ROW2_SKIP_LOGITS_READBACK=1` is unsafe and diagnostic-only.
- Current production artifact validator: `scripts/validate_ds4_mtp_k2_production_benchmark.py`.
- Current PR #1125 evidence fixture: `fixtures/mtp_k2_production/pr1125_n126_short_instruction_stdout.example.json`.

## K=3 prefix-frontier status

- K=3 now has a prefix-3 verifier frontier so row0+row1 matches can commit `[target_token,draft0,draft1]` without serial target replay.
- Controlled result: baseline greedy 11.01 t/s, MTP draft=3 11.19 t/s, speedup 1.016x, acceptance 75/153, target-next mismatches 0.
- K=3 is a proof-of-life speed path, not the selected path: K=2 remains better on this prompt at 20.55 t/s.

Production-eligible K=2 requires:

- `target_next_mismatch_events == 0`;
- `tail_acceptance_status == passed`;
- no accepted/attempted accounting regression;
- `benchmark_matrix_status == passed`;
- `production_eligible == true` only when all of the above gates pass.

## Prior slow verifier status

- accept rate: 21/21 = 1.000000
- baseline t/s: 14.650000
- MTP t/s: 2.000000
- speedup vs baseline: 0.136519x
- slowest component: target_eval_ms (1453.660 ms, 21 target eval calls, 21 output-head calls, 0 cache syncs, 0 CUDA syncs)
- next code change: redesign the exact verifier so accepted draft positions do not each pay target_eval/output_head work; keep MTP paused until that verifier cost is cheaper than target-only decode
- fix attempted: instrumented target-eval/output-head/cache-sync call counts and skipped the unused first-row logits read on the decode2 full-accept path; draft=2 improved from 1.56 t/s to 2.00 t/s but remains far below baseline
- PR consolidation: #1084 and #1094 merged into main; #1082, #1067, and #1089 closed as superseded; #1086 remains parked for capture-layout work with no speed-path dependency
