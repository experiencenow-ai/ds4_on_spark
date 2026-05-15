# DS4 MTP Slowpath Status

- accept rate: 19/22 = 0.863636
- baseline t/s: 11.410000
- MTP t/s: 0.830000
- slowest component: target_eval_ms (8722.939 ms across 11 MTP timing events)
- next code change: replace the slow `metal_graph_verify_suffix_tops()` verifier path in `ds4_session_eval_speculative_argmax()` with a cheaper strict target check, or bypass MTP until the verifier is faster than target-only decode
