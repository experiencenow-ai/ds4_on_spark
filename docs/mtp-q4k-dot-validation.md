# Q4_K dot-math validation (MTP sidecar)

This repo carries experimental CUDA patch notes for running the DeepSeek V4 Flash MTP sidecar (`Q4_K`) on Spark via the antirez runtime.

The current workaround patch includes a scalar CUDA `Q4_K` routed-MoE fallback. Before treating any draft-token quality failures as “model-side”, validate that the Q4_K dequant + dot path is internally self-consistent and finite on real sidecar bytes.

## 1) Fetch a tiny payload sample (no full download)

This downloads only the GGUF header + tensor directory and range-reads the first 144 bytes of each tensor payload.

```sh
python3 scripts/model_contract_probe_mtp_sidecar.py \
  --url 'https://huggingface.co/antirez/deepseek-v4-gguf/resolve/c566ab6d7c696ddd0c7f124e115228af1a326824/DeepSeek-V4-Flash-MTP-Q4K-Q8_0-F32.gguf' \
  --json \
  --payload-sample-bytes 144 \
  --payload-sample-include-bytes \
  > /private/tmp/mtp_sidecar_probe_144.json
```

## 2) Decode the first `Q4_K` block and verify dot math

This extracts the first `block_q4_K` (144 bytes) from the chosen tensor payload sample and computes the dot product against a deterministic `x[256]` vector in two ways (streaming vs dequantize-then-dot).

```sh
python3 scripts/verify_q4k_dot_math.py \
  --probe-json /private/tmp/mtp_sidecar_probe_144.json \
  --tensor mtp.0.ffn_gate_exps.weight \
  --x-seed 1 \
  --json
```

Expected: `ok=true`, `dot_ref` and `dot_stream` are finite, and the error is ~0.

## Notes

- This is a *local* correctness gate for the `Q4_K` unpacking and dot loop shape, not a full CUDA-vs-CPU oracle.
- For the Spark0 breakthrough context, see `docs/mtp-antirez-q4-sidecar-breakthrough-2026-05-12.md`.

