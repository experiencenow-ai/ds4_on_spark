# Baseline: llama.cpp Multi-slot (`--parallel 2`) Reservation Failures

This note tracks a Spark0 failure mode seen on DSv4 Flash forks when enabling multi-slot scheduling (for example `llama-server --parallel 2`).

Status note: this document and the companion probe scripts were rescued from
the superseded baseline-runtime PR #27 as standalone artifacts. The baseline
wrapper now supports `LLAMA_SERVER_THROUGHPUT_SWEEP=1` and
`LLAMA_MULTISLOT_PATCH_PROBE=1` and records the fetched artifacts under the
local report directory.

## Symptom

With `--parallel 2`, the runtime may fail during `sched_reserve()` / graph reservation with asserts or shape errors, often involving:

- `ggml_reshape_3d`
- `n_comp_visible <= n_comp_cache`

When this triggers, throughput sweeps are invalid because the server never becomes healthy (or dies immediately after startup).

## Local Fixes Under Test (Spark0)

Two narrow fixes have been observed as necessary on some forks:

1. DS4 SWA cache stream view for `mctx_swa->get_k()`
2. Resumed-graph reserve capped by `n_ctx_seq`

These are external-runtime patches (llama.cpp fork), not changes to `ds4_on_spark`.

Additional fixes have been observed as necessary on some forks but are not yet pinned as patch artifacts in this repo:

3. DeepSeek V4 reserve token count bounded by per-sequence context (avoid reserving more tokens than `n_ctx_seq` can support)
4. Skip impossible resumed-reserve windows instead of asserting (when computed reserve windows cannot fit the current per-sequence context)

Cross-cutting requirement for interpreting `--parallel 2` results:

5. The DSv4 Flash-Attention pad-to-256 reservation fix (see `docs/baseline-fattn-reservation.md`) should be present, otherwise multi-slot sweeps may silently run in a degraded fallback mode after a reservation failure.

### Narrow Patch Artifacts

Patch artifacts (apply to the external runtime tree, not this repo):

- `docs/patches/llama-cpp-dsv4-multislot-swa-stream-view.patch`
  - Slices SWA KV cache views down to a single stream before reshaping, so multi-stream reservation contexts do not trigger `ggml_reshape_3d` shape asserts.
- `docs/patches/llama-cpp-dsv4-multislot-reserve-nctxseq.patch`
  - Caps the DeepSeek V4 “resumed prompt” reservation position by `n_ctx_seq` instead of total `n_ctx`, avoiding `n_comp_visible <= n_comp_cache` asserts during `sched_reserve()`.

## Probe: Throughput Sweep Log Scan (Recommended)

The batching throughput sweep script emits a best-effort probe per combo:

- `multislot_reservation_probe.json`

It scans the server log for the known failure signatures above and records:

- `seen_sched_reserve_fail`
- `seen_reshape_3d`
- `seen_n_comp_visible_le_n_comp_cache`
- `match_lines` (bounded sample)

Run it via the baseline entrypoint:

```sh
ALLOW_RUN=1 \
MODEL_GGUF=/abs/path/on/spark/to/model.gguf \
LLAMA_SERVER=/abs/path/on/spark/to/llama-server \
LLAMA_SERVER_THROUGHPUT_SWEEP=1 \
LLAMA_SERVER_THROUGHPUT_SWEEP_PARALLEL_VALUES="1 2" \
scripts/run_baseline_existing_runtime.sh spark0@aitopatom-9ab9.local
```

## What To Record

For any `--parallel 2` failure, capture:

- exact `LLAMA_SERVER` binary hash/version and/or source revision
- exact `SERVER_ARGS` and sweep knobs (parallel/batch/ubatch/concurrency)
- `llama_server.log` and `multislot_reservation_probe.json`
- whether DSv4 Flash reservation was clean (`fattn_reservation_probe.json` from the same combo dir)

This makes the “parallel-2 stable” requirement measurable and prevents regressions when iterating on DSv4 Flash kernels.

## Cheap Source Probe (Patch Presence)

To confirm the multi-slot reservation fixes are present in an external runtime tree without loading a model, run:

```sh
LLAMA_MULTISLOT_PATCH_PROBE=1 \
LLAMA_DIR=/abs/path/on/spark/to/llama.cpp \
scripts/run_baseline_existing_runtime.sh spark0@aitopatom-9ab9.local
```

This runs a read-only scan (`scripts/benchmark_llamacpp_multislot_patch_probe.py`) on Spark and fetches:

- `multislot_patch_probe.json`

Heuristic booleans:

- `swa_stream_view_found`
- `reserve_cap_n_ctx_seq_found`
- `reserve_bound_tokens_found` (heuristic for fix (3); not tied to a pinned patch artifact)
- `skip_impossible_windows_found` (heuristic for fix (4); not tied to a pinned patch artifact)

The source probe always records bounded match samples under `*_matches` for debugging. For fixes (3) and (4), treat the booleans as a best-effort hint: record the exact runtime repo/commit and preserve the server log + probe JSON so the failure mode is explicit.
