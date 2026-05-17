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

- `ds4-3630e64-cuda-stage-handoff-streaming.patch`
  - Target: `antirez/ds4@3630e64`, applied after the stage-handoff files patch
  - Purpose:
    - allows `%u` in boundary input/output paths so one resident stage process can process multiple microbatches without restarting
    - adds `DS4_CUDA_STACK_PROBE_INPUT_WAIT_MS` so downstream stages can wait for upstream boundary files
    - writes one boundary file per microbatch and reads one boundary file per microbatch
    - emits `iter_ms`, `out_fnv64s`, `out_nonfinites`, `logits_fnv64s`, and `logits_nonfinites` arrays for streaming schedule reconstruction
    - keeps PP=1 parity separate; the streaming handoff proof is finite-logits evidence, not provider eligibility

- `ds4-3630e64-cuda-token-commit-profile-constrained.patch`
  - Target: `antirez/ds4@3630e64`, applied after the B=512 batch-head token-commit patch
  - Purpose:
    - emits `ds4-token-commit-profile-v1` timing for final hidden output, output head, top-1/argmax, readback, token hash, result collection, and sync wait
    - adds `DS4_CUDA_STACK_PROBE_CONSTRAINED_TOKEN_IDS=...` for exact top-1 commit over a declared candidate-token set
    - avoids the full 512-row vocabulary projection for constrained short-output tasks while preserving a final-row full-logits hash
    - keeps `production_generation_eligible=false`; this is a decode-only committed-token benchmark path, not the shared-prefix/suffix/KV production loop

- `ds4-3630e64-cuda-b512-multistep-kv-loop.patch`
  - Target: `antirez/ds4@3630e64`, applied after the constrained token-commit profile patch
  - Purpose:
    - adds `DS4_CUDA_STACK_PROBE_DECODE_STEPS=4|8` for repeated short-output decode
    - commits token ids and token hashes at every step
    - feeds committed ids back through the token embedding path so step 2+ updates session/KV state instead of reseeding from the original probe input
    - emits per-step decode, commit, KV-update, and token-hash arrays for `ds4-b512-end-to-end-decode-v1`
    - keeps row replacement disabled for this PR

- `ds4-3630e64-mtp-target-suffix-verify-k2.patch`
  - Target: `antirez/ds4@3630e64`, applied after the Q4K sidecar and multi-model cache patches
  - Purpose:
    - introduces the target-suffix verifier API shape required for economical MTP verification:
      `target_suffix_verify(checkpoint_state, draft_tokens[2])`
    - routes greedy `--mtp` through the direct argmax graph path by default; `DS4_MTP_SESSION=1` keeps the older session verifier path available for diagnostics
    - makes the DeepSeek-shaped K=2 verifier the default path: preserve the current target hidden state, draft two future tokens from it, append `[target_token, draft0, draft1]`, and run one target suffix verifier over all three positions
    - captures prefix-1 and prefix-2 verifier frontiers, so a row0-only match can still commit `[target_token, draft0]` without replaying serial target decode
    - preloads the MTP sidecar before the decode timer so first-draft lazy tensor caching does not poison generation TPS
    - uses the CUDA Q8 output-head top1 primitive by default for row0/row1 accept checking; row2 remains full logits for exact greedy continuation, and `DS4_MTP_ROW0_FULL_LOGITS=1` restores full-vocab verifier rows for A/B testing
    - carries the GPU-selected row2 continuation argmax into the next loop iteration, avoiding a CPU full-vocab argmax scan per accepted group
    - reads the already-materialized row2 logits only when trace/debug output needs host logits; the unsafe row2 no-readback escape hatch is intentionally absent because lazy readback is now tied to the valid pending continuation token instead of a free env knob
    - keeps the experimental row2 top1-only continuation path behind `DS4_MTP_ROW2_TOP1_CONT=1`; the measured experiment lowered acceptance, so it is not the default exact path
    - keeps partial-accept top1-only continuation behind `DS4_MTP_PARTIAL_TOP1_CONT=1`; the default still materializes exact continuation logits on partial accepts
    - stops the direct generation loop once `n_generated >= n_predict`, so multi-token commits do not run extra serial iterations after the requested output budget
    - uses top1-only MTP draft heads when draft logits are not requested; `DS4_MTP_DRAFT_FULL_LOGITS=1` restores full-vocab draft logits for diagnostics
    - adds `DS4_SUPPRESS_OUTPUT=1` for model-throughput benchmarks that still commit tokens but skip per-token CLI text rendering and stdout flush
    - keeps `DS4_MTP_SERIAL_SUFFIX=1` only as a diagnostic escape hatch for comparing against the older serial decode verifier
    - emits verifier invocation/position/head-row accounting; the intended fast path reports `verifier_calls=1`, `target_positions=3`, and `first_eval=0.000 ms` for full K=2 accepts
    - prototypes the next K=3 direct verifier first: `--mtp-draft 3` drafts three tokens, verifies `[target_token,draft0,draft1,draft2]` in one 4-row target suffix job, uses top1 rows 0-2 plus full continuation logits on row3, and reports `target_positions=4` on full accepts
    - adds a prefix-3 verifier frontier, so a row0+row1 K=3 partial accept can commit `[target_token,draft0,draft1]` and materialize row2 continuation logits without serial target replay

- `ds4-3630e64-cuda-b512-row-token-input.patch`
  - Target: `antirez/ds4@3630e64`, applied after the token-commit profile/constrained patch
  - Purpose:
    - adds `DS4_CUDA_STACK_PROBE_ROW_TOKEN_IDS=...` so B=512 stage0 embedding input can use explicit per-row compact suffix token IDs
    - emits `row_token_input`, `row_token_count`, and suffix-token metadata through the stage-handoff artifact path
    - enables the shared-prefix compact-suffix 1-token prompt benchmark without changing MoE kernels or claiming production eligibility

- `ds4-3630e64-cuda-constrained-candidate-dynamic.patch`
  - Target: `antirez/ds4@3630e64`, applied after the row-token input patch
  - Purpose:
    - removes the fixed 256-token `DS4_CUDA_STACK_PROBE_CONSTRAINED_TOKEN_IDS` parse cap
    - allocates the constrained candidate ID list from the actual env-sized count for probe startup
    - emits requested/enforced constrained candidate counts so sweep artifacts can reject truncation

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
git apply /path/to/ds4_on_spark/docs/antirez-patches/ds4-3630e64-cuda-stage-handoff-streaming.patch
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
python3 /path/to/ds4_on_spark/scripts/verify_antirez_ds4_cuda_stage_handoff_streaming_patch.py --patch /path/to/ds4_on_spark/docs/antirez-patches/ds4-3630e64-cuda-stage-handoff-streaming.patch
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
