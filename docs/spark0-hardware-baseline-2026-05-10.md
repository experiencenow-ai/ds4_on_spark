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

Refreshed later the same day:

```bash
REDACT=1 SPARK_KNOWN_HOSTS_PER_HOST=1 DS4_GIT_DIR=.git-codex DS4_GIT_WORK_TREE=. ./scripts/spark_probe.sh spark0@aitopatom-9ab9.local > /private/tmp/ds4_spark0_probe_redacted_2026-05-10T0109Z_loop_v4.txt
```

Refreshed again later the same day:

```bash
SPARK_SSH_USER=spark0 REDACT=1 SPARK_KNOWN_HOSTS_PER_HOST=1 DS4_GIT_DIR=.git-codex DS4_GIT_WORK_TREE=. ./scripts/spark_probe.sh aitopatom-9ab9.local > /private/tmp/ds4_spark0_probe_redacted_2026-05-10T0138Z_loop_v5.txt
```

Refreshed again later the same day:

```bash
REDACT=1 SPARK_KNOWN_HOSTS_PER_HOST=1 DS4_GIT_DIR=.git-codex DS4_GIT_WORK_TREE=. ./scripts/spark_probe.sh spark0@aitopatom-9ab9.local > /private/tmp/ds4_spark0_probe_redacted_2026-05-10T0413Z_loop_spark_access_v13.txt
```

Refreshed again (07:11Z, `.git-codex/.git` shim):

```bash
REDACT=1 SPARK_KNOWN_HOSTS_PER_HOST=1 DS4_GIT_DIR=.git-codex/.git DS4_GIT_WORK_TREE=. ./scripts/spark_probe.sh spark0@aitopatom-9ab9.local > /private/tmp/ds4_spark0_probe_redacted_2026-05-10T0712Z_loop.txt
```

Refreshed again (07:43Z, optional GPU/host PCIe query):

```bash
REDACT=1 SPARK_KNOWN_HOSTS_PER_HOST=1 DS4_GIT_DIR=.git-codex DS4_GIT_WORK_TREE=. ./scripts/spark_probe.sh spark0@aitopatom-9ab9.local > /private/tmp/ds4_spark0_probe_redacted_2026-05-10T0743Z_loop.txt
```

Refreshed again (08:13Z, `origin/main` at `git: 3728f20`, temporary gitdir):

```bash
REDACT=1 SPARK_KNOWN_HOSTS_PER_HOST=1 DS4_GIT_DIR=/private/tmp/ds4_gitdir_c87c955/git DS4_GIT_WORK_TREE=. ./scripts/spark_probe.sh spark0@aitopatom-9ab9.local > /private/tmp/ds4_spark0_probe_redacted_2026-05-10T0817Z_loop.txt
```

Refreshed again (08:43Z, `origin/main` at `git: 3a42299`, temporary gitdir):

```bash
REDACT=1 SPARK_KNOWN_HOSTS_PER_HOST=1 DS4_GIT_DIR=/private/tmp/ds4_gitshim_20260510T083825Z/git DS4_GIT_WORK_TREE=. ./scripts/spark_probe.sh spark0@aitopatom-9ab9.local > /private/tmp/ds4_spark0_probe_redacted_2026-05-10T084323Z_loop.txt
```

Refreshed again (09:13Z, loop-filtered storage output, temporary gitdir):

```bash
REDACT=1 SPARK_KNOWN_HOSTS_PER_HOST=1 DS4_GIT_DIR=/private/tmp/ds4_gitshim_20260510T090811Z/git DS4_GIT_WORK_TREE=. ./scripts/spark_probe.sh spark0@aitopatom-9ab9.local > /private/tmp/ds4_spark0_probe_redacted_2026-05-10T0918Z_loop.txt
```

Refreshed again (10:13Z, committed `nvcc --list-gpu-code` output):

```bash
REDACT=1 SPARK_KNOWN_HOSTS_PER_HOST=1 DS4_GIT_DIR=.git-codex DS4_GIT_WORK_TREE=. ./scripts/spark_probe.sh spark0@aitopatom-9ab9.local > /private/tmp/ds4_spark0_probe_redacted_2026-05-10T101326Z_loop_spark_access_nvcc_code_commit.txt
```

Refreshed again (10:42Z, `nvcc` arch sanity-check):

```bash
REDACT=1 SPARK_KNOWN_HOSTS_PER_HOST=1 DS4_GIT_DIR=.git-codex DS4_GIT_WORK_TREE=. ./scripts/spark_probe.sh spark0@aitopatom-9ab9.local > /private/tmp/ds4_spark0_probe_redacted_2026-05-10T104220Z_loop_nvcc_archcheck.txt
```

Refreshed again (11:44Z, runtime PCI bus id cross-check):

```bash
REDACT=1 SPARK_KNOWN_HOSTS_PER_HOST=1 DS4_GIT_DIR=.git-codex DS4_GIT_WORK_TREE=. ./scripts/spark_probe.sh spark0@aitopatom-9ab9.local > /private/tmp/ds4_spark0_probe_redacted_2026-05-10T114344Z_loop_pci_busid_git1ea8f17.txt
```

Refreshed again (12:13Z, toolchain paths + glibc banner):

```bash
REDACT=1 SPARK_KNOWN_HOSTS_PER_HOST=1 DS4_GIT_DIR=.git-codex/.git DS4_GIT_WORK_TREE=. ./scripts/spark_probe.sh spark0@aitopatom-9ab9.local > /private/tmp/ds4_spark0_probe_redacted_2026-05-10T121337Z_loop_toolpaths_git9ee0e27.txt
```

Refreshed again (12:43Z, `nvidia-smi -q` C2C summary):

```bash
REDACT=1 SPARK_KNOWN_HOSTS_PER_HOST=1 DS4_GIT_DIR=.git-codex/.git DS4_GIT_WORK_TREE=. ./scripts/spark_probe.sh spark0@aitopatom-9ab9.local > /private/tmp/ds4_spark0_probe_redacted_2026-05-10T1246Z_loop_c2csummary_git_e8b0486.txt
```

Refreshed again (13:13Z, runtime max cc sanity-check):

```bash
REDACT=1 SPARK_KNOWN_HOSTS_PER_HOST=1 DS4_GIT_DIR=.git-codex DS4_GIT_WORK_TREE=. ./scripts/spark_probe.sh spark0@aitopatom-9ab9.local > /private/tmp/ds4_spark0_probe_redacted_2026-05-10T1313Z_loop_runtime_ccmax_git_0cd918d.txt
```

Refreshed again (13:43Z, branch refresh):

```bash
REDACT=1 SPARK_KNOWN_HOSTS_PER_HOST=1 DS4_GIT_DIR=.git-codex DS4_GIT_WORK_TREE=. ./scripts/spark_probe.sh spark0@aitopatom-9ab9.local > /private/tmp/ds4_spark0_probe_redacted_2026-05-10T1339Z_loop_refresh.txt
```

Refreshed again (14:11Z, kernel module metadata snapshot):

```bash
REDACT=1 SPARK_KNOWN_HOSTS_PER_HOST=1 DS4_GIT_DIR=.git-codex DS4_GIT_WORK_TREE=. ./scripts/spark_probe.sh spark0@aitopatom-9ab9.local > /private/tmp/ds4_spark0_probe_redacted_2026-05-10T1411Z_loop_access.txt
```

Refreshed again (14:47Z refresh, runtime max cc line):

```bash
REDACT=1 SPARK_KNOWN_HOSTS_PER_HOST=1 DS4_GIT_DIR=.git-codex DS4_GIT_WORK_TREE=. ./scripts/spark_probe.sh spark0@aitopatom-9ab9.local > /private/tmp/ds4_spark0_probe_redacted_2026-05-10T1446Z_loop_runtime_maxcc.txt
```

Refreshed again (15:19Z refresh, Spark1-ready loop):

```bash
REDACT=1 SPARK_KNOWN_HOSTS_PER_HOST=1 DS4_GIT_DIR=.git-codex DS4_GIT_WORK_TREE=. ./scripts/spark_probe.sh spark0@aitopatom-9ab9.local > /private/tmp/ds4_spark0_probe_redacted_2026-05-10T151929Z_loop_spark1summary_fix.txt
```

High-level facts observed (from the probe output in `docs/spark0-probe-2026-05-10.md`):

- OS: Ubuntu 24.04.4 LTS (Noble)
- Kernel: `6.17.0-1014-nvidia`
- Architecture: `aarch64` (little-endian)
- Toolchain: gcc/g++ 13.3.0, cmake 3.28.3, make 4.3, python 3.12.3
- glibc (ldd): 2.39
- CPU: 20 cores total (10x Cortex-X925 + 10x Cortex-A725)
- Memory: ~119 GiB total RAM (per `free -h`)
- GPU: `NVIDIA GB10`
- Driver (nvidia-smi): `580.142`
- CUDA version reported by nvidia-smi: `13.0`
- CUDA compute capability: `12.1` (nvidia-smi + nvcc runtime probe; probe also prints `runtime max cc: 12.1`)
- CUDA runtime probe prints `device0 pci bus id: 000F:01:00.0`, matching `nvidia-smi` `pci.bus_id` (`0000000F:01:00.0`)
- CUDA toolkit (nvcc): 13.0 (V13.0.88), `nvcc` at `/usr/local/cuda/bin/nvcc` (not on default `PATH`)
- `nvcc --list-gpu-code` includes `sm_121`, matching the observed compute capability (`12.1`) and `NVCC_ARCH=sm_121` probe default
- CUDA toolkit component versions (`/usr/local/cuda/version.json`): CUDA SDK 13.0.3, cuDART 13.0.96, CCCL 13.0.85
- CUDA header macro (`cuda.h`): `#define CUDA_VERSION 13000`
- GPU memory (cuda runtime probe): 128,518,373,376 bytes (~119.7 GiB)
- GPU SM count (cuda runtime probe): 48
- NVMe root disk: ~3.7 TiB, model `SAMSUNG MZALC4T0HBL1-00B07`
- PCIe link negotiation (GPU): Gen1 x1 (`nvidia-smi -q` + sysfs)
- `nvidia-smi -q` also reports `Peer Type: Direct Connected` and `GPU C2C Mode: Enabled` (treat the PCIe link fields as best-effort/legacy reporting rather than the actual GPU<->CPU fabric)
- `nvidia-smi -q` also reports `Device Max`/`Host Max` Gen5 + x16, suggesting downtraining/training rather than a true capability limit
- When supported, the probe also prints `nvidia-smi` optional CSV fields `pcie.link.gen.gpumax` / `pcie.link.gen.hostmax`, which match the `nvidia-smi -q` `Device Max`/`Host Max` Gen5 report (while the legacy `pcie.link.gen.max` field remains `1` on this host)
- Sysfs path-chain shows the upstream bridge reporting `max_link_speed: 32.0 GT/s`, while the GPU endpoint reports `max_link_speed: 2.5 GT/s`; keep treating link reporting as potentially inconsistent and rely on multiple sources until the PCIe story is resolved
- As of the 09:13Z refresh (`git: afbc122`), the sysfs path-chain also showed the upstream bridge reporting `current_link_speed: Unknown` and `current_link_width: 0` even while the endpoint continued to report Gen1 x1; treat upstream `current_link_*` as best-effort until corroborated
- RDMA/ROCE devices present (`/sys/class/infiniband`, Mellanox `MT4129`), but ports were `DOWN`/`Disabled` during the probe
- cuDNN: not detected by the probe (no headers/libs found)
- NVIDIA kernel module appears to be the open variant (`NVIDIA UNIX Open Kernel Module for aarch64`, `nvidia-580-open`), with `modinfo nvidia` reporting `filename: .../kernel/nvidia-580-open/nvidia.ko`
