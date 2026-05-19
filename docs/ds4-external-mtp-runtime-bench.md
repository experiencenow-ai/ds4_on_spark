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

## Decision

Do not switch to upstream vLLM on the current Spark0/Spark1/Spark2 topology yet.
This is not a throughput result and must not be treated as MTP speedup evidence.

Exact next unblocks:

1. Apply the safetensors early-filter patch to the Spark vLLM install, then
   rerun PP=3. The measured blocker is current loader materialization of
   PP-missing layer tensors, not the static 15-layer shard itself.
2. Start Ray with explicit ring binding:
   `GLOO_SOCKET_IFNAME`, `NCCL_SOCKET_IFNAME`, `NCCL_IB_DISABLE=1`,
   `NCCL_P2P_DISABLE=1`, and `NCCL_SOCKET_FAMILY=AF_INET`.
3. Run vLLM target-only, then MTP with
   `--speculative-config '{"method":"mtp","num_speculative_tokens":1}'`.
4. Record baseline t/s, MTP t/s, acceptance counters, and blocker detail in the
   external runtime artifact before making any routing decision.
