# DS4 External MTP Runtime Bench

Status: standard vLLM release is installed on Spark1/Spark2 and the
DeepSeek-V4-Flash HF checkpoint is staged, but no external DS4 MTP speed result
exists because the standard checkpoint cannot complete vLLM startup on two GB10s.

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

## Result

| Runtime | DS4 MTP result | Blocker |
| --- | --- | --- |
| llama.cpp | failed before generation | Upstream MTP build exposes `--spec-type draft-mtp`, but cannot load the DS4 GGUF: `unknown model architecture: 'deepseek4'`. Latest upstream has MTP code but no `deepseek4`; the DS4 fork has `deepseek4` but not the upstream MTP runtime. |
| SGLang | not run | Spark1/Spark2 Docker access is permission-denied for the Spark users and SGLang is not installed. Official DeepSeek-V4-Flash recipes document multi-GPU Blackwell deployments for the unmodified checkpoint; keep SGLang as a candidate only after the standard checkpoint has enough memory headroom. |
| vLLM | checkpoint staged, benchmark blocked | Upstream vLLM `0.21.0` installs on both Spark1 and Spark2, imports with Torch `2.11.0+cu130`, exposes `DeepseekV4ForCausalLM` and `DeepSeekV4MTPModel`, Ray `2.54.0` over `10.10.5.1`/`10.10.5.2` sees `GPU=2.0`, and the full HF checkpoint is staged on Spark0/1/2. TP=2 required explicit ring socket binding, `kv_cache_dtype=fp8`, and reduced KV reservation, then reached 38/46 shards before Ray killed Spark2 at `118.76/119.69 GiB`. PP=2 loaded 46/46 shards but Ray killed Spark1 at `121.43/121.69 GiB` before engine startup completed. |

## Decision

Do not switch to upstream vLLM on Spark1/Spark2 yet. This is not a throughput
result and must not be treated as MTP speedup evidence.

Exact next unblocks:

1. Use a standard-runtime topology with more memory headroom for the unmodified
   HF checkpoint, likely the official multi-GB10/Blackwell shape, or use a
   smaller/converted checkpoint that can complete startup on two GB10s.
2. Start Ray with explicit ring binding:
   `GLOO_SOCKET_IFNAME`, `NCCL_SOCKET_IFNAME`, `NCCL_IB_DISABLE=1`,
   `NCCL_P2P_DISABLE=1`, and `NCCL_SOCKET_FAMILY=AF_INET`.
3. Run vLLM target-only, then MTP with
   `--speculative-config '{"method":"mtp","num_speculative_tokens":1}'`.
4. Record baseline t/s, MTP t/s, acceptance counters, and blocker detail in the
   external runtime artifact before making any routing decision.
