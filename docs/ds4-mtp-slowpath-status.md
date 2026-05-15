# DS4 MTP Slowpath Status

- accept rate: 19/22 = 0.863636
- baseline t/s: 11.410000
- MTP t/s: 0.830000
- slowest component: target_eval_ms (8722.939 ms across 11 MTP timing events)
- next code change: replace the slow `metal_graph_verify_suffix_tops()` verifier path in `ds4_session_eval_speculative_argmax()` with a cheaper strict target check, or bypass MTP until the verifier is faster than target-only decode
- PR consolidation: #1084 merged as primary MTP branch; #1082 closed; #1067 closed as superseded; #1086 parked for capture-layout work and must be rebased before merge
