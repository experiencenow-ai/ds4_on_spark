# DS4 vLLM Performance Pause Summary

Status date: 2026-05-22

## Current Decision

Pause DS4 performance work with the repo evidence centered on the standard
vLLM DeepSeek-V4-Flash serving lane.

The selected measured lane is **vLLM, DeepSeek-V4-Flash, no MTP, PP=2 over the
direct Spark4-Spark5 200G link, concurrency 256**:

- Single stream: `14.005` tok/s.
- Best measured aggregate: `171.856` tok/s at c256.
- c512 aggregate: `165.469` tok/s, slightly worse than c256.
- Runtime: `vllm`, version `0.1.dev16581+gdda4668b5.d20260521`.
- Runtime commit: `dda4668b59567416f86956cfe7bbc1eab371a61e`.

This is the official DeepSeek-V4-Flash checkpoint path, not the antirez
2-bit GGUF path. It is also not DeepSeek-V4-Pro/full 1.6T. In repo language,
"Flash" means the compact 284B-total / 13B-active model family; the measured
vLLM artifacts record the official FP8 checkpoint with fp8 KV cache and the
fp4 expert path. The measurements in this note are explicitly **no-MTP**.
So if "full resolution" means "not the antirez 2-bit GGUF and not a pruned
custom model", yes. If it means "V4-Pro/full 1.6T", no.

vLLM has a DeepSeek-V4 MTP implementation, and SGLang has DeepSeek-V4 recipes
that enable or disable MTP by serving profile. Those are future single-query
latency experiments. They are not part of the batch-provider numbers below.

## Measured Data

All rows below are forced 64 output tokens, no prefix-cache advantage, no MTP.

| Lane | Fabric | Nodes | c1 | c64 | c128 | c256 | c512 | Result |
| --- | --- | --- | ---: | ---: | ---: | ---: | ---: | --- |
| PP=2 | direct 200G pair | spark4, spark5 | `14.005` | `121.634` | `144.812` | `171.856` | `165.469` | Selected |
| PP=4 | routed 200G ring | spark3, spark4, spark5, spark6 | `13.493` | `121.539` | `149.486` | `171.788` | `168.472` | Works, not faster |
| PP=3 | Wi-Fi data plane | spark3, spark4, spark5 | `12.232` | `54.699` | `38.735` | not run | not run | Rejected |

Interpretation:

- PP=2 direct 200G is the best current batch lane.
- PP=4 over the routed 200G ring starts and runs, but is effectively tied with
  PP=2 at c256 for short 64-token outputs. Deeper pipeline parallelism did not
  improve throughput in this measured shape.
- PP=3 was rejected because the distributed data plane resolved to Wi-Fi
  addresses. It was stable enough to measure, but not a valid performance lane.

## What Worked

- Direct 200G PP=2 gives a stable provider lane and preserves the single-stream
  target of roughly 14 tok/s while scaling to useful aggregate throughput.
- c256 is the current sweet spot for 64-token batch output on the measured PP=2
  lane. c512 is close but lower, so c256 is the safer selected cap.
- PP=4 can run over the 200G ring after hostname and routing fixes. This is
  useful for memory/headroom experiments, but not yet a throughput win.
- The vLLM launch guard now rejects multi-node DS4 launches that put the
  distributed data plane on Wi-Fi.

## What Did Not Work

- The custom MTP implementation should remain paused as a speed path. It had
  high acceptance but paid target eval / output head cost almost token-for-token.
  The core lesson is still useful: MTP only helps if verification is cheaper
  than serial target decoding.
- PP=3 on Wi-Fi should not be used as a comparison point. It is a network
  configuration failure, not a model/runtime conclusion.
- PP=4 did not beat PP=2 for the short-output batch benchmark. Before trying
  PP=8, prefer multiple PP=2 replicas or data-parallel lanes unless the goal is
  memory residency or multi-tenancy headroom rather than per-lane throughput.

## Runtime Map

### vLLM

vLLM is the current measured standard serving lane. Use it for the next
provider-facing DS4 batch service pass.

The upstream vLLM recipe identifies DeepSeek-V4-Flash as a compact
284B-total / 13B-active V4 sibling with FP4+FP8 weights and MTP support:

- `https://recipes.vllm.ai/deepseek-ai/DeepSeek-V4-Flash`
- `https://docs.vllm.ai/en/latest/api/vllm/models/deepseek_v4/nvidia/mtp/`

Repo status:

- Batch lane measured: yes.
- MTP measured on the same stable vLLM stack: no.
- Selected role: standard batch provider lane now; MTP single-query lane later.

### SGLang

SGLang is a separate serving runtime, not a wrapper around vLLM. It has
DeepSeek-V4-specific deployment recipes and tuning knobs.

The SGLang docs describe three DeepSeek-V4 serving profiles:
`low-latency`, `balanced`, and `max-throughput`, with MTP enabled for the first
two and disabled for max-throughput saturation.

- `https://docs.sglang.io/cookbook/autoregressive/DeepSeek/DeepSeek-V4`

Repo status:

- Batch lane measured on Sparks: no.
- Useful next experiment: A/B against the vLLM PP=2 lane only if it can use the
  same model identity, same 200G fabric discipline, and comparable output shape.
- Selected role: alternative standard runtime to test later, especially for
  low-latency MTP and DeepSeek-specific MoE/dispatch recipes.

### llama.cpp

llama.cpp is the local/GGUF/reference lane. It is useful for format conversion,
single-node/local experiments, speculative-decoding ideas, and no-Python
deployment comparisons.

As of this pause note, upstream llama.cpp has merged generic MTP support in a
recent release stream, while DeepSeek-V4 support itself is still tracked through
open issues, discussions, and community forks.

- `https://github.com/ggml-org/llama.cpp/issues/22319`
- `https://github.com/ggml-org/llama.cpp/discussions/22376`
- `https://newreleases.io/project/github/ggml-org/llama.cpp/release/b9180`

Repo status:

- Main high-throughput Spark provider lane: no.
- DeepSeek-V4-Flash support in this repo is tracked through pinned forks and
  GGUF metadata in `docs/upstream-llama-cpp.md`.
- Selected role: reference/runtime comparison, not the current batch provider.

### antirez / custom DS4

The antirez/custom DS4 path is the research and low-level implementation lane.
It taught the repo useful execution lessons: slice-tile8, candidate-only
structured-output scoring, model-contract checks, and verifier economics.

Repo status:

- Useful as a source of ideas and correctness probes.
- Not selected as the standard serving lane while vLLM gives stable PP=2
  provider throughput with less custom runtime risk.

## Next Experiments When Work Resumes

1. Reproduce the selected PP=2 direct-200G c256 lane before changing anything.
2. Run same-stack vLLM no-MTP vs vLLM MTP K=2 for single-query latency. Do not
   mix MTP claims into the batch-provider lane until the same-stack baseline is
   recorded.
3. Test SGLang on the same 200G discipline and the same output shape. Compare
   `low-latency`, `balanced`, and `max-throughput` profiles rather than a single
   default launch.
4. For higher aggregate throughput, test multiple PP=2 replicas before PP=8.
   PP=4 already showed that deeper pipeline parallelism alone did not improve
   short-output throughput.
5. For constrained outputs, measure candidate-only scoring explicitly. Token
   masking alone should not be counted as a speed optimization.
6. If revisiting custom kernels, quantify MoE time and expert dispatch
   utilization before implementing queueing changes.

## Artifact Index

Selected summary artifacts:

- `fixtures/vllm_config_tuning/vllm_deepseek_v4_flash_pp2_200g_no_mtp_20260522.example.json`
- `fixtures/vllm_config_tuning/vllm_deepseek_v4_flash_pp4_ring_no_mtp_20260522.example.json`

Raw PP=2 artifacts:

- `fixtures/vllm_config_tuning/ds4_vllm_pp2_spark45_200g_no_mtp_c1_32_64tok_20260522.raw.json`
- `fixtures/vllm_config_tuning/ds4_vllm_pp2_spark45_200g_no_mtp_c64_128_64tok_20260522.raw.json`
- `fixtures/vllm_config_tuning/ds4_vllm_pp2_spark45_200g_no_mtp_c256_64tok_20260522.raw.json`
- `fixtures/vllm_config_tuning/ds4_vllm_pp2_spark45_200g_no_mtp_c512_64tok_20260522.raw.json`

Raw PP=4 artifact:

- `fixtures/vllm_config_tuning/ds4_vllm_pp4_spark3456_200g_no_mtp_c1_512_64tok_20260522.raw.json`

Rejected PP=3 Wi-Fi artifacts:

- `fixtures/vllm_config_tuning/ds4_vllm_pp3_spark345_no_mtp_c1_16_64tok_20260522.raw.json`
- `fixtures/vllm_config_tuning/ds4_vllm_pp3_spark345_no_mtp_c32_128_64tok_20260522.raw.json`

Related runtime references:

- `docs/upstream-vllm-transformers.md`
- `docs/upstream-sglang.md`
- `docs/upstream-llama-cpp.md`
- `docs/upstream-ds4.md`
- `docs/model-deepseek-v4-flash.md`
