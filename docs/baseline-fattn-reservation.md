# Baseline: DS4 Flash-Attention Reservation Probe

This note codifies a narrow probe for a **llama.cpp DeepSeek V4 Flash** failure mode where CUDA Flash Attention is **globally disabled** after a graph-reservation fallback on `__fattn__` nodes.

## Symptom

During graph reservation (often at `llama-server` startup) the runtime may log:

- `sched_reserve: layer ... is assigned to device CUDA0 but the Flash Attention tensor is assigned to device CPU ...`
- `sched_reserve: Flash Attention was auto, set to disabled`

Once this happens, later requests may run with a worse CUDA fallback mix.

## Root Cause (as observed on Spark0)

For DeepSeek V4 Flash `head_dim=512`, `ggml_cuda_get_best_fattn_kernel` prefers the GQA-optimized path which requires `K->ne[1] % 256 == 0`. The DS4 `is_prefill && n_comp == 0` raw-window reservation path can hit a tiny `K->ne[1] == 1` shape, triggering a rejection that disables Flash Attention globally.

## Narrow Patch

Patch artifact (apply to the external runtime tree, not this repo):

- `docs/patches/llama-cpp-kamnxt-ds4-fattn-reservation.patch`

Effect:

- In `src/models/deepseek4.cpp`, when `is_prefill && n_comp == 0` and Flash Attention is enabled and `n_embd_head_k == 512`, pad the `kv` window and mask to the next 256-token boundary.
- Remove temporary `ACCEPT/REJECT __fattn__` debug prints from the CUDA backend (keeps logs cleaner for profiling).

## Probe (Regression Check)

Run a resident `llama-server` sweep and inspect the emitted probe JSON:

- Script: `scripts/benchmark_llamacpp_server_sweep.py`
- Output: `fattn_reservation_probe.json` in `OUT_DIR`

Optional (best-effort): the one-shot `llama-cli` baseline (`scripts/benchmark_llamacpp_spark.sh`) also emits `fattn_cli_probe.json` when the runtime prints `sched_reserve:` / `__fattn__-*` / `__op__-*` placement lines during the run. This is not guaranteed across forks, but it provides a low-friction check for CUDA/CPU fallback signals without running a resident server.

The batching/concurrency throughput sweep (`scripts/benchmark_llamacpp_server_throughput_sweep.py`) also emits `fattn_reservation_probe.json` per `(parallel,batch,ubatch)` combo directory, which is useful when validating that Flash Attention stays enabled under `--parallel 2` and high batching. See `docs/baseline-batching-throughput.md`.

### Cheap Source Probe (Patch Presence)

To confirm the **pad-to-256** reservation fix is present in the external runtime tree without loading a model, run the baseline wrapper with:

```sh
LLAMA_FATTN_PATCH_PROBE=1 \
LLAMA_DIR=/abs/path/on/spark/to/llama.cpp \
scripts/run_baseline_existing_runtime.sh spark0@aitopatom-9ab9.local
```

This runs a read-only scan (`scripts/benchmark_llamacpp_fattn_patch_probe.py`) on Spark and fetches:

- `fattn_patch_probe.json` (in the fetched probe artifacts dir)

Key fields (heuristic):

- `pad256_found=True` suggests the `GGML_PAD(n_tokens, 256)` + `n_embd_head_k == 512` logic is present in the runtime sources.
- `patch_artifact_sha256` pins the expected patch artifact in this repo (`docs/patches/llama-cpp-kamnxt-ds4-fattn-reservation.patch`) for cross-run bookkeeping.

This source probe does **not** guarantee `__fattn__` schedules on CUDA; use the resident server sweep probe for that.

### Run From Mac (baseline wrapper)

To attach the probe to the standard baseline entrypoint (so the artifacts get fetched and recorded in the same report), run from the Mac:

```sh
ALLOW_RUN=1 \
LLAMA_SERVER_SWEEP=1 \
MODEL_GGUF=/abs/path/on/spark/to/model.gguf \
LLAMA_SERVER=/abs/path/on/spark/to/llama-server \
LLAMA_SERVER_SWEEP_CTX=8192 \
LLAMA_SERVER_SWEEP_PORT=18081 \
LLAMA_SERVER_SWEEP_SERVER_ARGS="--cache-ram -1 --fit off --no-warmup --no-webui --cache-prompt --parallel 1 --log-verbosity 2" \
scripts/run_baseline_existing_runtime.sh spark0@aitopatom-9ab9.local
```

Notes:

- `LLAMA_SERVER` is required when `LLAMA_SERVER_SWEEP=1`.
- Use a non-default port to avoid colliding with any resident server already running.
- Keep `LLAMA_SERVER_SWEEP_PROMPT_WORDS` small when iterating; the sweep is intended to be **read-only**, but model loads are still expensive.

The script writes these fields into `server_sweep.md` metadata:

- `fattn_seen_disabled`: should be `False` on a healthy runtime
- `fattn_seen_sched_reserve_cpu`: should be `False` on a healthy runtime
- `fattn_line_count` / `fattn_node_unique`: should be non-zero when the runtime logs `__fattn__` scheduling placement
- `fattn_id_min` / `fattn_id_max` / `fattn_id_missing_count`: best-effort `__fattn__-{id}` range check (helps confirm the expected reservation graph shape, e.g. `0..42` with no gaps)
- `fattn_expected_id_0_42_ok`: derived boolean for the common Spark0 expectation (`id_min=0`, `id_max>=42`, no gaps); `NA` when ids are not logged
- `fattn_backend0_only` / `fattn_backend_counts`: best-effort parse of a `backend 0` / `cuda backend 0` tag from `__fattn__` lines (not all forks include it)
- `fattn_expected_backend0_ok`: derived boolean (`backend0_only`) when backend tags are present; `NA` otherwise
- `fattn_cuda_device0_only` / `fattn_cuda_device_counts`: best-effort parse of `CUDA0` tags from `__fattn__` lines (not all forks include it)
- `fattn_expected_cuda_device0_ok`: derived boolean (`cuda_device0_only`) when device tags are present; `NA` otherwise
- `sched_reserve_graph_nodes` / `sched_reserve_graph_splits` / `sched_reserve_took_ms`: best-effort parse of reservation summary lines (helps compare graph size / split count)
- `node_kind_unique`: unique `__op__` kinds seen in the log (best-effort)
- `node_kind_cpu_top` / `node_kind_cuda_top`: best-effort top-k counts by `__op__` kind, based on whether each matching log line mentions `cpu` / `cuda`

Interpretation:

- `fattn_seen_disabled=True` means Flash Attention was disabled globally during reservation and the run is not a clean baseline.
- `fattn_seen_sched_reserve_cpu=True` usually indicates a CPU placement fallback on the Flash Attention tensor during reservation.
- If the fork logs `__fattn__-{id}` placement, a clean patched run should typically show `fattn_id_min=0`, `fattn_id_max>=42`, and `fattn_id_missing_count=0` (exact max may vary by build).
- If the fork logs backend/device tags, a clean patched run should typically show `fattn_backend0_only=True` and/or `fattn_cuda_device0_only=True` (Spark0 backend/device 0).

This probe is designed to be **read-only**: it parses the server log emitted by the sweep and records a bounded sample of matching lines for later debugging.

## Non-goals / Next Bottleneck

This patch/probe restores Flash Attention scheduling during reservation, but it does not explain the remaining throughput gap. For the current observed post-fix ceiling (about ~293 prompt tok/s at ~4k and ~12–15 gen tok/s), see `docs/quantized-spark0-results-2026-05-09.md` and prioritize the read-only instrumentation checklist in `docs/quantized-performance-path.md`.
