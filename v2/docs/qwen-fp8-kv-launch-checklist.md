# Qwen FP8 KV Launch Checklist

Qwen production launches must use explicit FP8 KV cache. Do not rely on vLLM
auto dtype or shell defaults when benchmarking capacity or throughput.

Required launch args:

```text
--kv-cache-dtype fp8
--attention-backend TRITON_ATTN
```

Do not use `FLASH_ATTN` with FP8 KV unless that path is revalidated for the
current vLLM build.

After launch, verify the live process on the vLLM entry node:

```bash
pid="$(pgrep -f 'vllm.*qwen' | head -1)"
tr '\0' ' ' < "/proc/$pid/cmdline" | grep -o -- '--kv-cache-dtype [^ ]*' || echo 'ERROR: no explicit --kv-cache-dtype'
```

Expected output:

```text
--kv-cache-dtype fp8
```

If the grep prints nothing, the launch is invalid.

Qwen external KV cache roots must be dtype-namespaced before measurement, for
example:

```text
qwen27_bf16_pp8_fp8kv
qwen27_nvfp4_pp8_fp8kv
qwen27_fp8kv
```

Do not compare FP8-KV measurements against old cache directories that may have
been populated with BF16 or implicit auto KV cache state.

Run the static audit before benchmark or deploy:

```bash
PYTHONPATH=src python3 scripts/ds4_qwen_fp8_kv_audit.py
```

Benchmark artifacts for Qwen must record:

```text
model
weight dtype or quantization
kv-cache-dtype
attention backend
max_num_seqs
max_num_batched_tokens
kv_cache_memory_bytes
LMCache on/off
MTP/spec on/off
```
