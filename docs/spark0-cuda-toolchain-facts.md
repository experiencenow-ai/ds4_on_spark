# Spark0 CUDA + Toolchain Facts (Stable Reference)

This is a compact, non-secret reference for Spark0 (`aitopatom-9ab9.local`). It is derived from the commit-safe probe snapshots in `docs/`.

## Current Facts (observed 2026-05-13)

- Host: `aitopatom-9ab9.local` (user: `spark0`)
- GPU: `NVIDIA GB10` (Blackwell)
- Compute capability: `12.1`
- Driver (`nvidia-smi --version`): `580.142`
- `nvidia-smi` reported CUDA: `13.0`
- `nvcc` (toolkit): `13.0.88` (release `13.0`; installed at `/usr/local/cuda/bin/nvcc`, not on `$PATH`)
- `/usr/local/cuda/version.json` `cuda`: `13.0.3`
- `/usr/local/cuda/include/cuda.h` `CUDA_VERSION`: `13000`

Source snapshot (commit-safe):
- `docs/spark0-probe-facts-2026-05-13T0628Z.md`

## How To Re-Verify (Commit-Safe)

From the Mac repo root:

```bash
stamp="$(date -u +%Y-%m-%dT%H%MZ)"
SPARK_SSH_USER=spark0 REDACT=1 SPARK_PROBE_FACTS=1 SPARK_KNOWN_HOSTS_PER_HOST=1 DS4_GIT_DIR=.codex_git DS4_GIT_WORK_TREE=. ./scripts/spark_probe.sh aitopatom-9ab9.local > "docs/spark0-probe-facts-${stamp}.md"
```

Notes:
- When `nvidia-smi --query-gpu=compute_cap` is unsupported, the probe’s tiny `nvcc` runtime test is the fallback source (`device0 cc:`).
- On unified-memory hosts, `nvidia-smi` can report `memory.total=[N/A]`; use the probe’s `== memory ==` and `device0 global mem (bytes)` instead.
- Spark0 has shown PCIe link downtraining in snapshots; see the `warning:` lines in the referenced facts snapshot.
