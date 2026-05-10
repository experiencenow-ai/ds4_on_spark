# Quantized Single-Spark Milestone

Goal: get DeepSeek V4 Flash producing tokens on **one** Spark (Spark0) before the native DS4 runtime and dual-Spark TP path are ready.

This is the first gate for the broader quantized high-performance path described
in `docs/quantized-performance-path.md`. A slow or low-quality first token
stream is useful if it proves the model artifact, runtime, CUDA path,
tokenizer/chat format, and memory envelope are real.

## Definition of Done

- One Spark0 command produces non-empty generated text from a V4 Flash-family
  quantized artifact.
- The run records exact runtime source, runtime commit (or binary hash/version),
  model source, quant, file size, sha256, command line, context length, token
  count, TTFT, tokens/sec where available, GPU memory snapshot, CPU RSS, stdout,
  stderr, and exit code.
- Note the upstream reference defaults are `max_seq_len=4096` and `max_batch_size=4`, but any external runtime may choose different values; record the actual context/window settings used.
- The report records whether the artifact preserves the upstream MTP namespace
  (`mtp.0.*`) and whether MTP was enabled/disabled for the run (see “MTP / tensor-key compatibility” below).
- When the artifact is a GGUF, the llama.cpp Spark baseline script attempts a
  cheap tensor-name scan and records `gguf_has_mtp` / `gguf_mtp_tensor_count` in
  the baseline summary (and writes `gguf_probe.txt` into the fetched Spark
  artifacts directory) when supported by the runtime.
- The report includes `scripts/model_contract_inspect_quantized_artifact.py --json` output for the tested artifact (at minimum: `metadata.general.*`, `tensor_type_counts`, and `mtp_tensor_type_counts` when present).
  - When the repo-default `fixtures/model_contract/deepseek_v4_flash/contract_summary.json` is available, this output also includes:
    - `tensor_key_namespace_guess` + `first_tensor_keys` (quick signal for whether the artifact appears to preserve upstream tensor key namespaces; many GGUF conversions are `llama.cpp`)
    - `trunk_contract` (upstream tensor-key completeness for top-level + `layers.{i}.*`)
    - `mtp_contract` (upstream tensor-key completeness for `mtp.{j}.*` when present)
    - `topology_contract` (GGUF header metadata vs expected `hidden_size`, `block_count`, head counts, vocab size, and (when present) RoPE `dimension_count` / `freq_base`)
    - For trunk+sidecar inspections (multiple `--path`), the JSON includes both per-artifact and `combined.*` summaries; use `combined.topology_contract_source_path` to see which GGUF header was used for the combined topology check.
- If the run fails, the report preserves the exact failure mode: unsupported
  architecture, unsupported GGUF type, OOM, CUDA kernel failure, tokenizer/chat
  mismatch, or runtime crash.
- No automation downloads large model files unless a human explicitly approves
  the exact command and target path.

## Candidate Artifacts

As of 2026-05-09, the practical first target is a community GGUF using a DeepSeek V4-capable llama.cpp fork or early-access runtime. Stock stable llama.cpp should be treated as unproven for V4 Flash until verified.

| Candidate | Why it matters | First-use posture |
| --- | --- | --- |
| Q2_K GGUF | Smallest currently useful class for a single Spark memory envelope. | Preferred first full-model smoke target if the runtime can load it. |
| Q3_K_M GGUF | Better quality but larger; tighter memory envelope. | Try after Q2_K, with small context and careful memory logging. |
| Native FP4/FP8 GGUF | Closest to upstream checkpoint's native low-precision layout. | Use for loader/format validation; likely tight for a single Spark. |
| Official HF safetensors | Source of truth for native DS4 loader work. | Metadata only unless a human approves checkpoint download. |

For any community artifact, record provenance rather than trusting the model card summary: HF repo, revision, file list, file sizes, sha256, declared base model, declared license, required runtime fork, and any conversion command.

## MTP (multi-token prediction) expectations

DeepSeek V4 Flash’s official checkpoint includes an MTP module namespace (`mtp.0.*`). Many derived artifacts (especially GGUF conversions) may drop it.

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
  - `trunk_contract.checked` is expected to be `false` (it only applies when `layers.{i}.*` keys are preserved).
  - The absence of `mtp.0.*` keys (`mtp_present == false`) means upstream MTP preservation is *not* proven; treat MTP as disabled/untrusted.
- For GGUF, record `tensor_type_counts` (and `mtp_tensor_type_counts` when present) to capture the exact quant formats the runtime must support (e.g. `Q2_K`, `Q3_K`, `BF16`, `MXFP4`).
  - If `topology_contract.checked == true` and `topology_contract.mismatches` is non-empty, treat the artifact as **suspect** (topology mismatch) until a human explains the discrepancy.
Observed metadata-only inspections (2026-05-09):

| Artifact URL (pinned) | `tensor_key_namespace_guess` | `mtp_present` | `url_prefix_bytes` | Recorded probe |
| --- | --- | --- | --- | --- |
| `https://huggingface.co/Preyazz/DeepSeek-V4-Flash-GGUF/resolve/6c6d74ce4efd3e1045c15e5823d75e62b6e4ba1d/DeepSeek-V4-Flash-Q4_K_M.gguf` | `llama.cpp` | `false` | `8388608` | `docs/gguf-inspect-preyazz-6c6d74c-q4-k-m.json` |
| `https://huggingface.co/nsparks/DeepSeek-V4-Flash-FP4-FP8-GGUF/resolve/0b34e0b629c706396002496e795e9f910f7bf69f/DeepSeek-V4-Flash-FP4-FP8-native.gguf` | `llama.cpp` | `false` | `8388608` | `docs/gguf-inspect-nsparks-0b34e0b-fp4-fp8-native.json` |
| `https://huggingface.co/antirez/deepseek-v4-gguf/resolve/ef3b960827870d69ed0b225c095a617c12d7e80d/DeepSeek-V4-Flash-IQ2XXS-w2Q2K-AProjQ8-SExpQ8-OutQ8-chat-v2.gguf` | `llama.cpp` | `false` | `8388608` | `docs/gguf-inspect-antirez-ef3b960-iq2xxs-chat-v2.json` |

MTP sidecar example (metadata-only inspection; 2026-05-09):

- `antirez/deepseek-v4-gguf` `DeepSeek-V4-Flash-MTP-Q4K-Q8_0-F32.gguf` @ `ef3b960827870d69ed0b225c095a617c12d7e80d`:
  - Recorded output: `docs/gguf-inspect-antirez-ef3b960-mtp-sidecar.json`
  - Summary: `mtp_present=true` and `tensor_key_namespace_guess=deepseek-upstream-mtp-only`, but `mtp_contract.complete=false` with `mtp_tensor_count=32` (compact DS4-tuned sidecar, not a full upstream `mtp.0.*` checkpoint).

To validate a sidecar that is already present on Spark (no downloads; no trunk model load), run the Spark-side contract probe via the baseline runner:

```sh
REMOTE_MTP_SIDECAR_ENV='ALLOW_RUN=1 MTP_SIDECAR_GGUF=/abs/path/to/DeepSeek-V4-Flash-MTP-*.gguf' \
scripts/run_baseline_existing_runtime.sh spark0@aitopatom-9ab9.local
```

Acceptance checks before DS4 can trust MTP:

1. Encoding oracle passes (tokenizer/chat rendering).
2. Next-token logits oracle passes (normal trunk forward + KV/cache semantics).
3. Add and validate an explicit MTP correctness oracle (weights required) that
   exercises `MTPBlock.forward(...)` semantics and the `mtp.0.hc_head_*` head.

## First Run Shape

Start with the least ambitious command that still proves real generation:

```sh
ALLOW_RUN=1 \
RUNTIME_LABEL=v4-capable-llama \
MODEL_SOURCE='<hf-repo-or-local-note>' \
MODEL_QUANT=Q2_K \
MODEL_GGUF=/abs/path/to/model.gguf \
LLAMA_CLI=/abs/path/to/v4-capable/llama-cli \
CTX=2048 \
N_TOKENS=32 \
N_GPU_LAYERS=99 \
scripts/run_baseline_existing_runtime.sh spark0@aitopatom-9ab9.local
```

Wrapper variant (same shape, fewer knobs):

```sh
MODEL_GGUF=/abs/path/to/model.gguf \
LLAMA_CLI=/abs/path/to/v4-capable/llama-cli \
MODEL_SOURCE='<hf-repo-or-local-note>' \
MODEL_QUANT=Q2_K \
scripts/run_quantized_single_spark.sh spark0@aitopatom-9ab9.local
```

If it loads and generates, rerun with:

- `CTX=4096`, then `CTX=8192`
- `N_TOKENS=128`, then `N_TOKENS=256`
- one representative chat prompt rendered through the DeepSeek V4 encoding path
- a second run after process restart to separate cold-load time from generation
- runtime instrumentation enabled if available: routing trace, expert batch
  sizes, per-token latency, memory snapshots, and MTP accept/reject counters

## Instrumentation Hooks (Read-only)

- Optional Spark inventory (read-only): set `SPARK_INVENTORY=1` when running the
  baseline entrypoint to record a best-effort scan for candidate `*.gguf` files
  and common runtime binaries. Keep scan depth small; do not run wide filesystem
  searches. When supported on the Spark host, the inventory lists GGUFs as
  `size_bytes<TAB>path` to make “smallest credible artifact” selection faster.
- GPU polling during runs: set `GPU_SAMPLE=1` (default) and adjust `GPU_SAMPLE_INTERVAL_S` (default `1`) to emit `nvidia_smi_poll.csv` alongside the normal `nvidia-smi` snapshots.
- The baseline summary also derives best-effort GPU poll stats from `nvidia_smi_poll.csv` (memory min/max/delta; plus util/power percentiles when present).
- llama.cpp token trace (best-effort): if the runtime emits per-token JSON log events (for example `process_token`), the Spark llama.cpp script writes them to `token_trace.jsonl` in the fetched artifacts directory. Do not guess flags; use the captured `llama_cli.help.txt` and only enable runtime-supported log options via `EXTRA_ARGS`.
- When token JSON is present, the llama.cpp script also prints read-only derived fields into the baseline summary (per-token latency percentiles; best-effort expert/queue/router-score/MTP counters if present).
- CUDA placement / fallback (best-effort): if the runtime prints `sched_reserve:` / `__fattn__-*` / `__op__-*` placement lines during a one-shot `llama-cli` run, the script writes `fattn_cli_probe.json` into the fetched artifacts directory and mirrors key fields into the baseline summary (`fattn_*`, `node_kind_*`, `sched_reserve_*`). This is opportunistic and may be `NA` on forks that do not emit those lines.
- See `docs/quantized-performance-path.md` for the ordered instrumentation path after the first successful token stream.
- After the first successful token stream, prioritize the batching/concurrency throughput sweep on Spark0 (expensive; requires a resident `llama-server`): see `docs/baseline-batching-throughput.md`.

## Failure Triage

- `unsupported architecture` or `unknown model`: switch runtime first; do not modify DS4 code.
- `unknown GGUF type`: verify the runtime branch supports the quant type.
- OOM at load: try smaller quant, smaller context, or lower GPU offload; record `nvidia-smi` before and after.
- OOM during decode: reduce context first, then token count.
- Bad/empty output with successful run: verify tokenizer/chat template and BOS/EOS handling against `docs/model-deepseek-v4-flash.md`.

## Automation Ownership

- Baseline runtime owns the first token-producing Spark0 report.
- Upstream intake owns quantized artifact and runtime-fork provenance.
- Model contract owns tokenizer/encoding and quant-format compatibility notes.
- Build skeleton/native DS4 work should not block this milestone; it uses the results as a measured baseline.
