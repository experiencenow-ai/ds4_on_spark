# DS4 RPC split compute probe, 2026-05-12

This probe tested whether quantized DeepSeek V4 Flash can execute across the
three Spark nodes through llama.cpp RPC/RDMA, and compared the split runs to a
single-Spark quantized baseline.

## Setup

- Hardware: 3x NVIDIA DGX Spark / GB10 nodes on the 100 GbE fabric ring.
- Controller: Spark0.
- Workers: Spark1 and Spark2 running Kamnxt llama.cpp `rpc-server`.
- Runtime source: `llama.cpp-kamnxt`, commit `9222e55c1-dirty`.
- Build flags: CUDA, RPC, CUDA architecture 121a.
- Runtime env: `GGML_CUDA_DISABLE_GRAPHS=1`.
- Model: `DeepSeek-V4-Flash-IQ2XXS-w2Q2K-AProjQ8-SExpQ8-OutQ8-chat-v2.gguf`.
- Prompt: `Explain Redis streams in one paragraph.`
- Common args: `-n 8 -c 512 -ngl 99 --fit off --cache-ram -1 --show-timings --perf --single-turn --simple-io --no-display-prompt --no-warmup`.

The successful distributed runs required a temporary CUDA proof patch in
`ggml/src/ggml-cuda/binbcast.cu` to allow the DS4 grouped-output `I32` ID repeat
to execute on remote CUDA backends. See
`patches/kamnxt-i32-repeat-proof-for-ds4-rpc.patch`.

## Results

| Mode | Layer placement | Model memory | Prompt tok/s | Gen tok/s | Wall |
| --- | --- | --- | ---: | ---: | ---: |
| Single Spark0 | all layers local | 81,687 MiB local | 18.1 | 15.2 | 456.12 s |
| Spark0+Spark1 layer split | 0-21 local, 22-42 remote | 40,193 MiB local, 41,494 MiB remote | 15.3 | 14.0 | 171.71 s |
| Spark0+Spark1+Spark2 layer split | 0-14 local, 15-29 Spark1, 30-42 Spark2 | 25,091 MiB local, 28,294 MiB Spark1, 28,301 MiB Spark2 | 14.6 | 13.7 | 165.05 s |

## Interpretation

The important result is that distributed DS4 compute is now proven across all
three Sparks. The scheduler split the attention layers onto the intended
backends and the model produced tokens without crashing.

For one short decode stream, layer split is not a throughput win. Single Spark0
generated at 15.2 tok/s, while two-node and three-node layer splits generated at
14.0 and 13.7 tok/s. This is expected for simple layer pipeline parallelism:
each token still flows through the layer groups serially, with fabric handoff
overhead.

The split is already useful for capacity and load behavior. Model memory drops
from about 81.7 GiB on one Spark to about 40/41 GiB on two nodes, and about
25/28/28 GiB on three nodes. Wall time was also much lower in these runs because
less model data was resident on Spark0 and the RPC tensor caches were used.

The next performance question is batched throughput, not single-stream latency.
Layer-pipeline parallelism should have a better chance at higher batch sizes or
multiple queued prompts, where different sequences can occupy different layer
groups concurrently.

## Blockers Found

1. Antirez RPC server binaries did not include the Kamnxt DS4 CUDA ops and
   crashed on `DSV4_HC_SPLIT_SINKHORN`.
2. Kamnxt RPC initially crashed on remote CUDA `REPEAT` for DS4 grouped-output
   `I32` IDs.
3. Row split did not work for this model: scheduling aborted on a reshaped DS4
   weight in a split buffer that could not run `RESHAPE`.
4. Full unquantized DS4 was not tested. The Spark nodes do not yet have the
   full HF/safetensors runtime stack, such as torch/vLLM/Ray, installed.

## Next Steps

1. Replace the proof-only `I32` repeat patch with a bit-preserving CUDA repeat
   implementation and submit it upstream or vendor it cleanly.
2. Add managed RPC worker launch scripts/systemd user units for the Kamnxt build
   with `GGML_CUDA_DISABLE_GRAPHS=1` until CUDA graph capture is fixed.
3. Run a batch-throughput matrix for single, two-node, and three-node modes:
   batch sizes 1, 2, 4, 8, 16 and output lengths 32 or 64.
4. Re-test tensor split after the `I32` repeat fix, since tensor/row parallelism
   is more likely than pure layer split to improve single-token latency.
5. Keep the layer-split path as the capacity/load baseline and focus speed work
   on batching, expert queues, and model-specific parallel kernels.

