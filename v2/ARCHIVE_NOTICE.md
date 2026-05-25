# Archive notice

The previous `ds4_on_spark` tree is treated as a lab archive. It contained useful empirical evidence, but its scripts, compatibility endpoints, launch experiments, and old lazy proxy surface are not part of the v2 live substrate.

Preserve old work through the main Git history and PRs. Do not recreate a local Git forge for lattice history: merged source changes already map deterministically to atom/lattice changes.

Old material worth porting selectively:

- model qualification measurements;
- vLLM/antirez/llama launch facts that survive calibration;
- CPU-service ideas that fit the new tool lattice;
- tests that prove new service contracts.

Everything else should remain archived.
