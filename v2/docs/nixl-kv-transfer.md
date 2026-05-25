# DS4 NIXL KV Transfer

DS4 treats NIXL as a Spark-side vLLM capability. Centaur and the DS4 queue still send normal OpenAI-compatible inference requests; the proxy fans each request through a prefiller and decoder and carries `kv_transfer_params` between them.

The first experimental lane is pinned-only Qwen 27B on spark7:

```bash
PYTHONPATH=v2/src python3 -m ds4_nixl.cli plan \
  --deployment v2/profiles/nixl/qwen27_spark7_nixl.json

PYTHONPATH=v2/src python3 -m ds4_nixl.cli write-scripts \
  --deployment v2/profiles/nixl/qwen27_spark7_nixl.json \
  --output-dir /tmp/ds4_nixl_qwen27
```

The generated scripts start:

```text
spark7: Qwen 27B prefiller on 8110
spark7: Qwen 27B decoder on 8120
spark7: DS4 NIXL proxy on 8192
```

Live Spark7 status on 2026-05-25:

```text
Qwen27 model load: succeeds
NIXL package import: succeeds after forcing nixl-cu13 in the vLLM runtime
FlashInfer JIT: succeeds when the vLLM env bin directory is on PATH
Hybrid KV setup: requires --no-disable-hybrid-kv-cache-manager
Qwen SSM layout: requires VLLM_SSM_CONV_STATE_LAYOUT=DS
Serving status: blocked before /health
```

The current blocker is in vLLM 0.21's NIXL worker, not DS4 routing. After Qwen27 reaches NIXL initialization, vLLM raises:

```text
NotImplementedError: 3-read conv transfer only supports Mamba2 models, got mamba_type=<MambaAttentionBackendEnum.GDN_ATTN: 'vllm.v1.attention.backends.gdn_attn.GDNAttentionBackend'>.
```

Keep this lane pinned-only until either the Spark runtime supports NIXL transfer for the Qwen3.6 GDN/Mamba path, or the experimental lane is moved to a NIXL-compatible model.

Use the lane only by pinning the profile:

```json
{
  "model_pin": {
    "profile_id": "qwen3_6_27b_fp8_nixl_experimental_v1"
  }
}
```

For direct runner tests:

```bash
export DS4_NIXL_BASE_URL=http://spark7:8192
PYTHONPATH=v2/src python3 -m ds4_infer.cli submit \
  --profiles-dir v2/profiles/models \
  --requests requests.jsonl \
  --out /tmp/ds4_nixl_submit \
  --runner nixl \
  --run
```

The proxy is intentionally small: it sends a one-token prefiller request with `do_remote_decode=true`, copies the returned `kv_transfer_params`, then streams the real request from the decoder. DS4 does not expose raw KV tensors.
