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

Notes:

- The probe writes SSH host keys to `SPARK_KNOWN_HOSTS` (default: `/private/tmp/ds4_spark_known_hosts`).
- The probe includes a small `nvcc` compile + run under `/tmp` and then deletes the temporary files.
- When `REDACT=1`, the probe scrubs GPU UUID tokens that can appear in `nvidia-smi -L` output.

## What To Record In `docs/spark0-*.md`

- `nvidia-smi` driver + CUDA version.
- CUDA compute capability (from `nvidia-smi` query and the `nvcc` runtime probe).
- `nvcc` path and version (toolkit version).
- cuDNN presence/version when available (probe prints header macros + `ldconfig` hits).
- Storage summary (`df -h` + `lsblk` disk model/size).
- Wired link status + speed when available (`ip link` + optional `ethtool`).
