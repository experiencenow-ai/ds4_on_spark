# Quantized Single-Spark Milestone

Goal: get DeepSeek V4 Flash producing tokens on **one** Spark (Spark0) before the native DS4 runtime and dual-Spark TP path are ready.

This is an intermediate execution milestone, not the final architecture. A slow or low-quality first token stream is useful if it proves the model artifact, runtime, CUDA path, tokenizer/chat format, and memory envelope are real.

## Definition of Done

- One Spark0 command produces non-empty generated text from a V4 Flash-family quantized artifact.
- The run records exact runtime source + revision (or binary hash), model source, quant, file size, sha256, command line, context length, token count, TTFT, tokens/sec where available, GPU memory snapshot, CPU RSS, stdout, stderr, and exit code.
- If the run fails, the report preserves the exact failure mode: unsupported architecture, unsupported GGUF type, OOM, CUDA kernel failure, tokenizer/chat mismatch, or runtime crash.
- No automation downloads large model files unless a human explicitly approves the exact command and target path.

## Candidate Artifacts

As of 2026-05-09, the practical first target is a community GGUF using a DeepSeek V4-capable llama.cpp fork or early-access runtime. Stock stable llama.cpp should be treated as unproven for V4 Flash until verified.

| Candidate | Why it matters | First-use posture |
| --- | --- | --- |
| Q2_K GGUF | Smallest currently useful class for a single Spark memory envelope. | Preferred first full-model smoke target if the runtime can load it. |
| Q3_K_M GGUF | Better quality but larger; tighter memory envelope. | Try after Q2_K, with small context and careful memory logging. |
| Native FP4/FP8 GGUF | Closest to upstream checkpoint's native low-precision layout. | Use for loader/format validation; likely tight for a single Spark. |
| Official HF safetensors | Source of truth for native DS4 loader work. | Metadata only unless a human approves checkpoint download. |

For any community artifact, record provenance rather than trusting the model card summary: HF repo, revision, file list, file sizes, sha256, declared base model, declared license, required runtime fork, and any conversion command.

## First Run Shape (Spark0)

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

If it loads and generates, rerun with:

- `CTX=4096`, then `CTX=8192`
- `N_TOKENS=128`, then `N_TOKENS=256`
- one representative chat prompt rendered through the DeepSeek V4 encoding path
- a second run after process restart to separate cold-load time from generation

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

