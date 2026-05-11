# llama.cpp Spark/CUDA: DeepSeek V4 MTP sidecar probe

Problem observed on Spark/CUDA llama.cpp forks (e.g. `kamnxt/llama.cpp-deepseek-v4-flash-cuda-spark@9222e55`): attempting to treat the DS4-tuned MTP sidecar as a normal model fails early with:

- `unknown model architecture: deepseek4_mtp_support`

This is expected: the sidecar is **not** a full trunk GGUF; it is a compact 32‑tensor `mtp.0.*` table used by DS4’s MTP path.

This patch adds a **metadata-only** probe binary to the Spark fork:

- `llama-ds4-mtp-sidecar-probe`

It also replaces the confusing `unknown model architecture: deepseek4_mtp_support` exception with a targeted message explaining that `deepseek4_mtp_support` is a **sidecar-only** GGUF and pointing at `llama-ds4-mtp-sidecar-probe` for validation.

It validates:

- `general.architecture == deepseek4_mtp_support`
- the exact expected 32 tensor names under `mtp.0.*` (same list as the pinned `antirez/ds4` binder; see `docs/mtp-ds4-reference.md`)
- light self-consistency checks derived from tensor shapes + types
- payload span sanity (offset monotonicity, no overlap, and file-bounds checks when `file_size` is available)

When `--json` is used, the probe also emits `file_size` (best-effort) plus a per-tensor `tensors[]` table (name, presence, ggml type code, dims, byte size, payload offset, and `has_data` when `--load-weights` is enabled). This is intended as a stable “binder inventory” for downstream loader work.

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

If `--load-weights` is reported as an unknown argument, update the ds4_on_spark patch file (`docs/llamacpp-patches/...-mtp-sidecar-probe.patch`) and rebuild the probe.
```

Helper script (optional; guarded by `ALLOW_*` env vars): `scripts/llamacpp_mtp_sidecar_probe_patch.sh`. It supports `LOAD_WEIGHTS=1` and `PAYLOAD_SAMPLE_BYTES=N`.

Notes:

- The helper is now **truly gated**: it does not `git fetch` / `git checkout` unless `ALLOW_FETCH=1` or `ALLOW_PATCH=1` is set.
- When `JSON_ONLY=1` is set, common preflight failures (missing `LLAMA_DIR`, missing probe binary, unreadable `MTP_SIDECAR_GGUF`, etc.) emit a small JSON object (`ok=false`, `errors[]`) so Spark runners can parse failures deterministically.

To verify the expected 32-tensor list is still pinned to `antirez/ds4` (binder source of truth):

```bash
./scripts/fetch_upstreams.sh ds4
python3 scripts/verify_mtp_sidecar_expected_tensors_vs_ds4.py
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

The Python probe also computes a `payload_bytes` estimate per tensor (for the expected `F32`/`Q8_0`/`Q4_K` types) and validates that tensor payload spans do not overlap and do not exceed the reported `file_size` when available.

Optional stronger check (still no full download): sample a small prefix from each tensor payload:

```bash
python3 scripts/model_contract_probe_mtp_sidecar.py --url https://huggingface.co/.../DeepSeek-V4-Flash-MTP-*.gguf --json --payload-sample-bytes 64
```

Pinned reference runner:

```bash
./scripts/model_contract_probe_mtp_sidecar_antirez.sh
```

Recorded reference output for a pinned antirez sidecar is in `docs/mtp-sidecar-probe-antirez-9cb905d.json`.

Stronger pinned output (includes `--payload-sample-bytes 64`) is in `docs/mtp-sidecar-probe-antirez-9cb905d-payload64.json`.
