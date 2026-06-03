# Baked vLLM Profiles

DS4 production launches should not rediscover the vLLM recipe from shell defaults, inherited environment, and multiple JSON files. A baked profile resolves those inputs once into an immutable `engine.lock.json`.

The lock is not a serialized CUDA engine. vLLM still creates CUDA contexts, loads weights, allocates KV blocks, sets up communicators, and may capture CUDA graphs at launch. The lock makes that launch verify a known plan instead of inventing one.

## Bake

Example conservative DSV4 PP7 semantic profile:

```bash
PYTHONPATH=src python3 scripts/ds4_bake_vllm_profile.py \
  --profile-name dsv4_flash_pp7_semantic_cpu_staged \
  --runtime-contract profiles/runtime_contracts/dsv4_flash_pp8_mtp_v1.json \
  --topology /private/tmp/ds4_topology_pp7_runtime.json \
  --service-id dsv4_flash_pp8 \
  --vllm-repo ../upstreams/vllm \
  --output /opt/ds4/baked_profiles/dsv4_flash_pp7_semantic_cpu_staged \
  --served-model-name deepseek-v4-flash-pp7 \
  --node-ids spark0,spark1,spark2,spark3,spark4,spark5,spark6 \
  --layer-partition 7,6,6,6,6,6,6 \
  --pipeline-parallel-size 7 \
  --set-arg=--max-num-seqs=1 \
  --set-arg=--max-num-batched-tokens=8192 \
  --drop-arg=--speculative-config \
  --set-env DS4_PP_TRANSPORT=tcp-staged \
  --set-env DSV4_ENABLE_MTP=0 \
  --set-env DSV4_ENABLE_PREFIX_CACHING=0 \
  --set-env DSV4_KV_OFFLOADING_SIZE=0 \
  --expect-banner moe_backend=FLASHINFER_CUTLASS_MXFP4_MXFP8 \
  --semantic-preset dsv4-basic
```

The generated lock records:

```text
DS4 and vLLM commits
model path and served model name
exact vLLM args
exact environment variables
node order
PP/TP/EP settings
layer partition and stage starts
profile-specific VLLM_CACHE_ROOT
expected backend banner fields
semantic probes
self hash
```

Each profile gets its own `VLLM_CACHE_ROOT` containing the profile hash. Do not share cache roots between PP7/PP8/PP16, Qwen, debug flags, MTP on/off, or different commits.

## Verify And Export

```bash
PYTHONPATH=src python3 scripts/ds4_launch_baked_profile.py \
  /opt/ds4/baked_profiles/dsv4_flash_pp7_semantic_cpu_staged/engine.lock.json \
  --vllm-repo ../upstreams/vllm \
  --write-rank-dir /opt/ds4/baked_profiles/dsv4_flash_pp7_semantic_cpu_staged/ranks \
  --print-summary
```

Verification fails if:

```text
lock contents do not match lock_sha256
DS4 commit differs from the lock
vLLM commit differs from the lock
node count and PP size differ
layer partition and PP size differ
required vLLM args are absent
VLLM_CACHE_ROOT is absent
current environment differs from locked values when --verify-current-env is used
```

## Policy

Bake semantic and fast profiles separately:

```text
dsv4_flash_pp7_semantic_cpu_staged
dsv4_flash_pp7_fast
qwen27_pp8_fp8kv
qwen54_ppN_fp8kv
```

Do not route traffic or run benchmarks from a launch that does not match its baked lock. If the lock fails verification, stop the launch and fix the profile instead of adding another shell override.
