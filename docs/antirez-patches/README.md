# antirez patches (ds4 / llama.cpp)

This directory contains **narrow, reviewable patch files** meant to be applied to upstream runtimes when validating the DeepSeek V4 Flash MTP-on-CUDA track.

## ds4

- `ds4-3630e64-cuda-mtp-q4k-and-sidecar-map.patch`
  - Target: `antirez/ds4@3630e64`
  - Purpose:
    - allow the DS4-tuned MTP sidecar to use `Q4_K` routed experts on CUDA (fallback path)
    - prevent the MTP sidecar map from clobbering the trunk CUDA model-map/fd-cache owner

- `ds4-3630e64-cuda-multi-model-cache.patch`
  - Target: `antirez/ds4@3630e64`
  - Purpose:
    - fix CUDA weight-cache keying so cached ranges are keyed by `(model_map, fd, offset)` (not just `offset`)
    - add `ds4_gpu_set_model_fd_for_map(model_map, fd)` so the MTP sidecar can register its fd without clobbering the trunk fd state
    - avoids trunk/sidecar cache collisions when `DS4_CUDA_WEIGHT_CACHE=1` (or when fd-caching is enabled)
    - keeps the trunk startup tensor cache enabled when `--mtp` is active, so decode does not lazily page trunk tensors while drafting/verifying
    - auto-budgets the MTP trunk cache to half of reported CUDA memory unless `DS4_CUDA_WEIGHT_CACHE_LIMIT_GB` is set
    - defaults MTP CUDA weight arena chunks to 512 MiB unless `DS4_CUDA_WEIGHT_ARENA_CHUNK_MB` is set, reducing large contiguous allocation pressure
    - treats MTP startup caching as best-effort so a cache budget stop leaves a hot resident prefix instead of aborting startup
    - keeps the largest cached mapping per key to avoid cache thrash on repeated partial range requests

- `ds4-3630e64-cuda-moe-expert-slice-cache.patch`
  - Target: `antirez/ds4@3630e64`, applied after the Q4K sidecar patch and multi-model cache patch
  - Purpose:
    - adds an opt-in decode path for `DS4_CUDA_MOE_EXPERT_SLICE_CACHE=1`
    - copies the selected top-6 expert IDs to host for one-token decode, caches only those gate/up/down expert slices, and passes per-expert device pointers into CUDA kernels
    - avoids requesting the full 256-expert `moe_gate`, `moe_up`, and `moe_down` slabs on the hot decode path
    - covers the fast IQ2/Q2 decode kernels and the Q4_K MTP sidecar fallback kernels
    - keeps the existing full-slab path as fallback; `DS4_CUDA_MOE_EXPERT_SLICE_STRICT=1` makes slice preparation failures fatal for testing
    - `DS4_CUDA_MOE_EXPERT_SLICE_VERBOSE=1` prints selected-slice residency size

- `ds4-3630e64-cuda-moe-batched-expert-slice-queue.patch`
  - Target: `antirez/ds4@3630e64`, applied after the expert-slice cache patch
  - Purpose:
    - adds an opt-in batched decode path for `DS4_CUDA_MOE_BATCHED_EXPERT_SLICE_CACHE=1`
    - reuses the real sorted expert-pair counts to discover active experts for the current batch
    - caches active gate/up/down expert slices instead of requesting full 256-expert MoE slabs
    - routes the sorted and p2 sorted gate/up/down kernels through per-expert slice pointer tables
    - keeps full-slab fallback when slice preparation fails unless `DS4_CUDA_MOE_EXPERT_SLICE_STRICT=1` is set

- `ds4-3630e64-cuda-moe-batched-expert-tile-slices.patch`
  - Target: `antirez/ds4@3630e64`, applied after the batched expert-slice queue patch
  - Purpose:
    - keeps expert-tile kernels enabled when `DS4_CUDA_MOE_BATCHED_EXPERT_SLICE_CACHE=1`
    - makes the gate/up row32 and row-span tile kernels accept optional per-expert slice pointer tables
    - makes the down row32, row-span, and block16 tile kernels accept optional per-expert slice pointer tables
    - preserves the contiguous full-slab path by passing null pointer tables when slice caching is disabled
    - moves the real batched slice path onto the high-throughput expert-tile route instead of the scalar sorted fallback
    - reserves slice-pointer storage inside the sorted-pair scratch buffer so the pointer table cannot overwrite expert counts/offsets
    - defaults the batched down tile path away from the slower block16 down kernel on Spark/GB10; `DS4_CUDA_MOE_DOWN_BLOCK16=1` restores it for A/B testing

- `ds4-3630e64-mtp-one-token-json-probe.patch`
  - Target: `antirez/ds4@3630e64`
  - Purpose:
    - adds a `--dump-mtp-one-token-json` CLI mode that emits a single JSON object to stdout
    - captures `base_next_token_id`, `mtp_draft_token_id`, plus intermediate tensor `*_fnv64` fingerprints (`trunk_token_embd`, `trunk_pre_hc_head`, `mtp_input_hc`, `mtp_block_out_hc`, `mtp_head_norm`)
    - also captures pre-`mtp_input_hc` intermediates (`mtp_enorm`, `mtp_eproj`, `mtp_eproj_hc`, `mtp_hnorm_hc`, `mtp_hproj_hc`) to localize oracle-vs-candidate mismatches
    - intended for oracle-vs-candidate diffs via `python3 scripts/diff_mtp_one_token_draft_probe.py`

- `ds4-3630e64-cuda-moe-probe-and-startup-cache-skip.patch`
  - Target: `antirez/ds4@3630e64`, applied after the batched expert-tile slice patch
  - Purpose:
    - adds `--cuda-moe-probe` to isolate the real CUDA routed-MoE path without running the full decode graph
    - adds `--cuda-layer-probe` and `--cuda-ffn-probe` to measure the graph layer or FFN half around the routed-MoE kernel at the same synthetic batch size
    - adds `--cuda-decode-probe` to measure one warmed decode layer with synthetic resident HC/raw/compressed cache state
    - adds `--cuda-decode-stack-probe`, `--cuda-batch-stack-probe`, and `--cuda-output-head-probe` to move from weighted estimates toward direct full-stack measurements
    - uses the real router matmul, real selected experts, real expert weights, and real `ds4_gpu_routed_moe_batch_tensor(...)`
    - adds `--cuda-moe-layer`, `--cuda-moe-tokens`, `--cuda-moe-iters`, and `--cuda-decode-pos` sweep knobs
    - emits JSON with queue depth, best routed-pair throughput, best layer/FFN/decode throughput, output fingerprint, and non-finite counts
    - adds `DS4_CUDA_MOE_PROBE_COMPARE_FULL=1` to compare batched active-slice output against the full-slab tiled path in one process
    - adds `DS4_CUDA_SKIP_STARTUP_MODEL_CACHE=1` so the probe can keep lazy expert loading while avoiding huge eager startup cache attempts
    - lowers the startup preload span floor to 4 MiB and adds `DS4_CUDA_WEIGHT_PRELOAD_SLEEP_US` for paced residency experiments

- `ds4-3630e64-cuda-stack-stage-range-preload.patch`
  - Target: `antirez/ds4@3630e64`, applied after the CUDA MoE probe/startup-cache skip patch
  - Purpose:
    - adds `DS4_CUDA_STACK_PROBE_LAYER_BEGIN` and `DS4_CUDA_STACK_PROBE_LAYER_END` so stack probes can run a contiguous layer stage instead of all 43 layers
    - adds `DS4_CUDA_STACK_PROBE_PRELOAD_STAGE=1` to preload every tensor required by that stage before timing
    - adds `DS4_CUDA_STACK_PROBE_PRELOAD_CHUNK_MB` and `DS4_CUDA_STACK_PROBE_PRELOAD_SLEEP_US` for stage-local residency tuning when large range uploads hit CUDA launch timeouts
    - preloads routed expert slabs (`ffn_gate_exps`, `ffn_up_exps`, `ffn_down_exps`) for every owned layer so the tested stage does not fall back to lazy expert loads
    - preloads stage weights before graph activation buffers are allocated, so the stage's owned weights get first claim on GPU memory
    - keeps output-head work only on the final stage unless `DS4_CUDA_STACK_PROBE_NO_HEAD=1` is absent and the stage ends at layer 43
    - lets a three-Spark stage split run as `[0,15)`, `[15,29)`, `[29,43)` without hardcoding the topology into C

- `ds4-3630e64-cuda-explicit-stage-preload.patch`
  - Target: `antirez/ds4@3630e64`, applied after the stack-stage range preload patch
  - Purpose:
    - fixes the stage preload path so it no longer calls the generic demand-cache range loader for each tensor/chunk
    - adds `ds4_gpu_preload_model_range(...)`, which allocates the final device-resident tensor range from the CUDA arena, reads through the pinned staging pool, copies explicit chunks with `cudaMemcpy`, and registers the completed range in the CUDA model cache
    - keeps routed expert slabs resident as full owned-stage tensors, with semantic labels such as `stack_stage_l0_ffn_gate_exps`, `stack_stage_l0_ffn_up_exps`, and `stack_stage_l0_ffn_down_exps`
    - turns the prior misleading `lazy_moe_range_upload` timeout into a real explicit-preload path with exact tensor labels
    - allowed the first successful B=64 three-Spark owned-stage run after the Sparks were made headless and stale RPC GPU contexts were killed

- `ds4-3630e64-cuda-stage-handoff-files.patch`
  - Target: `antirez/ds4@3630e64`, applied after the explicit stage preload patch
  - Purpose:
    - adds host-visible stage boundary import/export to `--cuda-batch-stack-probe`
    - `DS4_CUDA_STACK_PROBE_EMBED_INPUT=1` seeds stage0 from token embeddings instead of synthetic HC rows
    - `DS4_CUDA_STACK_PROBE_OUTPUT_HC_FILE=/path/boundary.bin` writes the post-stage `[batch,hc,hidden]` f32 boundary
    - `DS4_CUDA_STACK_PROBE_INPUT_HC_FILE=/path/boundary.bin` imports that boundary for the next stage
    - emits boundary metadata in the probe JSON so handoff artifacts can prove finite final logits/hash

Apply (example):

```bash
git clone https://github.com/antirez/ds4.git
cd ds4
git checkout 3630e64
git apply /path/to/ds4_on_spark/docs/antirez-patches/ds4-3630e64-cuda-mtp-q4k-and-sidecar-map.patch
git apply /path/to/ds4_on_spark/docs/antirez-patches/ds4-3630e64-cuda-multi-model-cache.patch
git apply /path/to/ds4_on_spark/docs/antirez-patches/ds4-3630e64-cuda-moe-expert-slice-cache.patch
git apply /path/to/ds4_on_spark/docs/antirez-patches/ds4-3630e64-cuda-moe-batched-expert-slice-queue.patch
git apply /path/to/ds4_on_spark/docs/antirez-patches/ds4-3630e64-cuda-moe-batched-expert-tile-slices.patch
git apply /path/to/ds4_on_spark/docs/antirez-patches/ds4-3630e64-cuda-moe-probe-and-startup-cache-skip.patch
git apply /path/to/ds4_on_spark/docs/antirez-patches/ds4-3630e64-cuda-stack-stage-range-preload.patch
git apply /path/to/ds4_on_spark/docs/antirez-patches/ds4-3630e64-cuda-explicit-stage-preload.patch
git apply /path/to/ds4_on_spark/docs/antirez-patches/ds4-3630e64-cuda-stage-handoff-files.patch
git apply /path/to/ds4_on_spark/docs/antirez-patches/ds4-3630e64-mtp-one-token-json-probe.patch
```

Host-side math sanity check (no CUDA required):

```bash
python3 /path/to/ds4_on_spark/scripts/verify_antirez_ds4_q4k_dot_math.py
```

Fixture provenance and regeneration (optional; no CUDA required):

- `docs/mtp-q4k-dot-validation.md`

Patch verifiers (no CUDA required):

```bash
python3 /path/to/ds4_on_spark/scripts/verify_antirez_ds4_cuda_mtp_q4k_sidecar_patch.py --patch /path/to/ds4_on_spark/docs/antirez-patches/ds4-3630e64-cuda-mtp-q4k-and-sidecar-map.patch
python3 /path/to/ds4_on_spark/scripts/verify_antirez_ds4_cuda_multi_model_cache_patch.py --patch /path/to/ds4_on_spark/docs/antirez-patches/ds4-3630e64-cuda-multi-model-cache.patch
python3 /path/to/ds4_on_spark/scripts/verify_antirez_ds4_cuda_moe_expert_slice_patch.py --patch /path/to/ds4_on_spark/docs/antirez-patches/ds4-3630e64-cuda-moe-expert-slice-cache.patch
python3 /path/to/ds4_on_spark/scripts/verify_antirez_ds4_cuda_moe_batched_expert_slice_queue_patch.py --patch /path/to/ds4_on_spark/docs/antirez-patches/ds4-3630e64-cuda-moe-batched-expert-slice-queue.patch
python3 /path/to/ds4_on_spark/scripts/verify_antirez_ds4_cuda_moe_batched_expert_tile_slices_patch.py --patch /path/to/ds4_on_spark/docs/antirez-patches/ds4-3630e64-cuda-moe-batched-expert-tile-slices.patch
python3 /path/to/ds4_on_spark/scripts/verify_antirez_ds4_cuda_moe_probe_patch.py --patch /path/to/ds4_on_spark/docs/antirez-patches/ds4-3630e64-cuda-moe-probe-and-startup-cache-skip.patch
python3 /path/to/ds4_on_spark/scripts/verify_antirez_ds4_cuda_stack_stage_preload_patch.py --patch /path/to/ds4_on_spark/docs/antirez-patches/ds4-3630e64-cuda-stack-stage-range-preload.patch
python3 /path/to/ds4_on_spark/scripts/verify_antirez_ds4_cuda_explicit_stage_preload_patch.py --patch /path/to/ds4_on_spark/docs/antirez-patches/ds4-3630e64-cuda-explicit-stage-preload.patch
python3 /path/to/ds4_on_spark/scripts/verify_antirez_ds4_cuda_stage_handoff_patch.py --patch /path/to/ds4_on_spark/docs/antirez-patches/ds4-3630e64-cuda-stage-handoff-files.patch
python3 /path/to/ds4_on_spark/scripts/verify_antirez_ds4_mtp_one_token_oracle_patch.py --patch /path/to/ds4_on_spark/docs/antirez-patches/ds4-3630e64-mtp-one-token-json-probe.patch
```

The verifier will also validate against the repo’s pinned llama.cpp Q4_K test vectors when the fixture file is present:

- `fixtures/quant/q4k_llamacpp_b9110_rowdot_fixture.json`

Local patch integrity check (no CUDA required):

```bash
python3 /path/to/ds4_on_spark/scripts/verify_antirez_ds4_cuda_multi_model_cache_patch.py \
  --patch /path/to/ds4_on_spark/docs/antirez-patches/ds4-3630e64-cuda-multi-model-cache.patch
```

Spark oracle runner (fetch/patch/build/run; all gated on Spark-side env):

```bash
REMOTE_ANTIREZ_DS4_MTP_ORACLE_ENV="ALLOW_FETCH=1 ALLOW_PATCH=1 ALLOW_BUILD=1 ALLOW_RUN=1" \
scripts/run_antirez_ds4_mtp_one_token_oracle_probe_spark.sh spark0@<spark-host>
```
