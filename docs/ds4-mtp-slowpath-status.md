# DS4 MTP Slowpath Status

- accept rate: 21/21 = 1.000000
- baseline t/s: 11.410000
- MTP t/s: 1.560000
- slowest component: target_eval_ms (2106.974 ms across 11 MTP timing events)
- next code change: make the draft=2 verifier cheaper than target-only decode by eliminating the remaining full target decode/output-head work, or bypass MTP until that verifier path is faster
- fix attempted: made the existing exact decode2 verifier the default for draft=2, leaving `DS4_MTP_BATCH_VERIFY=1` for the older suffix-batch verifier A/B path; this improved 0.83 t/s to 1.56 t/s but remains slower than baseline
- PR consolidation: #1084 merged as primary MTP branch; #1082 closed; #1067 closed as superseded; #1086 parked for capture-layout work and must be rebased before merge
