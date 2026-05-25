# LLM runners

The live inference runners are intentionally thin adapters behind the DS4 request contract.

## Runner choices

```bash
ds4-infer submit --runner fake    ...
ds4-infer submit --runner vllm    ...
ds4-infer submit --runner antirez ...
ds4-infer submit --runner auto    ...

ds4-infer queue-work --runner auto --node-id spark0 ...
```

`auto` routes by the selected model profile backend:

- `vllm` and `vllm_mtp` use the OpenAI-compatible `/v1/chat/completions` or `/v1/completions` endpoints.
- `antirez` uses a completion-style `/completion` endpoint.

The xhigh should set the endpoint environment on each resident lane:

```bash
export DS4_VLLM_BASE_URL=http://127.0.0.1:8000
export DS4_VLLM_MTP_BASE_URL=http://spark4:8000
export DS4_ANTIREZ_BASE_URL=http://127.0.0.1:8080
```

The first live validation must exercise `--runner vllm` on every resident Qwen lane, `--runner vllm` on the spark4+spark5 MTP lane, and `--runner antirez` on spark6. See `docs/xhigh-live-validation.md`.

The runner code is best-effort because the real endpoints are not reachable from the sandbox. The queue contract should not change when endpoint details are corrected.
