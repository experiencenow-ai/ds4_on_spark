# DS4 External MTP Runtime Bench

Status: standard vLLM release is installed on Spark0/Spark1/Spark2 and the
DeepSeek-V4-Flash HF checkpoint is staged, but no external DS4 MTP speed result
exists because the standard checkpoint still cannot complete vLLM startup on
the available GB10 topology.

Run: `ds4-external-mtp-runtime-bench-spark0-20260517`

Artifact: `fixtures/external_mtp_runtime_bench/ds4_external_mtp_runtime_bench_spark0_20260517.example.json`

Latest Spark1/Spark2 readiness run:
`ds4-external-mtp-runtime-bench-spark12-vllm-readiness-20260518`

Artifact:
`fixtures/external_mtp_runtime_bench/ds4_external_mtp_runtime_bench_spark12_vllm_readiness_20260518.example.json`

Latest Spark1/Spark2 staged-checkpoint run:
`ds4-external-mtp-runtime-bench-spark12-vllm-staged-load-20260518`

Artifact:
`fixtures/external_mtp_runtime_bench/ds4_external_mtp_runtime_bench_spark12_vllm_staged_load_20260518.example.json`

Latest Spark0/Spark1/Spark2 PP=3 run:
`ds4-external-mtp-runtime-bench-spark012-vllm-pp3-20260518`

Artifact:
`fixtures/external_mtp_runtime_bench/ds4_external_mtp_runtime_bench_spark012_vllm_pp3_20260518.example.json`

Latest PP=3 safetensors load-filter audit:
`ds4-vllm-pp3-safetensors-filter-spark1-20260519`

Artifact:
`fixtures/vllm_pp_safetensors_filter/ds4_vllm_pp3_safetensors_filter_spark1_20260519.example.json`

Latest patched two-Spark control:
`ds4-vllm-pp2-probe-20260519`

Artifact:
`fixtures/vllm_pp_runtime_probe/ds4_vllm_pp2_probe_20260519.example.json`

Latest patched three-Spark PP=3 OOM repro:
`ds4-vllm-pp3-probe-gpumem045-monitor-off-20260519`

Artifact:
`fixtures/vllm_pp_runtime_probe/ds4_vllm_pp3_probe_gpumem045_monitor_off_20260519.example.json`

Latest patched three-Spark PP=3 memory-lifecycle run:
`ds4-vllm-pp3-layerwise-paramrefs-sm121-mhc-tiny-20260519`

Artifact:
`fixtures/vllm_pp_runtime_probe/ds4_vllm_pp3_layerwise_paramrefs_sm121_mhc_tiny_20260519.example.json`

## Result

| Runtime | DS4 MTP result | Blocker |
| --- | --- | --- |
| llama.cpp | failed before generation | Upstream MTP build exposes `--spec-type draft-mtp`, but cannot load the DS4 GGUF: `unknown model architecture: 'deepseek4'`. Latest upstream has MTP code but no `deepseek4`; the DS4 fork has `deepseek4` but not the upstream MTP runtime. |
| SGLang | not run | Spark1/Spark2 Docker access is permission-denied for the Spark users and SGLang is not installed. Official DeepSeek-V4-Flash recipes document multi-GPU Blackwell deployments for the unmodified checkpoint; keep SGLang as a candidate only after the standard checkpoint has enough memory headroom. |
| vLLM | checkpoint staged, benchmark blocked | Upstream vLLM `0.21.0` imports on Spark0/Spark1/Spark2 with Torch `2.11.0+cu130`, exposes `DeepseekV4ForCausalLM` and `DeepSeekV4MTPModel`, and Ray `2.54.0` sees `GPU=3.0`. PP=3 over the Wi-Fi control plane with `VLLM_PP_LAYER_PARTITION=14,15,14`, `kv_cache_dtype=fp8`, and reduced Ray object store reaches model load but does not reach token generation. With 8 GiB object stores, PP0 and PP2 loaded while Spark1 PP1 stalled at about `121 GiB` used and `700 MiB` free. With 1 GiB object stores, PP1 finished weight load, then Spark1 again reached about `121 GiB` used and `697 MiB` free before final engine startup. No target-only baseline or MTP TPS was produced. |

## Memory Load Audit

The PP=3 failure is now isolated to the loader path, not to the static model
size. Header-only safetensors accounting on the staged checkpoint shows Spark1
rank 1 owns about `53.70 GiB` of layer tensors for the `[14,29)` partition, but
the current vLLM safetensors iterator materializes tensors before
`DeepseekV4ForCausalLM` can reject PP-missing layers or MTP tensors. For rank 1,
that means about `96.66 GiB` of avoidable tensor payload is touched before the
later skip logic runs. Rank 0 and rank 2 each have about `100 GiB` of avoidable
payload by the same conservative count.

Repo-owned patch artifact:
`docs/vllm-patches/ds4-deepseek-v4-pp-safetensors-early-filter.patch`

The patch adds a raw weight-name predicate to
`safetensors_weights_iterator(...)` and lets `DeepseekV4ForCausalLM` map HF
names to vLLM names, reject `mtp.` tensors, and reject PP-missing parameters
before `safe_open(...).get_tensor(name)`.

## Patched Runtime Probe

The vLLM early-filter patch was applied to Spark0/Spark1/Spark2 runtime copies
under `/home/spark*/standard-runtimes/vllm-0.21.0`. Ray 2.54 also needed a
probe-only startup patch to skip Ray Client and dashboard/API-server startup
before raylet creation; without it the head process stalled before raylet.

Spark1/Spark2 then formed a healthy two-node Ray cluster on `10.20.0.11/12`.
A PP=2 control with `VLLM_PP_LAYER_PARTITION=22,21` reached checkpoint loading
and showed the memory drop expected from early filtering, but still failed after
load because 22/21 layers leave too little headroom on 128 GB nodes. Ray killed
the worker at `121.63 GiB / 121.69 GiB` used. This makes PP=2 close but not a
stable standard-vLLM topology.

After Spark0 reboot, all three Sparks formed a healthy Ray cluster and PP=3 with
`VLLM_PP_LAYER_PARTITION=14,15,14` reached per-stage model loading. The 14-layer
PP0 and PP2 stages reported about `48 GiB` model memory, but the 15-layer PP1
stage was killed during model initialization. This reproduced with Ray's memory
monitor enabled, with the monitor disabled, with `gpu_memory_utilization=0.45`,
and with a tiny decode config (`max_model_len=64`, `max_num_batched_tokens=64`,
`gpu_memory_utilization=0.20`). Spark2's kernel log confirmed the hard failure:
`Out of memory: Killed process ... ray::RayWorkerP` plus an NVIDIA `NVRM`
allocation/copy-out failure.

The 15-layer PP stage OOM was fixed by finalizing MXFP4 MoE layers as soon as
each layer's local experts are loaded and by deleting stale `params_dict`
references to pre-conversion `layers.N.ffn.experts.*` parameters after each
layer is converted. Without deleting those references, the per-layer conversion
still retained old loaded tensors until `load_weights()` returned. With both
fixes applied, PP=3 `[14,15,14]` reached model load on all ranks:
PP0 `48.14 GiB`, PP1 `50.28 GiB`, PP2 `47.92 GiB`.

The remaining blocker is after model load, during vLLM's
`determine_available_memory()` dummy-forward/profile path. The failing stack is
DeepSeek-V4 attention `fused_wqa_wkv` to `cutlass_scaled_mm`, ending in
`Not yet supported ScalarType 44` from Torch stable IValue conversion. This is
not the previous PP1 model-load OOM.

## Decision

Do not switch to upstream vLLM on the current Spark0/Spark1/Spark2 topology yet.
This is not a throughput result and must not be treated as MTP speedup evidence.

Exact next unblocks:

1. Fix or bypass the standard-vLLM dummy-forward/profile path where
   `fused_wqa_wkv` calls `cutlass_scaled_mm` with `ScalarType 44` after model
   load.
2. Start Ray with explicit 10G binding:
   `GLOO_SOCKET_IFNAME`, `NCCL_SOCKET_IFNAME`, `NCCL_IB_DISABLE=1`,
   `NCCL_P2P_DISABLE=1`, and `NCCL_SOCKET_FAMILY=AF_INET`.
3. Rerun PP=3 target-only with `VLLM_PP_LAYER_PARTITION=14,15,14`, or PP=4 if a
   fourth Spark is available, then MTP with
   `--speculative-config '{"method":"mtp","num_speculative_tokens":1}'`.
4. Record baseline t/s, MTP t/s, acceptance counters, and blocker detail in the
   external runtime artifact before making any routing decision.
