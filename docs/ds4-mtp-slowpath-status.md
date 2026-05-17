# DS4 MTP Slowpath Status

## K=2 direct verifier status

- PR #1125 changed K=2 materially: the original controlled run used baseline greedy 11.02 t/s and MTP draft=2 20.55 t/s, a 1.865x speedup, with 84/84 accepted draft tokens and 0 target-next mismatches.
- 2026-05-17 matched-rebuild baseline check: greedy baseline is 13.40 t/s on the same rebuilt binary and exact K=2 is 20.54 t/s, so the matched-source speedup is 1.53x; the prior 1.86x number used the earlier 11.02 t/s denominator.
- 2026-05-17 lazy host-logits follow-up: greedy baseline is 13.75 t/s and exact K=2 measured-mode MTP is 20.34 t/s for `N_PREDICT=126`; the diagnostic timing run reports 84/84 accepted draft tokens and `target_next_mismatch_events=0`.
- 2026-05-17 short-tail follow-up: same-shape `N_PREDICT=32` baseline is 14.09 t/s, pre-tail K=2 was 16.40 t/s, and the two-token tail-capable K=2 patch measured 17.88 t/s (`1.269x` vs baseline, about `+9.0%` vs pre-tail). The timing probe at `N_PREDICT=29` proves the new `suffix2_tail` branch and accounting (`target_positions=2`, `head_calls=1`, `cache_sync_calls=0`, `target_next_mismatch_events=0`); that prompt rejected the one tail draft, so the throughput evidence remains the measured-mode `N_PREDICT=32` run.
- 2026-05-17 partial-continuation experiment: carrying verifier top1 as the next partial-accept token reduced the `N_PREDICT=29` partial-pattern output-head count from 14 to 11 in the diagnostic shape, but throughput stayed 10.96 t/s because target eval remained dominant and top1 continuation has the same near-tie exactness risk as row2 top1 continuation. The guarded knob is `DS4_MTP_PARTIAL_TOP1_CONT=1`; exact default still materializes continuation logits on partial accepts. The next real speed change should fuse exact row1/row2 continuation logits into one verifier head or prove top1/full-logits equivalence first.
- Timing decisions now require a `ds4-mtp-timing-samples-v1` report with at least 10 valid same-command samples; single-run t/s numbers are exploratory only. Use `scripts/build_ds4_mtp_timing_samples.py` and `scripts/validate_ds4_mtp_timing_samples.py` before treating a K=2 change as direction-setting.
- 2026-05-17 10-sample K=2 timing run: baseline median 12.02 t/s (mean 12.161, stdev 1.195, CV 0.098), MTP median 20.23 t/s (mean 16.871, stdev 4.532, CV 0.269), median speedup 1.683x. The sample reports pass, but the timing decision is `unstable` because MTP is bimodal (`20.24,20.22,20.30,10.79,14.26,11.17,10.70,20.29,20.34,20.40`). Artifact root: `/private/tmp/ds4_mtp_10_sample_spark/20260517T054900Z-mtp-k2-timing-samples`. Next code change: add a measured-mode low-overhead slow-mode discriminator for K=2 runs so the 10.7-14.3 t/s mode can be attributed to verifier path, cache residency, runtime scheduling, or external load.
- 2026-05-17 low-mode discriminator follow-up: `DS4_MTP_SAMPLE_DIAG=1` now emits aggregate K=2 verifier-path counters in measured mode, and `ds4-mtp-timing-samples-v1` derives accepted/attempted draft counts from that record when verbose conf logs are disabled. Spark artifact root: `/private/tmp/ds4_mtp_lowmode_diag_10_sample_spark/20260517T065955Z-mtp-k2-timing-samples`. Baseline median 13.605 t/s (CV 0.0567); MTP median 20.185 t/s (CV 0.2463), median speedup 1.484x, still `unstable`. Fast samples were perfect-accept (`84/84`, 42 output-head calls, 126 target positions, ~20.1-20.6 t/s). Slow samples were not serial fallback: they had `serial_steps=0` and `suffix2_fallbacks=0`, but low derived acceptance (`70/112`, `69/114`, `70/112`) with 87-90 output-head calls and 168-171 target positions, yielding ~11.0-11.5 t/s. Next code change: use the first-nonfull diagnostic (`suffix2_first_nonfull_*`) to identify whether the target argmax sequence changes or the MTP draft/raw-cache state drifts, then fix that nondeterministic low-accept mode.
- The K=2 direct verifier is now a real speed path for the measured group-boundary case (`n_predict=126`, `n_predict % 3 == 0`).
- Production eligibility is still false until the controlled matrix covers `n_predict={32,64,126,127,128}`, at least short/code/long prompt shapes, and both stdout-style and `DS4_SUPPRESS_OUTPUT=1` runs.
- Tail cases `n_predict % 3 == 1` and `n_predict % 3 == 2` must produce explicit `ds4-mtp-k2-production-benchmark-v1` artifacts with `tail_acceptance_status=passed`; they must not be inferred from the group-boundary run.
- The row2 continuation must remain exact full-logits/indexer-derived by default. A measured `DS4_MTP_ROW2_TOP1_CONT=1` experiment removed the full-vocab continuation row but dropped acceptance to 70/112 and MTP throughput to 11.59 t/s, so it stays opt-in until the top1 primitive is proven to match the full-logits argmax.
- The K=2 continuation path now keeps the GPU-selected row2 continuation token as `pending_argmax` and makes host logits readback lazy: trace/debug reads row2 logits, measured argmax continuation does not. The unsafe `DS4_MTP_ROW2_SKIP_LOGITS_READBACK` escape hatch remains absent from the patch contract.
- `DS4_SUPPRESS_OUTPUT=1` measured 20.48 t/s with 84/84 acceptance, so token printing is not the current K=2 limiter.
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
