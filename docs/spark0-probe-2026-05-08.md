# Spark0 Probe (2026-05-08)

Host:

- mDNS name: `aitopatom-9ab9.local`
- Linux hostname: `aitopatom-9ab9`
- User: `spark0`

Commands run from the Mac:

```bash
REDACT=1 ./scripts/spark_probe.sh spark0@aitopatom-9ab9.local
```

Notes:

- `nvidia-smi` reports the driver CUDA compatibility version (`CUDA Version: 13.0`).
- `nvcc` is installed at `/usr/local/cuda/bin/nvcc` (may not be on `$PATH` by default).
- Use `REDACT=1` when saving probe output for commit; see `docs/spark0-hardware-baseline-2026-05-08.md` for a full redacted snapshot.

## Key facts

Operating system:

- Ubuntu 24.04.4 LTS (`aarch64`)
- Kernel: `6.17.0-1014-nvidia`

Toolchain:

- `gcc`/`g++`: 13.3.0
- `cmake`: 3.28.3
- `python3`: 3.12.3

GPU:

- `nvidia-smi` driver: `580.142`
- GPU name: `NVIDIA GB10`
- CUDA compute capability (runtime): `12.1`
- CUDA compilation tools: `13.0` (`nvcc` reports `V13.0.88`)

Storage:

- Root filesystem: 3.7 TiB (`/dev/nvme0n1p2`)
- Used during probe: 38 GiB

Network:

- Wired: `enP7s7` `<redacted-ipv4>/24` (not the default route)
- Wi-Fi: `wlP9s9` `<redacted-ipv4>/24` (default route)

## Probe excerpts

`nvidia-smi` header:

```text
NVIDIA-SMI 580.142                Driver Version: 580.142        CUDA Version: 13.0
```

CUDA runtime device properties (compiled and executed via `nvcc`):

```text
device_count=1
device=0 name=NVIDIA GB10
compute_capability=12.1
totalGlobalMem_bytes=128518373376
multiProcessorCount=48
memoryBusWidth_bits=256
l2CacheSize_bytes=25165824
```
