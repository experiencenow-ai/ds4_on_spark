---
title: "antirez/ds4 CUDA: Q4_K MTP sidecar breakthrough (2026-05-12)"
---

# antirez/ds4 CUDA: Q4_K MTP sidecar breakthrough (2026-05-12)

Goal: make the `antirez/deepseek-v4-gguf` DeepSeek V4 Flash MTP sidecar usable on the Spark/Linux CUDA path, using `antirez/ds4` as the concrete execution reference.

## Spark0 finding

Runtime:

- Host: Spark0 (`aitopatom-9ab9`)
- `antirez/ds4`: `3630e64ea2aadb4d069a30dc3369f2b2950d6cb3`
- Trunk: `DeepSeek-V4-Flash-IQ2XXS-w2Q2K-AProjQ8-SExpQ8-OutQ8-chat-v2-imatrix.gguf`
- Sidecar: `DeepSeek-V4-Flash-MTP-Q4K-Q8_0-F32.gguf`

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

## Patch stack

This repo ships patches against `antirez/ds4@3630e64` that address the immediate CUDA blockers:

1. `docs/antirez-patches/ds4-3630e64-cuda-mtp-q4k-and-sidecar-map.patch`
   - adds a diagnostic `Q4_K` routed-MoE fallback
   - prevents the secondary MTP model map from clobbering the trunk CUDA map owner
2. `docs/antirez-patches/ds4-3630e64-cuda-multi-model-cache.patch`
   - keys cached CUDA ranges by model identity rather than offset alone
   - avoids trunk/sidecar cache aliasing under CUDA weight caching
3. `docs/antirez-patches/ds4-3630e64-mtp-one-token-json-probe.patch`
   - adds `--dump-mtp-one-token-json`
   - emits oracle-compatible MTP one-token draft fingerprints

Older experimental Spark0 patches are retained for provenance:

- `docs/antirez-patches/ds4-cuda-mtp-q4-sidecar.patch`
- `docs/antirez-patches/ds4-mtp-sidecar-lazy-map.patch`

## Result

After the experimental Spark0 patches, MTP draft execution no longer fails and the draft logits are finite:

```text
ds4: CUDA cached moe_gate 1152.00 MiB
ds4: CUDA cached moe_up 1152.00 MiB
ds4: CUDA cached moe_down 1152.00 MiB
ds4: mtp spec miss first draft=344 mtp_top0=344 mtp_v0=27.679432 mtp_top1=28010 mtp_v1=26.611919 target_top=30700
```

The blocker moved from "MTP cannot execute" to "MTP executes but first-draft agreement is not established." The low generation rate in that run is not meaningful because it includes first-use sidecar tensor caching of roughly 3.4 GiB of `Q4_K` routed experts.

## Math validation

The Q4_K fallback must be validated before performance work matters. This branch includes CPU-only checks grounded in ggml/llama.cpp behavior:

- `scripts/verify_antirez_ds4_q4k_dot_math.py`
- `fixtures/quant/q4k_llamacpp_b9110_rowdot_fixture.json`
- `tests/q4k_llamacpp_fixture_test.py`

Run:

```bash
python3 scripts/verify_antirez_ds4_q4k_dot_math.py
python3 -m unittest tests/q4k_llamacpp_fixture_test.py
```

## Oracle path

Finite logits are not enough. The next correctness gate is a one-token MTP oracle that can diff intermediate fingerprints before acceptance sweeps.

Spark oracle runner:

```bash
REMOTE_ANTIREZ_DS4_MTP_ORACLE_ENV="ALLOW_FETCH=1 ALLOW_PATCH=1 ALLOW_BUILD=1 ALLOW_RUN=1" \
scripts/run_antirez_ds4_mtp_one_token_oracle_probe_spark.sh spark0@<spark-host>
```

Diff oracle vs candidate:

```bash
python3 scripts/diff_mtp_one_token_draft_probe.py --a /path/to/oracle_probe.json --b /path/to/candidate_probe.json --json
```

Convenience wrapper (oracle + candidate + diff in one command; all Spark work remains gated):

```bash
scripts/run_mtp_one_token_oracle_vs_candidate_diff_spark.sh spark0@<spark-host>
```

## Remaining gates

1. Build and run the patched antirez oracle on Spark0.
2. Add matching one-token MTP captures to the candidate runtime.
3. Diff `e_proj`, `h_proj`, MTP attention, routed MoE, head norm, and logits fingerprints.
4. Once first-token agreement is plausible, run an acceptance sweep with `--mtp-draft 2`, strict verifier enabled, and fixed prompts.
5. Replace the diagnostic `Q4_K` fallback with a tiled/q8-activation CUDA path only after correctness is locked.
