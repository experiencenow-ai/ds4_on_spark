# llama.cpp Spark/CUDA: DeepSeek V4 MTP sidecar probe

Problem observed on Spark/CUDA llama.cpp forks (e.g. `kamnxt/llama.cpp-deepseek-v4-flash-cuda-spark@9222e55`): attempting to treat the DS4-tuned MTP sidecar as a normal model fails early with:

- `unknown model architecture: deepseek4_mtp_support`

This is expected: the sidecar is **not** a full trunk GGUF; it is a compact 32‑tensor `mtp.0.*` table used by DS4’s MTP path.

This patch adds a **metadata-only** probe binary to the Spark fork:

- `llama-ds4-mtp-sidecar-probe`

It validates:

- `general.architecture == deepseek4_mtp_support`
- the exact expected 32 tensor names under `mtp.0.*`
- light self-consistency checks derived only from the tensor shapes

It does **not** require loading the trunk GGUF and does **not** read tensor payloads into RAM (uses `gguf_init_from_file(..., no_alloc=true)` with a meta-only ggml context).

## Patch

- Patch file: `docs/llamacpp-patches/kamnxt-llamacpp-deepseek-v4-flash-cuda-spark-9222e55-mtp-sidecar-probe.patch`
- Target upstream: `kamnxt/llama.cpp-deepseek-v4-flash-cuda-spark` at commit `9222e55`

## Apply + build (Spark)

```bash
# inside your Spark working dir
git clone https://github.com/kamnxt/llama.cpp-deepseek-v4-flash-cuda-spark.git
cd llama.cpp-deepseek-v4-flash-cuda-spark
git checkout 9222e55

git apply /path/to/ds4_on_spark/docs/llamacpp-patches/kamnxt-llamacpp-deepseek-v4-flash-cuda-spark-9222e55-mtp-sidecar-probe.patch

cmake -B build -DGGML_CUDA=ON -DCMAKE_BUILD_TYPE=Release
cmake --build build --config Release --target llama-ds4-mtp-sidecar-probe -j
```

## Run

```bash
./build/bin/llama-ds4-mtp-sidecar-probe --path /abs/path/to/DeepSeek-V4-Flash-MTP-*.gguf --json
```

Expected success signal:

- `ok=true`
- `missing=[]` and `extra=[]`

If it fails, the JSON includes `errors[]` with the first actionable reason.

## Relationship to the Python contract probe

This probe is a llama.cpp-side sanity check for local files.

For the canonical repo-side, no-download validation (HTTP range-read of header/tensor directory), use:

```bash
python3 scripts/model_contract_probe_mtp_sidecar.py --url https://huggingface.co/.../DeepSeek-V4-Flash-MTP-*.gguf --json
```

Recorded reference output for a pinned antirez sidecar is in `docs/mtp-sidecar-probe-antirez-ef3b960.json`.
