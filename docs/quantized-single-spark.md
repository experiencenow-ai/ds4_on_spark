# Quantized Single-Spark Milestone

Goal: get DeepSeek V4 Flash producing tokens on **one** Spark before the native
DS4 runtime and dual-Spark TP path are ready.

This is the first gate for the broader quantized high-performance path described
in `docs/quantized-performance-path.md`. A slow or low-quality first token
stream is useful if it proves the model artifact, runtime, CUDA path,
tokenizer/chat format, and memory envelope are real.

## Definition of Done

- One Spark0 command produces non-empty generated text from a V4 Flash-family
  quantized artifact.
- The run records exact runtime source, runtime commit, model source, quant,
  file size, sha256, command line, context length, token count, TTFT, tokens/sec
  where available, GPU memory snapshot, CPU RSS, stdout, stderr, and exit code.
- Note the upstream reference defaults are `max_seq_len=4096` and `max_batch_size=4`, but any external runtime may choose different values; record the actual context/window settings used.
- The report records whether the artifact preserves the upstream MTP namespace
  (`mtp.0.*`) and whether MTP was enabled/disabled for the run (see “MTP / tensor-key compatibility” below).
- If the run fails, the report preserves the exact failure mode: unsupported
  architecture, unsupported GGUF type, OOM, CUDA kernel failure, tokenizer/chat
  mismatch, or runtime crash.
- No automation downloads large model files unless a human explicitly approves
  the exact command and target path.

## Candidate Artifacts

As of 2026-05-09, the practical first target is a community GGUF using a
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

Interpreting the result:

- If `mtp_present == false`, treat the artifact as **MTP-disabled** even if it
  generates text normally. Any runtime “speculative” or “draft” feature must be
  treated as untrusted unless it can be traced back to `mtp.0.*` weights.
- If `mtp_present == true`, the artifact is only **MTP-capable** if the runtime
  actually loads and uses those tensors. Still require correctness oracles
  before trusting MTP outputs.

Acceptance checks before DS4 can trust MTP:

1. Encoding oracle passes (tokenizer/chat rendering).
2. Next-token logits oracle passes (normal trunk forward + KV/cache semantics).
3. Add and validate an explicit MTP correctness oracle (weights required) that
   exercises `MTPBlock.forward(...)` semantics and the `mtp.0.hc_head_*` head.

## First Run Shape

Start with the least ambitious command that still proves real generation:

```sh
REMOTE_LLAMA_ENV='ALLOW_RUN=1 RUNTIME_LABEL=v4-capable-llama MODEL_SOURCE=<hf-repo-or-local-note> MODEL_QUANT=Q2_K MODEL_GGUF=/abs/path/to/model.gguf LLAMA_CLI=/abs/path/to/llama-cli CTX=2048 N_TOKENS=32 N_GPU_LAYERS=99' \
scripts/run_baseline_existing_runtime.sh spark0@aitopatom-9ab9.local
```

If it loads and generates, rerun with:

- `CTX=4096`, then `CTX=8192`
- `N_TOKENS=128`, then `N_TOKENS=256`
- one representative chat prompt rendered through the DeepSeek V4 encoding path
- a second run after process restart to separate cold-load time from generation
- runtime instrumentation enabled if available: routing trace, expert batch
  sizes, per-token latency, memory snapshots, and MTP accept/reject counters

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
