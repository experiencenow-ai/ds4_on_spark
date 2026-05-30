# Qwen27 NVFP4 PP8 external-KV pipeline

This service is cache-primary. The reason to pipeline Qwen27 is not raw decode speed; it is to make Qwen a single Spark-fleet resource with predictable per-node memory, one spark0 entrypoint, and pipeline-layer-sharded external KV/cache.

Service shape:

```text
service_id:      qwen27_nvfp4_pp8
profile_id:      qwen3_6_27b_nvfp4_pp8_fast_cache_v1
entrypoint:      spark0:8103
placement:       PP8 x TP1, one rank on each Spark
model:           sakamakismile/Qwen3.6-27B-Text-NVFP4-MTP
MTP default:     disabled
KV layout:       LMCacheConnectorV1 native HMA, one layer shard per Spark
partition PP8:   9,9,9,8,8,8,8,5
```

The model name contains `MTP` because that is the available text-only ModelOpt NVFP4 checkpoint. The production PP8 service does not enable speculative decoding unless the operator explicitly opts into the experimental path. External KV commits are base-model verified state only.

Launch one rank per Spark:

```bash
export HEAD_ADDR=<spark0-200g-address-or-hostname>
export NNODES=8

for rank in 0 1 2 3 4 5 6 7
do
    ssh spark${rank} \
      "cd /home/\$USER/ds4_on_spark/v2 && NODE_RANK=${rank} HEAD_ADDR=${HEAD_ADDR} NNODES=${NNODES} ./scripts/ds4_launch_qwen27_nvfp4_pp.sh"
done
```

The launcher enforces text-only/native path basics:

```text
--language-model-only
--quantization modelopt
--linear-backend flashinfer-cutlass
--kv-cache-dtype fp8
--pipeline-parallel-size $NNODES
--tensor-parallel-size 1
--distributed-executor-backend mp
--enable-prefix-caching
--enable-chunked-prefill
--no-disable-hybrid-kv-cache-manager
--mamba-cache-mode align
LMCacheConnectorV1 native HMA
no Marlin / no emulation
```

For N other than 8, the launcher uses a simple `64 / N` decoder-layer split with the remainder assigned to early stages. Operators may override with an arbitrary partition:

```bash
export NNODES=7
export QWEN27_PP_LAYER_PARTITION=10,9,9,9,9,9,9
```

The override must have exactly `NNODES` positive integers and must sum to 64, otherwise startup fails before vLLM begins serving.

## KV placement

A logical external KV object is recorded as one shard per pipeline stage. For the PP8 partition, the stage ownership is:

```text
spark0 layers 0:9
spark1 layers 9:18
spark2 layers 18:27
spark3 layers 27:35
spark4 layers 35:43
spark5 layers 43:51
spark6 layers 51:59
spark7 layers 59:64
```

That means a logical Qwen cache entry should occupy roughly 1/8 of its logical cache bytes on each Spark, instead of being replicated to all possible Qwen workers.

## MTP

MTP is optional and disabled by default:

```text
QWEN27_NVFP4_ENABLE_MTP=0
```

A targeted bring-up run may opt in:

```bash
export QWEN27_NVFP4_ENABLE_MTP=1
export QWEN27_NVFP4_ENABLE_MTP_EXPERIMENTAL=1
```

That path is not a production requirement. The production cache-primary pipeline should be validated without MTP first.
