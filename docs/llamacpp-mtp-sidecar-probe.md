# llama.cpp Spark/CUDA: DeepSeek V4 MTP sidecar probe

Problem observed on Spark/CUDA llama.cpp forks (e.g. `kamnxt/llama.cpp-deepseek-v4-flash-cuda-spark@9222e55`): attempting to treat the DS4-tuned MTP sidecar as a normal model fails early with:

- `unknown model architecture: deepseek4_mtp_support`

This is expected: the sidecar is **not** a full trunk GGUF; it is a compact 32‑tensor `mtp.0.*` table used by DS4’s MTP path.

This patch adds a **metadata-only** probe binary to the Spark fork:

- `llama-ds4-mtp-sidecar-probe`

It validates:

- `general.architecture == deepseek4_mtp_support`
- the exact expected 32 tensor names under `mtp.0.*` (same list as the pinned `antirez/ds4` binder; see `docs/mtp-ds4-reference.md`)
- light self-consistency checks derived only from the tensor shapes

It does **not** require loading the trunk GGUF. By default it does **not** read tensor payloads into RAM (uses `gguf_init_from_file(..., no_alloc=true)` with a meta-only ggml context). When `--payload-sample-bytes N` is set, it reads only `N` bytes per tensor payload (via file seeks) and emits `fnv1a64` sample hashes.

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

# optional stronger check: sample 64 bytes per tensor payload
./build/bin/llama-ds4-mtp-sidecar-probe --path /abs/path/to/DeepSeek-V4-Flash-MTP-*.gguf --json --payload-sample-bytes 64

# optional stronger check: load full sidecar weights blob and validate all 32 tensors have non-null data pointers
./build/bin/llama-ds4-mtp-sidecar-probe --path /abs/path/to/DeepSeek-V4-Flash-MTP-*.gguf --json --load-weights
```

Helper script (optional; guarded by `ALLOW_*` env vars): `scripts/llamacpp_mtp_sidecar_probe_patch.sh`. It supports `LOAD_WEIGHTS=1` and `PAYLOAD_SAMPLE_BYTES=N`.

## Spark runner (optional)

If you want to build/run the probe on Spark via SSH (still gated by `ALLOW_*` on Spark), use:

```bash
REMOTE_LLAMA_MTP_SIDECAR_PROBE_ENV='ALLOW_FETCH=1 ALLOW_PATCH=1 ALLOW_BUILD=1' \
scripts/run_llamacpp_mtp_sidecar_probe_spark.sh spark0@<spark-host>

REMOTE_LLAMA_MTP_SIDECAR_PROBE_ENV='ALLOW_RUN=1 MTP_SIDECAR_GGUF=/abs/path/to/DeepSeek-V4-Flash-MTP-*.gguf PAYLOAD_SAMPLE_BYTES=64' \
scripts/run_llamacpp_mtp_sidecar_probe_spark.sh spark0@<spark-host>
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

Optional stronger check (still no full download): sample a small prefix from each tensor payload:

```bash
python3 scripts/model_contract_probe_mtp_sidecar.py --url https://huggingface.co/.../DeepSeek-V4-Flash-MTP-*.gguf --json --payload-sample-bytes 64
```

Pinned reference runner:

```bash
./scripts/model_contract_probe_mtp_sidecar_antirez_ef3b960.sh
```

Recorded reference output for a pinned antirez sidecar is in `docs/mtp-sidecar-probe-antirez-ef3b960.json`.

Stronger pinned output (includes `--payload-sample-bytes 64`) is in `docs/mtp-sidecar-probe-antirez-ef3b960-payload64.json`.
