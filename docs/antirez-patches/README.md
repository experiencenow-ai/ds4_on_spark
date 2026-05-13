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
    - avoids trunk/sidecar cache collisions when `DS4_CUDA_WEIGHT_CACHE=1` (or when fd-caching is enabled)
    - keeps the largest cached mapping per key to avoid cache thrash on repeated partial range requests

- `ds4-3630e64-mtp-one-token-json-probe.patch`
  - Target: `antirez/ds4@3630e64`
  - Purpose:
    - adds a `--dump-mtp-one-token-json` CLI mode that emits a single JSON object to stdout
    - captures `base_next_token_id`, `mtp_draft_token_id`, plus intermediate tensor `*_fnv64` fingerprints (`trunk_token_embd`, `trunk_pre_hc_head`, `mtp_input_hc`, `mtp_block_out_hc`, `mtp_head_norm`)
    - also captures pre-`mtp_input_hc` intermediates (`mtp_enorm`, `mtp_eproj`, `mtp_eproj_hc`, `mtp_hnorm_hc`, `mtp_hproj_hc`) to localize oracle-vs-candidate mismatches
    - intended for oracle-vs-candidate diffs via `python3 scripts/diff_mtp_one_token_draft_probe.py`

Apply (example):

```bash
git clone https://github.com/antirez/ds4.git
cd ds4
git checkout 3630e64
git apply /path/to/ds4_on_spark/docs/antirez-patches/ds4-3630e64-cuda-mtp-q4k-and-sidecar-map.patch
git apply /path/to/ds4_on_spark/docs/antirez-patches/ds4-3630e64-cuda-multi-model-cache.patch
git apply /path/to/ds4_on_spark/docs/antirez-patches/ds4-3630e64-mtp-one-token-json-probe.patch
```

Host-side math sanity check (no CUDA required):

```bash
python3 /path/to/ds4_on_spark/scripts/verify_antirez_ds4_q4k_dot_math.py
```

Patch verifiers (no CUDA required):

```bash
python3 /path/to/ds4_on_spark/scripts/verify_antirez_ds4_cuda_mtp_q4k_sidecar_patch.py --patch /path/to/ds4_on_spark/docs/antirez-patches/ds4-3630e64-cuda-mtp-q4k-and-sidecar-map.patch
python3 /path/to/ds4_on_spark/scripts/verify_antirez_ds4_cuda_multi_model_cache_patch.py --patch /path/to/ds4_on_spark/docs/antirez-patches/ds4-3630e64-cuda-multi-model-cache.patch
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
