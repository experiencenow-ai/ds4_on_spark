# DS4 MTP Slowpath Status

- accept rate: 21/21 = 1.000000
- baseline t/s: 14.650000
- MTP t/s: 2.000000
- speedup vs baseline: 0.136519x
- slowest component: target_eval_ms (1453.660 ms, 21 target eval calls, 21 output-head calls, 0 cache syncs, 0 CUDA syncs)
- next code change: redesign the exact verifier so accepted draft positions do not each pay target_eval/output_head work; keep MTP paused until that verifier cost is cheaper than target-only decode
- fix attempted: instrumented target-eval/output-head/cache-sync call counts and skipped the unused first-row logits read on the decode2 full-accept path; draft=2 improved from 1.56 t/s to 2.00 t/s but remains far below baseline
- PR consolidation: #1084 and #1094 merged into main; #1082, #1067, and #1089 closed as superseded; #1086 remains parked for capture-layout work with no speed-path dependency
