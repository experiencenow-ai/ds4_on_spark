# Spark0/Spark1 Probe Runbook

This is a lightweight, reproducible probe flow for Spark hosts.

## Goals

- Capture non-secret hardware + toolchain facts (CPU/RAM/storage/GPU/CUDA toolchain).
- Verify CUDA compute capability via multiple sources (`nvidia-smi` query + a tiny `nvcc` runtime probe).
- Keep committed artifacts safe: redact IP/MAC tokens.

## Mac-Side Discovery

Use discovery first to confirm which `*.local` targets resolve and whether TCP/22 is reachable.

```bash
REDACT=1 ./scripts/mac_spark_discovery.sh aitopatom-9ab9.local spark1.local
```

Omit args to use the same default targets.

## Spark Probe (Redacted)

Always use `REDACT=1` when saving output for commit.

```bash
REDACT=1 ./scripts/spark_probe.sh spark0@aitopatom-9ab9.local | tee /private/tmp/spark0-probe.txt
REDACT=1 ./scripts/spark_probe.sh spark0@spark1.local | tee /private/tmp/spark1-probe.txt
```

Optional toggles:

- Include full `nvidia-smi` output (verbose; includes process list + timestamps):

```bash
REDACT=1 NVIDIA_SMI_FULL=1 ./scripts/spark_probe.sh spark0@aitopatom-9ab9.local | tee /private/tmp/spark0-probe-verbose.txt
```

- Skip the `nvcc` runtime probe compile/run (when you only need the driver-side query):

```bash
REDACT=1 CUDA_RUNTIME_PROBE=0 ./scripts/spark_probe.sh spark0@aitopatom-9ab9.local
```

- Force the `nvcc` runtime probe compile arch (defaults to deriving from `nvidia-smi` compute capability when available):

```bash
REDACT=1 NVCC_ARCH=sm_121 ./scripts/spark_probe.sh spark0@aitopatom-9ab9.local
```

Notes:

- The probe writes SSH host keys to `SPARK_KNOWN_HOSTS` (default: `/private/tmp/ds4_spark_known_hosts`).
- When probing multiple Spark hosts, consider `SPARK_KNOWN_HOSTS_PER_HOST=1` so Spark0 and Spark1 keep separate known_hosts files.
- The probe includes a small `nvcc` compile + run under `/tmp` and then deletes the temporary files.
- When `REDACT=1`, the probe scrubs GPU UUID tokens that can appear in `nvidia-smi -L` output.
- If the checkout `.git` metadata is unusable (macOS provenance/permission), set `DS4_GIT_DIR=/path/to/.git` so probe artifacts include `git: <hash>`.

## What To Record In `docs/spark0-*.md`

- `nvidia-smi` driver + CUDA version.
- `nvidia-smi` inventory line(s) (includes GPU `index` + `pci.bus_id`).
- CUDA compute capability (from `nvidia-smi` query and the `nvcc` runtime probe).
- `nvcc` path and version (toolkit version).
- `cuda.h` macros (`CUDA_VERSION` / `CUDART_VERSION`) to cross-check toolkit headers.
- cuDNN presence/version when available (probe prints header macros + `ldconfig` hits).
- `nvidia-smi topo -m` (capped) + `modinfo nvidia` summary to capture GPU/driver topology and module version metadata.
- Storage summary (`df -h` + `lsblk` disk model/size).
- Wired link status + speed when available (`ip link` + optional `ethtool`).
