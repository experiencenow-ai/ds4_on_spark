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

The script writes these fields into `server_sweep.md` metadata:

- `fattn_seen_disabled`: should be `False` on a healthy runtime
- `fattn_seen_sched_reserve_cpu`: should be `False` on a healthy runtime
- `fattn_line_count` / `fattn_node_unique`: should be non-zero when the runtime logs `__fattn__` scheduling placement

Interpretation:

- `fattn_seen_disabled=True` means Flash Attention was disabled globally during reservation and the run is not a clean baseline.
- `fattn_seen_sched_reserve_cpu=True` usually indicates a CPU placement fallback on the Flash Attention tensor during reservation.

This probe is designed to be **read-only**: it parses the server log emitted by the sweep and records a bounded sample of matching lines for later debugging.
