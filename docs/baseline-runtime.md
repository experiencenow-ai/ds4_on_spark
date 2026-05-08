# Baseline Runtime

Goal: define **reproducible** baseline runs for:

- `antirez/ds4` (Mac / Metal reference)
- `llama.cpp` on Spark (CUDA baseline)
- vLLM on Spark (reference)
- later: `ds4_on_spark` (native DS4 Flash measurements)

This baseline track is designed to capture **exact command lines**, **model artifact requirements**, and the key metrics:

- TTFT (time to first token)
- tokens/sec (prefill + generation where possible)
- memory usage (CPU RSS + GPU memory snapshot)
- failure modes (exact stderr / return codes)

## Safety Gates (non-negotiable)

- Scripts **do not download model weights**.
- Scripts **do not build** upstream runtimes unless explicitly enabled.
- Scripts **do not run** inference unless explicitly enabled.

Enable gates with environment variables:

- `ALLOW_FETCH=1` to `git clone` upstream repos (small; still explicit)
- `ALLOW_BUILD=1` to compile (can take minutes)
- `ALLOW_RUN=1` to run inference (can be long / expensive)

## One-command entrypoint (Mac → Spark)

Run from the Mac:

```sh
scripts/run_baseline_existing_runtime.sh spark0@aitopatom-9ab9.local
```

This writes a markdown report to a local output directory and includes:

- Spark identity + `nvidia-smi` snapshot
- llama.cpp baseline (optional build/run depending on gates)
- vLLM presence/version probe (no installs)

## Required Fixtures

See `docs/baseline-fixtures.md` for artifact handling and the fixture manifest template.

## Baseline Report Format

Use `docs/baseline-template.md` as the canonical structure for reports committed to this repo.

