# Antirez DS4 MTP Q4 sidecar breakthrough

Date: 2026-05-12
Host: Spark0 (`aitopatom-9ab9`)
Runtime: `antirez/ds4` at `3630e64ea2aadb4d069a30dc3369f2b2950d6cb3`, locally patched

## Summary

The current antirez runtime can parse and bind the DeepSeek V4 Flash MTP sidecar, but the stock CUDA path did not produce usable draft tokens on Spark0.

The first probe loaded the sidecar and then failed every draft:

```text
ds4: MTP support model loaded: ...DeepSeek-V4-Flash-MTP-Q4K-Q8_0-F32.gguf (draft=2)
ds4: mtp draft failed stage=decode_layer pos=12 raw_row=12 n_raw=1 mtp_n_raw=0
```

Instrumentation localized the failure to the sidecar layer's routed MoE. The sidecar contract probe shows all three routed expert tensors are `Q4_K`:

```text
mtp.0.ffn_gate_exps.weight Q4_K [4096, 2048, 256]
mtp.0.ffn_up_exps.weight   Q4_K [4096, 2048, 256]
mtp.0.ffn_down_exps.weight Q4_K [2048, 4096, 256]
```

The stock CUDA routed-MoE launcher only accepted trunk-style `IQ2_XXS` gate/up plus `Q2_K` down, so the MTP sidecar was structurally loaded but not executable.

## Local Patches

Two experimental patches were applied on Spark0:

- [ds4-cuda-mtp-q4-sidecar.patch](antirez-patches/ds4-cuda-mtp-q4-sidecar.patch): adds a scalar CUDA `Q4_K` routed-MoE fallback and prevents the trunk model fd/device-owned shortcut from being used for non-trunk `model_map` pointers.
- [ds4-mtp-sidecar-lazy-map.patch](antirez-patches/ds4-mtp-sidecar-lazy-map.patch): keeps the trunk model as the CUDA cache owner and lets MTP sidecar tensors be copied lazily from their own mmap. This avoids the current single-global model cache mixing the trunk fd with MTP tensor offsets.

This is not the final performance path. The `Q4_K` fallback is intentionally simple and is only meant to prove the MTP execution path.

## Result

After the patches, MTP draft execution no longer fails and the draft logits are finite:

```text
ds4: CUDA cached moe_gate 1152.00 MiB
ds4: CUDA cached moe_up 1152.00 MiB
ds4: CUDA cached moe_down 1152.00 MiB
ds4: mtp spec miss first draft=344 mtp_top0=344 mtp_v0=27.679432 mtp_top1=28010 mtp_v1=26.611919 target_top=30700
```

So the blocker moved from "MTP cannot execute" to "MTP executes but the first sampled draft did not match the trunk verifier." That is progress: we now have finite draft logits and a concrete acceptance-quality target.

The run's low generation rate is not meaningful yet because it includes first-use sidecar tensor caching. The local patch copies roughly 3.4 GiB of `Q4_K` MTP routed experts on first draft.

## Next Gates

1. Validate the new CUDA `Q4_K` dot path against ggml/llama.cpp `q4_K x q8_K` on a small row fixture.
2. Add a real multi-model CUDA weight cache keyed by `(model_map, fd, offset)`, rather than one global trunk fd.
3. Compare MTP intermediate tensors against a CPU or llama.cpp reference for `e_proj`, `h_proj`, MTP attention, routed MoE, and head logits.
4. Once first-token draft agreement is plausible, run an acceptance sweep with `--mtp-draft 2`, strict verifier enabled, and fixed prompts.
5. Only after correctness is established, replace the scalar `Q4_K` fallback with a q8-activation/tiled path.
