# Spark0 Hardware Baseline

Date: 2026-05-10 (UTC) from the Mac workspace.

Host:

- mDNS name used for probes: `aitopatom-9ab9.local`
- Linux hostname: `aitopatom-9ab9`
- Login user used for probes: `spark0`

Commands run:

```bash
REDACT=1 SPARK_KNOWN_HOSTS_PER_HOST=1 DS4_GIT_DIR=.git-codex DS4_GIT_WORK_TREE=. ./scripts/spark_probe.sh spark0@aitopatom-9ab9.local > /private/tmp/ds4_spark0_probe_redacted_2026-05-10T0007Z_loop_v11.txt
```

High-level facts observed (from the probe output in `docs/spark0-probe-2026-05-10.md`):

- OS: Ubuntu 24.04.4 LTS (Noble)
- Kernel: `6.17.0-1014-nvidia`
- Architecture: `aarch64` (little-endian)
- CPU: 20 cores total (10x Cortex-X925 + 10x Cortex-A725)
- Memory: ~119 GiB total RAM (per `free -h`)
- GPU: `NVIDIA GB10`
- Driver (nvidia-smi): `580.142`
- CUDA version reported by nvidia-smi: `13.0`
- CUDA compute capability: `12.1` (nvidia-smi + nvcc runtime probe)
- CUDA toolkit (nvcc): 13.0 (V13.0.88), `nvcc` at `/usr/local/cuda/bin/nvcc` (not on default `PATH`)
- CUDA header macro (`cuda.h`): `#define CUDA_VERSION 13000`
- NVMe root disk: ~3.7 TiB, model `SAMSUNG MZALC4T0HBL1-00B07`
- PCIe link negotiation (GPU): Gen1 x1 (`nvidia-smi -q` + sysfs)
- `nvidia-smi -q` also reports `Device Max`/`Host Max` Gen5 + x16, suggesting downtraining/training rather than a true capability limit
- RDMA/ROCE devices present (`/sys/class/infiniband`, Mellanox `MT4129`), but ports were `DOWN`/`Disabled` during the probe
- cuDNN: not detected by the probe (no headers/libs found)

