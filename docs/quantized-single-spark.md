# Quantized Single-Spark Milestone

Goal: get DeepSeek V4 Flash producing tokens on **one** Spark before the native
DS4 runtime and dual-Spark TP path are ready.

This is the first gate for the broader quantized high-performance path described
in `docs/quantized-performance-path.md`. A slow or low-quality first token
stream is useful if it proves the model artifact, runtime, CUDA path,
tokenizer/chat format, and memory envelope are real.

Latest successful Spark0 run (tokens produced): `docs/baseline-quantized-single-spark0-2026-05-11.md`.

## Definition of Done

- One Spark0 command produces non-empty generated text from a V4 Flash-family
  quantized artifact.
- The run records exact runtime source, runtime commit, model source, quant,
  file size, sha256, command line, context length, token count, TTFT, tokens/sec
  where available, GPU memory snapshot, CPU RSS, stdout, stderr, and exit code.
- The run preserves the baseline-summary key/value block (so `decode_tps`,
  `total_wall_s`, and `output_tokens` are recoverable for later scoring), plus
  the read-only patch probes when enabled (`LLAMA_FATTN_PATCH_PROBE=1`,
  `LLAMA_MULTISLOT_PATCH_PROBE=1`) so the report says whether the runtime likely
  contains the FA pad-to-256 reservation fix and the multi-slot reserve/SWA fixes.
- Note the upstream reference defaults are `max_seq_len=4096` and `max_batch_size=4`, but any external runtime may choose different values; record the actual context/window settings used.
- The report records whether the artifact preserves the upstream MTP namespace
  (`mtp.0.*`) and whether MTP was enabled/disabled for the run (see “MTP / tensor-key compatibility” below).
- The report includes `scripts/model_contract_inspect_quantized_artifact.py --json` output for the tested artifact (at minimum: `metadata.general.*`, `tensor_type_counts`, and `mtp_tensor_type_counts` when present).
  - Always record `weight_keys_sha256` (stable fingerprint of the artifact’s tensor key set). When `mtp_present=true`, also record `mtp_keys_sha256` (stable fingerprint of the `mtp.*` subset).
  - When available, also record `tensor_type_profile` (best-effort expert vs dense split for known DeepSeek-V4 GGUF naming), since it captures whether MoE experts appear to be `MXFP4` (Flash-leaning) vs primarily FP8.
  - When available, also record `quantization_contract` (contract-aware “Flash native FP8/FP4-like?” hint derived from `tensor_type_profile` vs `fixtures/model_contract/deepseek_v4_flash/contract_summary.json` `quantization.inference_config`).
  - When the repo-default `fixtures/model_contract/deepseek_v4_flash/contract_summary.json` is available, this output also includes:
    - `tensor_key_namespace_guess` + `first_tensor_keys` (quick signal for whether the artifact appears to preserve upstream tensor key namespaces; many GGUF conversions are `llama.cpp`)
    - `trunk_contract` (structural trunk tensor-key completeness; interpret via `trunk_contract.kind`):
      - `kind="deepseek-upstream"` checks `layers.{i}.*` (only applies if the artifact preserves upstream tensor names)
      - `kind="llama.cpp"` checks `blk.{i}.*` (compat-only structural signal for DeepSeek4 GGUFs)
    - `mtp_contract` (upstream tensor-key completeness for `mtp.{j}.*` when present)
    - `mtp_preservation` (structural “preserves upstream `mtp.0.*`?” status derived from `mtp_namespace` + `mtp_contract`)
    - `mtp_trust` (structural “complete vs incomplete” status derived from the upstream MTP contract + explicit trust gates; still requires a logits oracle before enabling MTP)
    - `topology_contract` (GGUF header metadata vs expected `hidden_size`, `block_count`, head counts, vocab size, and (when present) RoPE `dimension_count` / `freq_base`)
    - For trunk+sidecar inspections (multiple `--path`), the JSON includes both per-artifact and `combined.*` summaries; use `combined.topology_contract_source_path` to see which GGUF header was used for the combined topology check.
      - For artifact sets, also record `combined.weight_keys_union_sha256` and (when present) `combined.mtp_keys_union_sha256` to fingerprint the union key set across trunk + sidecar inputs.
- If the run fails, the report preserves the exact failure mode: unsupported
  architecture, unsupported GGUF type, OOM, CUDA kernel failure, tokenizer/chat
  mismatch, or runtime crash.
- No automation downloads large model files unless a human explicitly approves
  the exact command and target path.

### Inspector wiring (Mac → Spark)

`scripts/run_baseline_existing_runtime.sh` can run a metadata-only GGUF inspection
on Spark before the llama.cpp run:

- Set `ALLOW_MODEL_INSPECT=1` on Spark (via `REMOTE_LLAMA_ENV` or `REMOTE_GGUF_INSPECT_ENV`).
- Provide `MODEL_GGUF=/abs/path/to/model.gguf` (same as the llama.cpp run).

The inspector output is written into the local report directory as:

- `remote_gguf_inspect_stdout.txt` (JSON; full output)
- `remote_gguf_inspect_stderr.txt`

## Candidate Artifacts

As of 2026-05-10, the practical first target is a community GGUF using a
DeepSeek V4-capable llama.cpp fork or early-access runtime. Stock stable
llama.cpp should be treated as unproven for V4 Flash until verified.

| Candidate | Why it matters | First-use posture |
| --- | --- | --- |
| Q2_K GGUF | Smallest currently useful class for a single 128 GB unified-memory Spark. | Preferred first full-model smoke target if the runtime can load it. |
| Q3_K_M GGUF | Better quality but close to the single-Spark memory envelope. | Try after Q2_K, with small context and careful memory logging. |
| Native FP4/FP8 GGUF | Closest to the upstream checkpoint's native low-precision layout. | Use for loader/format validation; likely tight for a single Spark. |
| Official HF safetensors | Source of truth for native DS4 loader work. | Metadata only unless a human approves checkpoint download. |

For any community artifact, record provenance rather than trusting the model
card summary: HF repo, revision, file list, file sizes, sha256, declared base
model, declared license, required runtime fork, and any conversion command.

### Staged artifact discovery (no downloads)

If multiple V4 Flash GGUFs are already staged on Spark0, pick the smallest
credible one (usually `Q2_K`) for the first token-producing run.

No-download discovery commands (Mac → Spark0; metadata only):

```sh
ssh spark0@aitopatom-9ab9.local "ls -lh /home/spark0/models/ds4/*.gguf 2>/dev/null | sort -k5 -h"
```

If you want an exact byte count (better for comparing near-ties), prefer `wc -c`:

```sh
ssh spark0@aitopatom-9ab9.local "for f in /home/spark0/models/ds4/*.gguf; do [ -r \"$f\" ] || continue; wc -c \"$f\"; done | sort -n | head"
```

## MTP (multi-token prediction) expectations

DeepSeek V4 Flash’s official checkpoint includes an MTP module namespace (`mtp.0.*`).
Many derived artifacts (especially GGUF conversions) may drop it.

For each tested artifact, record:

- Whether `mtp.0.*` weights exist in the artifact.
- If MTP is missing: run with MTP disabled and treat the artifact as **next-token only**.
- If MTP is present: still treat it as **untrusted** until it is validated against an upstream logit oracle that exercises the MTP path (weights required).

Reference pages to inspect before choosing a fixture:

- `https://huggingface.co/Preyazz/DeepSeek-V4-Flash-GGUF`
- `https://huggingface.co/batiai/DeepSeek-V4-Flash-GGUF`
- `https://huggingface.co/nsparks/DeepSeek-V4-Flash-FP4-FP8-GGUF`
- `https://huggingface.co/models?other=base_model%3Aquantized%3Adeepseek-ai%2FDeepSeek-V4-Flash`

## MTP / tensor-key compatibility

DeepSeek V4 Flash includes a distinct MTP (multi-token prediction) module under
the `mtp.0.*` tensor namespace. Many conversion pipelines and some runtimes
silently drop unfamiliar tensor namespaces or ignore them at load time.

For each tested quantized artifact, record whether `mtp.0.*` is present:

```sh
python3 scripts/model_contract_inspect_quantized_artifact.py --path /abs/path/to/model.gguf
```

When running from this repo (or when `--contract-summary` points at `fixtures/model_contract/deepseek_v4_flash/contract_summary.json`), prefer the contract-aware structural gate:

```sh
python3 scripts/model_contract_inspect_quantized_artifact.py --path /abs/path/to/model.gguf --json --require-mtp-complete
```

For Hugging Face-hosted GGUFs, you can capture the same header/tensor-table metadata without downloading the full file (range reads only). Record the `url_prefix_bytes` from the JSON output:

```sh
python3 scripts/model_contract_inspect_quantized_artifact.py --url https://huggingface.co/<repo>/resolve/<rev>/<file>.gguf --json
```

Interpreting the result:

- If `mtp_present == false`, treat the artifact as **MTP-disabled** even if it
  generates text normally. Any runtime “speculative” or “draft” feature must be
  treated as untrusted unless it can be traced back to `mtp.0.*` weights.
- If `mtp_present == true`, the artifact is only **MTP-capable** if the runtime
  actually loads and uses those tensors. Still require correctness oracles
  before trusting MTP outputs.
- If `tensor_key_namespace_guess != deepseek-upstream`, assume the artifact does **not** preserve upstream tensor key namespaces by default. In that case:
- `trunk_contract.checked` is expected to be `true` for most DeepSeek4 GGUF conversions (`kind="llama.cpp"`), and `false` for arbitrary GGUFs that don’t follow the deepseek4 `blk.{i}.*` naming.
  - The absence of `mtp.0.*` keys (`mtp_present == false`) means upstream MTP preservation is *not* proven; treat MTP as disabled/untrusted.
- For GGUF, record `tensor_type_counts` (and `mtp_tensor_type_counts` when present) to capture the exact quant formats the runtime must support (e.g. `Q2_K`, `Q3_K`, `BF16`, `MXFP4`).
  - When available, also record `tensor_type_profile` so the report captures the expert-vs-dense quant split (useful for spotting Flash-leaning `MXFP4` experts in “native FP4/FP8” GGUFs).
  - If `topology_contract.checked == true` and `topology_contract.mismatches` is non-empty, treat the artifact as **suspect** (topology mismatch) until a human explains the discrepancy.

Observed metadata-only inspections (2026-05-10):

| Artifact URL (pinned) | `tensor_key_namespace_guess` | `mtp_present` | `url_prefix_bytes` | Recorded probe |
| --- | --- | --- | --- | --- |
| `https://huggingface.co/Preyazz/DeepSeek-V4-Flash-GGUF/resolve/6c6d74ce4efd3e1045c15e5823d75e62b6e4ba1d/DeepSeek-V4-Flash-Q4_K_M.gguf` | `llama.cpp` | `false` | `8388608` | `docs/gguf-inspect-preyazz-6c6d74c-q4-k-m.json` |
| `https://huggingface.co/nsparks/DeepSeek-V4-Flash-FP4-FP8-GGUF/resolve/0b34e0b629c706396002496e795e9f910f7bf69f/DeepSeek-V4-Flash-FP4-FP8-native.gguf` | `llama.cpp` | `false` | `8388608` | `docs/gguf-inspect-nsparks-0b34e0b-fp4-fp8-native.json` |
| `https://huggingface.co/antirez/deepseek-v4-gguf/resolve/b0c3326275d2207e25e42bc8ac0704952466b5bb/DeepSeek-V4-Flash-IQ2XXS-w2Q2K-AProjQ8-SExpQ8-OutQ8-chat-v2.gguf` | `llama.cpp` | `false` | `8388608` | `docs/gguf-inspect-antirez-b0c3326-iq2xxs-chat-v2.json` |

MTP sidecar example (metadata-only inspection; 2026-05-10):

- `antirez/deepseek-v4-gguf` `DeepSeek-V4-Flash-MTP-Q4K-Q8_0-F32.gguf` @ `b0c3326275d2207e25e42bc8ac0704952466b5bb`:
  - Recorded output: `docs/gguf-inspect-antirez-b0c3326-mtp-sidecar.json`
  - Summary: `mtp_present=true` and `tensor_key_namespace_guess=deepseek-upstream-mtp-only`, but `mtp_contract.complete=false` with `mtp_tensor_count=32` (compact DS4-tuned sidecar, not a full upstream `mtp.0.*` checkpoint).

To validate a sidecar that is already present on Spark (no downloads; no trunk model load), prefer the dedicated Spark-side contract probe runner:

```sh
REMOTE_MTP_SIDECAR_ENV='ALLOW_RUN=1 MTP_SIDECAR_GGUF=/abs/path/to/DeepSeek-V4-Flash-MTP-*.gguf' \
scripts/run_mtp_sidecar_contract_probe_spark.sh spark0@aitopatom-9ab9.local
```

Optional stronger check (still no trunk load): run the combined contract + llama.cpp loader probe (loads the sidecar tensor blob into RAM when `LOAD_WEIGHTS=1`, plus the pinned payload-fingerprint gate):

```sh
REMOTE_MTP_SIDECAR_ENV='ALLOW_RUN=1 MTP_SIDECAR_GGUF=/abs/path/to/DeepSeek-V4-Flash-MTP-*.gguf' \
REMOTE_LLAMA_MTP_SIDECAR_PROBE_ENV='ALLOW_FETCH=1 ALLOW_PATCH=1 ALLOW_BUILD=1 ALLOW_RUN=1 LOAD_WEIGHTS=1' \
scripts/run_mtp_sidecar_loader_probe_spark.sh spark0@aitopatom-9ab9.local
```

Acceptance checks before DS4 can trust MTP:

1. Encoding oracle passes (tokenizer/chat rendering).
2. Artifact gate: `mtp_present == true` implies `mtp_keys_sha256` matches `fixtures/model_contract/deepseek_v4_flash/contract_summary.json` `mtp.checkpoint_key_fingerprint.keys_sha256` **and** `mtp_contract.complete == true` (otherwise treat MTP as disabled/untrusted).
3. Next-token logits oracle passes (normal trunk forward + KV/cache semantics).
4. Add and validate an explicit MTP correctness oracle (weights required) that
   exercises `MTPBlock.forward(...)` semantics and the `mtp.0.hc_head_*` head.

## First Run Shape

Start with the least ambitious command that still proves real generation:

```sh
REMOTE_LLAMA_ENV='ALLOW_MODEL_INSPECT=1 ALLOW_RUN=1 RUNTIME_LABEL=v4-capable-llama MODEL_SOURCE=<hf-repo-or-local-note> MODEL_QUANT=Q2_K MODEL_GGUF=/abs/path/to/model.gguf LLAMA_CLI=/abs/path/to/llama-cli CTX=512 N_TOKENS=8 N_GPU_LAYERS=99' \
scripts/run_baseline_existing_runtime.sh spark0@aitopatom-9ab9.local
```

Optional: append a best-effort scoring row to a local CSV so you can run
`scripts/model_quality_speed_score.py` as soon as you have multiple runs:

```sh
MODEL_RUNS_CSV=/private/tmp/ds4_model_runs.csv \
REMOTE_LLAMA_ENV='ALLOW_MODEL_INSPECT=1 ALLOW_RUN=1 RUNTIME_LABEL=v4-capable-llama MODEL_SOURCE=<hf-repo-or-local-note> MODEL_QUANT=Q2_K MODEL_GGUF=/abs/path/to/model.gguf LLAMA_CLI=/abs/path/to/llama-cli CTX=512 N_TOKENS=8 N_GPU_LAYERS=99' \
scripts/run_baseline_existing_runtime.sh spark0@aitopatom-9ab9.local
```

The CSV row is derived from the `== baseline summary (approx) ==` block emitted
by the remote runner. For llama.cpp it now includes `output_tokens` (best-effort
count from the llama.cpp `eval time = ... / <tokens>` timing line), plus
canonical aliases `ttft_s`, `total_wall_s`, and `decode_tps` for cross-runtime
comparisons.

Compatibility notes (llama.cpp forks):

- Some V4-capable forks expose `--show-timings` + `--perf` instead of `--timings`. The Spark-side probe auto-detects the supported flags via `llama-cli --help` and parses either the classic `eval time = ... / <tokens>` lines or the fork-style `[ Prompt: <t/s> | Generation: <t/s> ]` summary.
- The milestone wrapper now shell-quotes values in `REMOTE_LLAMA_ENV` so `MODEL_SOURCE` can include spaces/parentheses without breaking the remote command.

### Flash-attention scheduling signal (best-effort)

When the V4-capable runtime emits `__fattn__-*` log lines, the Spark-side runner
summarizes them as:

- `fattn_log_lines=<n>`: number of log lines containing `__fattn__`
- `fattn_unique_nodes=<n>`: count of distinct `__fattn__-<id>` nodes observed

This is **not** a correctness proof, but it is a coarse signal that a Flash
Attention schedule node executed instead of falling back to a slow path. Always
preserve `remote_llamacpp_stdout.txt` / `remote_llamacpp_stderr.txt` so the
fallback reason is visible.

### Patch-status probes (read-only; recommended)

To track the current Spark-side runtime state for the DSv4 Flash Attention
pad-to-256 reservation fix and the multi-slot reserve/SWA fixes, enable the
read-only source probes in the baseline runner:

- `LLAMA_FATTN_PATCH_PROBE=1` (pad-to-256 reservation fix probe)
- `LLAMA_MULTISLOT_PATCH_PROBE=1` (multi-slot reserve/SWA fix probe)

`scripts/run_quantized_single_spark.sh` enables both probes by default. Set
either env var to `0` to skip.

The wrapper also defaults to `SKIP_MTP_SIDECAR=1` and `SKIP_VLLM=1` so a
milestone run only does: GGUF metadata inspection (optional), llama.cpp run, and
the read-only patch probes. Set either to `0` to include those extra probes.

The probes scan `LLAMA_DIR` on Spark. If your `LLAMA_CLI` looks like
`.../build*/bin/llama-cli`, the milestone wrapper infers `LLAMA_DIR` from that
path. Otherwise, set `LLAMA_DIR=/abs/path/to/llama.cpp/tree` (Spark path) in the
Mac environment so the probes scan the right runtime tree.

`scripts/run_baseline_existing_runtime.sh` also forwards `LLAMA_DIR` into the
Spark-side llama.cpp runner so the printed `== llama.cpp revision ==` line
matches the tree that `LLAMA_CLI` points at.

If you prefer the milestone wrapper (same run shape, with fewer knobs to type),
it forwards the same CSV/quality env vars:

```sh
MODEL_RUNS_CSV=/private/tmp/ds4_model_runs.csv \
MODEL_SOURCE=<hf-repo-or-local-note> MODEL_QUANT=Q2_K MODEL_GGUF=/abs/path/to/model.gguf LLAMA_CLI=/abs/path/to/llama-cli \
scripts/run_quantized_single_spark.sh spark0@aitopatom-9ab9.local
```

Note: `scripts/run_quantized_single_spark.sh` sets `LLAMA_SCOPE=deepseek_v4_flash` by default when appending CSV rows, so DeepSeek V4 Flash runs do not get mixed into generic `llamacpp` scopes. When you start recording DeepSeek speculative metrics (MTP draft/accept/reject counters), switch the label to `LLAMA_SCOPE=deepseek_v4_flash_mtp` so those rows stay separate from the target-only baseline.

If it loads and generates, rerun with:

- `CTX=4096`, then `CTX=8192`
- `N_TOKENS=128`, then `N_TOKENS=256`
- one representative chat prompt rendered through the DeepSeek V4 encoding path
- a second run after process restart to separate cold-load time from generation
- runtime instrumentation enabled if available: routing trace, expert batch
  sizes, per-token latency, memory snapshots, and MTP accept/reject counters

## Example Baseline Report

- `docs/baseline-quantized-single-spark0-2026-05-11.md` records a Spark0 run that:
  - generates tokens with `antirez/deepseek-v4-gguf` IQ2XXS (chat-v2) under a V4-capable llama.cpp fork
  - captures `scripts/model_contract_inspect_quantized_artifact.py --json` output (MTP absent)
  - confirms `__fattn__-*` nodes are scheduled (`fattn_unique_nodes=43`)

## Failure Triage

- `unsupported architecture` or `unknown model`: switch runtime first; do not
  modify DS4 code.
- `unknown GGUF type`: verify the runtime branch supports the quant type.
- OOM at load: try smaller quant, smaller context, or lower GPU offload; record
  `nvidia-smi` before and after.
- OOM during decode: reduce context first, then token count.
- Bad/empty output with successful run: verify tokenizer/chat template and BOS /
  EOS handling against `docs/model-deepseek-v4-flash.md`.

## Automation Ownership

- Baseline runtime owns the first token-producing Spark0 report.
- Upstream intake owns quantized artifact and runtime-fork provenance.
- Model contract owns tokenizer/encoding and quant-format compatibility notes.
- Build skeleton/native DS4 work should not block this milestone; it uses the
  results as a measured baseline.
