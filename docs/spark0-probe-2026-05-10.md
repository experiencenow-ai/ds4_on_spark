# Spark0 Probe (2026-05-10)

Host:

- mDNS name: `aitopatom-9ab9.local`
- Linux hostname: `aitopatom-9ab9`
- User: `spark0`

Commands run from the Mac:

```bash
REDACT=1 SPARK_KNOWN_HOSTS_PER_HOST=1 DS4_GIT_DIR=.git-codex DS4_GIT_WORK_TREE=. ./scripts/spark_probe.sh spark0@aitopatom-9ab9.local | tee /private/tmp/ds4_spark0_probe_redacted_2026-05-10T0007Z_loop_v11.txt
SPARK_SSH_USER=spark0 REDACT=1 SPARK_KNOWN_HOSTS_PER_HOST=1 DS4_GIT_DIR=.git-codex DS4_GIT_WORK_TREE=. ./scripts/spark_probe.sh aitopatom-9ab9.local spark1.local | tee /private/tmp/ds4_spark01_probe_redacted_2026-05-10T0111Z_loop_v4.txt || true
```

Additional probe run (later the same day):

```bash
REDACT=1 SPARK_KNOWN_HOSTS_PER_HOST=1 DS4_GIT_DIR=.git-codex DS4_GIT_WORK_TREE=. ./scripts/spark_probe.sh spark0@aitopatom-9ab9.local | tee /private/tmp/ds4_spark0_probe_redacted_2026-05-10T0109Z_loop_v4.txt
SPARK_SSH_USER=spark0 REDACT=1 SPARK_KNOWN_HOSTS_PER_HOST=1 DS4_GIT_DIR=.git-codex DS4_GIT_WORK_TREE=. ./scripts/spark_probe.sh aitopatom-9ab9.local | tee /private/tmp/ds4_spark0_probe_redacted_2026-05-10T0138Z_loop_v5.txt
REDACT=1 SPARK_KNOWN_HOSTS_PER_HOST=1 DS4_GIT_DIR=.git-codex DS4_GIT_WORK_TREE=. ./scripts/spark_probe.sh spark0@aitopatom-9ab9.local | tee /private/tmp/ds4_spark0_probe_redacted_2026-05-10T0221Z_loop_spark_access_after4.txt
REDACT=1 SPARK_KNOWN_HOSTS_PER_HOST=1 DS4_GIT_DIR=.git-codex DS4_GIT_WORK_TREE=. ./scripts/spark_probe.sh spark0@aitopatom-9ab9.local | tee /private/tmp/ds4_spark0_probe_redacted_2026-05-10T0413Z_loop_spark_access_v13.txt
```

Additional probe run (07:12Z refresh, `.git-codex/.git` shim):

```bash
REDACT=1 SPARK_KNOWN_HOSTS_PER_HOST=1 DS4_GIT_DIR=.git-codex/.git DS4_GIT_WORK_TREE=. ./scripts/spark_probe.sh spark0@aitopatom-9ab9.local | tee /private/tmp/ds4_spark0_probe_redacted_2026-05-10T0712Z_loop.txt
```

Additional probe run (07:43Z refresh, optional GPU/host PCIe query):

```bash
REDACT=1 SPARK_KNOWN_HOSTS_PER_HOST=1 DS4_GIT_DIR=.git-codex DS4_GIT_WORK_TREE=. ./scripts/spark_probe.sh spark0@aitopatom-9ab9.local | tee /private/tmp/ds4_spark0_probe_redacted_2026-05-10T0743Z_loop.txt
```

Additional probe run (08:13Z refresh, `origin/main` at `git: 3728f20`, temporary gitdir):

```bash
REDACT=1 SPARK_KNOWN_HOSTS_PER_HOST=1 DS4_GIT_DIR=/private/tmp/ds4_gitdir_c87c955/git DS4_GIT_WORK_TREE=. ./scripts/spark_probe.sh spark0@aitopatom-9ab9.local | tee /private/tmp/ds4_spark0_probe_redacted_2026-05-10T0817Z_loop.txt
```

Additional probe run (08:43Z refresh, `origin/main` at `git: 3a42299`, temporary gitdir):

```bash
REDACT=1 SPARK_KNOWN_HOSTS_PER_HOST=1 DS4_GIT_DIR=/private/tmp/ds4_gitshim_20260510T083825Z/git DS4_GIT_WORK_TREE=. ./scripts/spark_probe.sh spark0@aitopatom-9ab9.local | tee /private/tmp/ds4_spark0_probe_redacted_2026-05-10T084323Z_loop.txt
```

Additional probe run (09:13Z refresh, loop-filtered storage output, temporary gitdir):

```bash
REDACT=1 SPARK_KNOWN_HOSTS_PER_HOST=1 DS4_GIT_DIR=/private/tmp/ds4_gitshim_20260510T090811Z/git DS4_GIT_WORK_TREE=. ./scripts/spark_probe.sh spark0@aitopatom-9ab9.local | tee /private/tmp/ds4_spark0_probe_redacted_2026-05-10T0918Z_loop.txt
```

Additional probe run (10:13Z refresh, committed `nvcc --list-gpu-code` output):

```bash
REDACT=1 SPARK_KNOWN_HOSTS_PER_HOST=1 DS4_GIT_DIR=.git-codex DS4_GIT_WORK_TREE=. ./scripts/spark_probe.sh spark0@aitopatom-9ab9.local | tee /private/tmp/ds4_spark0_probe_redacted_2026-05-10T101326Z_loop_spark_access_nvcc_code_commit.txt
REDACT=1 SPARK_KNOWN_HOSTS_PER_HOST=1 DS4_GIT_DIR=.git-codex DS4_GIT_WORK_TREE=. ./scripts/spark_probe.sh spark0@aitopatom-9ab9.local | tee /private/tmp/ds4_spark0_probe_redacted_2026-05-10T104220Z_loop_nvcc_archcheck.txt
```

Additional probe run (11:44Z refresh, runtime PCI bus id cross-check):

```bash
REDACT=1 SPARK_KNOWN_HOSTS_PER_HOST=1 DS4_GIT_DIR=.git-codex DS4_GIT_WORK_TREE=. ./scripts/spark_probe.sh spark0@aitopatom-9ab9.local | tee /private/tmp/ds4_spark0_probe_redacted_2026-05-10T114344Z_loop_pci_busid_git1ea8f17.txt
```

Additional probe run (12:13Z refresh, toolchain paths + glibc banner):

```bash
REDACT=1 SPARK_KNOWN_HOSTS_PER_HOST=1 DS4_GIT_DIR=.git-codex/.git DS4_GIT_WORK_TREE=. ./scripts/spark_probe.sh spark0@aitopatom-9ab9.local | tee /private/tmp/ds4_spark0_probe_redacted_2026-05-10T121337Z_loop_toolpaths_git9ee0e27.txt
```

Additional probe run (12:43Z refresh, `nvidia-smi -q` C2C summary):

```bash
REDACT=1 SPARK_KNOWN_HOSTS_PER_HOST=1 DS4_GIT_DIR=.git-codex/.git DS4_GIT_WORK_TREE=. ./scripts/spark_probe.sh spark0@aitopatom-9ab9.local | tee /private/tmp/ds4_spark0_probe_redacted_2026-05-10T1246Z_loop_c2csummary_git_e8b0486.txt
```

Additional probe run (13:13Z refresh, runtime max cc sanity-check):

```bash
REDACT=1 SPARK_KNOWN_HOSTS_PER_HOST=1 DS4_GIT_DIR=.git-codex DS4_GIT_WORK_TREE=. ./scripts/spark_probe.sh spark0@aitopatom-9ab9.local | tee /private/tmp/ds4_spark0_probe_redacted_2026-05-10T1313Z_loop_runtime_ccmax_git_0cd918d.txt
```

Additional probe run (13:43Z refresh, confirms cc + sysfs PCIe snapshot):

```bash
REDACT=1 SPARK_KNOWN_HOSTS_PER_HOST=1 DS4_GIT_DIR=.git-codex DS4_GIT_WORK_TREE=. ./scripts/spark_probe.sh spark0@aitopatom-9ab9.local | tee /private/tmp/ds4_spark0_probe_redacted_2026-05-10T1339Z_loop_refresh.txt
```

Additional probe run (14:11Z refresh, kernel module metadata snapshot):

```bash
REDACT=1 SPARK_KNOWN_HOSTS_PER_HOST=1 DS4_GIT_DIR=.git-codex DS4_GIT_WORK_TREE=. ./scripts/spark_probe.sh spark0@aitopatom-9ab9.local > /private/tmp/ds4_spark0_probe_redacted_2026-05-10T1411Z_loop_access.txt
```

Notes:

- This output is redacted (`REDACT=1`) to remove IPv4/IPv6/MAC addresses and GPU UUID tokens.
- CUDA compute capability is recorded from both `nvidia-smi` (when the field exists) and the tiny `nvcc` runtime probe (`device0 cc: ...`).
- PCIe link state is captured from `nvidia-smi -q` and sysfs (`/sys/bus/pci/devices/*/current_link_*`) because `lspci -vv` capability fields may be restricted without elevated privileges.

## Probe Excerpts (Redacted)

### Toolchain paths (Spark0, 12:13Z)

```text
== toolchain ==
gcc path: /usr/bin/gcc
g++ path: /usr/bin/g++
cmake path: /usr/bin/cmake
make path: /usr/bin/make
python3 path: /usr/bin/python3
ldd path: /usr/bin/ldd
gcc (Ubuntu 13.3.0-6ubuntu2~24.04.1) 13.3.0
g++ (Ubuntu 13.3.0-6ubuntu2~24.04.1) 13.3.0
cmake version 3.28.3
GNU Make 4.3
Python 3.12.3
ldd (Ubuntu GLIBC 2.39-0ubuntu8.7) 2.39
```

### nvidia-smi fabric/c2c summary (Spark0, 12:43Z)

```text
== nvidia-smi -q fabric/c2c (summary) ==
Product Architecture: Blackwell
Peer Type: Direct Connected
GPU C2C Mode: Enabled
```

### Compute capability + sysfs PCIe snapshot (Spark0, 13:43Z)

```text
== local meta ==
Sun May 10 13:43:17 UTC 2026
git: 393ae50
probe args: spark0@aitopatom-9ab9.local
resolved targets: spark0@aitopatom-9ab9.local

selected compute_cap: 12.1
selected nvcc arch: sm_121
runtime max cc: 12.1

== pci link (sysfs, current/max, post-load) ==
path 000f:00:00.0 current_link_speed: Unknown
path 000f:00:00.0 current_link_width: 0
path 000f:01:00.0 current_link_speed: 2.5 GT/s PCIe
path 000f:01:00.0 current_link_width: 1
```

### Compute capability + open kernel module metadata (Spark0, 14:11Z)

```text
== local meta ==
Sun May 10 14:11:26 UTC 2026
git: a083307
probe args: spark0@aitopatom-9ab9.local
resolved targets: spark0@aitopatom-9ab9.local

selected compute_cap: 12.1
selected nvcc arch: sm_121

== cuda runtime probe (nvcc, no deps) ==
device0 cc: 12.1
runtime max cc: 12.1

== nvidia driver (proc) ==
NVRM version: NVIDIA UNIX Open Kernel Module for aarch64  580.142  Release Build  (dvs-builder@U22-I3-H10-02-1)  Tue Mar  3 19:08:06 UTC 2026

== modinfo nvidia (summary) ==
filename:       /lib/modules/6.17.0-1014-nvidia/kernel/nvidia-580-open/nvidia.ko
version:        580.142
vermagic:       6.17.0-1014-nvidia SMP preempt mod_unload modversions aarch64
```

### Single-target probe (Spark0, 01:38Z)

```text
== local meta ==
Sun May 10 01:38:24 UTC 2026
git: fb13e5b
probe args: aitopatom-9ab9.local
resolved targets: spark0@aitopatom-9ab9.local
```

```text
== nvidia-smi version ==
NVIDIA-SMI version  : 580.142
NVML version        : 580.142
DRIVER version      : 580.142
CUDA Version        : 13.0

== nvidia-smi inventory (index + pci bus) ==
columns: index,gpu_name,pci.bus_id,driver_version,compute_cap,temperature.gpu,pstate,memory.total
0, NVIDIA GB10, 0000000F:01:00.0, 580.142, 12.1, 52, P0, [N/A]

selected compute_cap: 12.1
selected nvcc arch: sm_121
```

```text
== cuda toolkit ==
nvcc path: /usr/local/cuda/bin/nvcc (not on PATH)
Cuda compilation tools, release 13.0, V13.0.88

== nvcc supported gpu arch (capped) ==
compute_120
compute_121

== cuda headers (cuda.h) ==
/usr/local/cuda/include/cuda.h
#define CUDA_VERSION 13000

== cuda runtime probe (nvcc, no deps) ==
nvcc arch: sm_121
cuda driver api version: 13000 (13.0)
cuda runtime api version: 13000 (13.0)
device0 name: NVIDIA GB10
device0 cc: 12.1
device0 global mem (bytes): 128518373376
device0 sms: 48
```

### Single-target probe (Spark0, 10:13Z, `nvcc --list-gpu-code`)

```text
== local meta ==
Sun May 10 10:13:26 UTC 2026
git: 0874be4
probe args: spark0@aitopatom-9ab9.local
resolved targets: spark0@aitopatom-9ab9.local
```

```text
== nvcc supported gpu arch (capped) ==
compute_75
compute_80
compute_86
compute_87
compute_88
compute_89
compute_90
compute_100
compute_110
compute_103
compute_120
compute_121

== nvcc supported gpu code (capped) ==
sm_75
sm_80
sm_86
sm_87
sm_88
sm_89
sm_90
sm_100
sm_110
sm_103
sm_120
sm_121
```

### Single-target probe (Spark0, 10:42Z, nvcc arch sanity-check)

```text
== local meta ==
Sun May 10 10:42:20 UTC 2026
git: acad7c2
probe args: spark0@aitopatom-9ab9.local
resolved targets: spark0@aitopatom-9ab9.local
```

```text
== pci link (sysfs, current/max, post-load) ==
-- 0000000F:01:00.0 -> 000f:01:00.0 --
path: 000f:00:00.0 000f:01:00.0
path 000f:00:00.0 current_link_speed: Unknown
path 000f:00:00.0 current_link_width: 0
path 000f:00:00.0 max_link_speed: 32.0 GT/s PCIe
path 000f:00:00.0 max_link_width: 16
path 000f:01:00.0 current_link_speed: 2.5 GT/s PCIe
path 000f:01:00.0 current_link_width: 1
path 000f:01:00.0 max_link_speed: 2.5 GT/s PCIe
path 000f:01:00.0 max_link_width: 16
```

### Single-target probe (Spark0, 11:44Z, runtime PCI bus id cross-check)

```text
== local meta ==
Sun May 10 11:44:10 UTC 2026
git: 1ea8f17
probe args: spark0@aitopatom-9ab9.local
resolved targets: spark0@aitopatom-9ab9.local
```

```text
== cuda runtime probe (nvcc, no deps) ==
nvcc arch: sm_121
cuda devices: 1
cuda driver api version: 13000 (13.0)
cuda runtime api version: 13000 (13.0)
device0 name: NVIDIA GB10
device0 cc: 12.1
device0 pci bus id: 000F:01:00.0
```

### Single-target probe (Spark0, 02:21Z, PCIe query mismatch warning)

This run uses the updated `scripts/spark_probe.sh` PCIe reporting which warns when `nvidia-smi --query-gpu=pcie.link.*` underreports `max` relative to `nvidia-smi -q` `GPU Link Info` (`Device Max`/`Host Max`).

```text
== nvidia-smi pcie link (max/current) ==
columns: index,pci.bus_id,pcie.link.gen.max,pcie.link.gen.current,pcie.link.width.max,pcie.link.width.current
0, 0000000F:01:00.0, 1, 1, 16, 1
warning: nvidia-smi query pcie.gen.max=1 but -q shows device_max=5 host_max=5 (bus 0000000F:01:00.0)
```

### Single-target probe (Spark0, 04:13Z, CUDA `version.json` snapshot)

This run uses the updated probe output to include `/usr/local/cuda/version.json` (when present) so the toolkit component versions can be captured without relying on package metadata alone.

```text
== local meta ==
Sun May 10 04:13:01 UTC 2026
git: eb46bba
probe args: spark0@aitopatom-9ab9.local
resolved targets: spark0@aitopatom-9ab9.local
```

```text
== cuda toolkit ==
nvcc path: /usr/local/cuda/bin/nvcc (not on PATH)
Cuda compilation tools, release 13.0, V13.0.88

== cuda version.json (capped) ==
{
   "cuda" : {
      "name" : "CUDA SDK",
      "version" : "13.0.3"
   },
   "cuda_cccl" : {
      "name" : "CUDA C++ Core Compute Libraries",
      "version" : "13.0.85"
   },
   "cuda_crt" : {
      "name" : "CUDA crt Compiler for CUDA applications",
      "version" : "13.0.88"
   },
```

### Single-target probe (Spark0, 07:11Z, fresh refresh + toolchain cross-check)

```text
== local meta ==
Sun May 10 07:11:40 UTC 2026
git: 0394b73
probe args: spark0@aitopatom-9ab9.local
resolved targets: spark0@aitopatom-9ab9.local
```

```text
== nvidia-smi inventory (index + pci bus) ==
columns: index,gpu_name,pci.bus_id,driver_version,compute_cap,temperature.gpu,pstate,memory.total
0, NVIDIA GB10, 0000000F:01:00.0, 580.142, 12.1, 48, P0, [N/A]

selected compute_cap: 12.1
selected nvcc arch: sm_121
```

```text
== nvidia-smi pcie link (max/current) ==
columns: index,pci.bus_id,pcie.link.gen.max,pcie.link.gen.current,pcie.link.width.max,pcie.link.width.current
0, 0000000F:01:00.0, 1, 1, 16, 1
warning: nvidia-smi query pcie.gen.max=1 but -q shows device_max=5 host_max=5 (bus 0000000F:01:00.0)
```

```text
== cuda headers (cuda.h) ==
/usr/local/cuda/include/cuda.h
#define CUDA_VERSION 13000

== cuda runtime probe (nvcc, no deps) ==
device0 name: NVIDIA GB10
device0 cc: 12.1
```

### Single-target probe (Spark0, 07:43Z, GPU/host max PCIe query)

This run adds an optional `nvidia-smi` PCIe query snapshot to make `GPU Link Info` (`Device Max`/`Host Max`) fields available in CSV form when supported.

```text
== local meta ==
Sun May 10 07:43:26 UTC 2026
git: d68bc45
probe args: spark0@aitopatom-9ab9.local
resolved targets: spark0@aitopatom-9ab9.local
```

```text
== nvidia-smi pcie link (max/current) ==
columns: index,pci.bus_id,pcie.link.gen.max,pcie.link.gen.current,pcie.link.width.max,pcie.link.width.current
0, 0000000F:01:00.0, 1, 1, 16, 1
warning: nvidia-smi query pcie.gen.max=1 but -q shows device_max=5 host_max=5 (bus 0000000F:01:00.0)

== nvidia-smi pcie link (gpu/host max, optional) ==
columns: index,pci.bus_id,pcie.link.gen.gpucurrent,pcie.link.gen.gpumax,pcie.link.gen.hostmax,pcie.link.width.current,pcie.link.width.max
0, 0000000F:01:00.0, 1, 5, 5, 1, 16
```

### Single-target probe (Spark0, 08:13Z refresh, `origin/main` `git: 3728f20`)

```text
== local meta ==
Sun May 10 08:13:33 UTC 2026
git: 3728f20
probe args: spark0@aitopatom-9ab9.local
resolved targets: spark0@aitopatom-9ab9.local
```

```text
== nvidia-smi version ==
NVIDIA-SMI version  : 580.142
NVML version        : 580.142
DRIVER version      : 580.142
CUDA Version        : 13.0

== nvidia-smi inventory (index + pci bus) ==
columns: index,gpu_name,pci.bus_id,driver_version,compute_cap,temperature.gpu,pstate,memory.total
0, NVIDIA GB10, 0000000F:01:00.0, 580.142, 12.1, 49, P0, [N/A]

selected compute_cap: 12.1
selected nvcc arch: sm_121
```

```text
== nvidia-smi pcie link (max/current) ==
columns: index,pci.bus_id,pcie.link.gen.max,pcie.link.gen.current,pcie.link.width.max,pcie.link.width.current
0, 0000000F:01:00.0, 1, 1, 16, 1
warning: nvidia-smi query pcie.gen.max=1 but -q shows device_max=5 host_max=5 (bus 0000000F:01:00.0)

== nvidia-smi pcie link (gpu/host max, optional) ==
columns: index,pci.bus_id,pcie.link.gen.gpucurrent,pcie.link.gen.gpumax,pcie.link.gen.hostmax,pcie.link.width.current,pcie.link.width.max
0, 0000000F:01:00.0, 1, 5, 5, 1, 16

== pci link (sysfs, current/max) ==
-- 0000000F:01:00.0 -> 000f:01:00.0 --
sysfs: /sys/devices/pci000f:00/000f:00:00.0/000f:01:00.0
path: 000f:00:00.0 000f:01:00.0
path 000f:00:00.0 max_link_speed: 32.0 GT/s PCIe
path 000f:00:00.0 max_link_width: 16
path 000f:01:00.0 current_link_speed: 2.5 GT/s PCIe
path 000f:01:00.0 current_link_width: 1
path 000f:01:00.0 max_link_speed: 2.5 GT/s PCIe
path 000f:01:00.0 max_link_width: 16
```

```text
== cuda toolkit ==
nvcc path: /usr/local/cuda/bin/nvcc (not on PATH)
Cuda compilation tools, release 13.0, V13.0.88

== cuda version.json (capped) ==
{
   "cuda" : {
      "name" : "CUDA SDK",
   "version" : "13.0.3"
   },
```

### Single-target probe (Spark0, 08:43Z refresh, `origin/main` `git: 3a42299`)

```text
== local meta ==
Sun May 10 08:43:23 UTC 2026
git: 3a42299
probe args: spark0@aitopatom-9ab9.local
resolved targets: spark0@aitopatom-9ab9.local
```

```text
== nvidia-smi inventory (index + pci bus) ==
columns: index,gpu_name,pci.bus_id,driver_version,compute_cap,temperature.gpu,pstate,memory.total
0, NVIDIA GB10, 0000000F:01:00.0, 580.142, 12.1, 54, P0, [N/A]

selected compute_cap: 12.1
selected nvcc arch: sm_121
```

```text
== cuda version.json (capped) ==
{
   "cuda" : {
      "name" : "CUDA SDK",
      "version" : "13.0.3"
   },
   "cuda_nvcc" : {
      "name" : "CUDA NVCC",
      "version" : "13.0.88"
   },
```

### Single-target probe (Spark0, 09:13Z refresh, loop-filtered storage output, `git: afbc122`)

```text
== local meta ==
Sun May 10 09:13:41 UTC 2026
git: afbc122
probe args: spark0@aitopatom-9ab9.local
resolved targets: spark0@aitopatom-9ab9.local
```

```text
== nvidia-smi inventory (index + pci bus) ==
columns: index,gpu_name,pci.bus_id,driver_version,compute_cap,temperature.gpu,pstate,memory.total
0, NVIDIA GB10, 0000000F:01:00.0, 580.142, 12.1, 66, P0, [N/A]

selected compute_cap: 12.1
selected nvcc arch: sm_121

== nvidia-smi pcie link (max/current) ==
columns: index,pci.bus_id,pcie.link.gen.max,pcie.link.gen.current,pcie.link.width.max,pcie.link.width.current
0, 0000000F:01:00.0, 1, 1, 16, 1
warning: nvidia-smi query pcie.gen.max=1 but -q shows device_max=5 host_max=5 (bus 0000000F:01:00.0)

== pci link (sysfs, current/max) ==
-- 0000000F:01:00.0 -> 000f:01:00.0 --
path: 000f:00:00.0 000f:01:00.0
path 000f:00:00.0 current_link_speed: Unknown
path 000f:00:00.0 current_link_width: 0
path 000f:00:00.0 max_link_speed: 32.0 GT/s PCIe
path 000f:00:00.0 max_link_width: 16
path 000f:01:00.0 current_link_speed: 2.5 GT/s PCIe
path 000f:01:00.0 current_link_width: 1
path 000f:01:00.0 max_link_speed: 2.5 GT/s PCIe
path 000f:01:00.0 max_link_width: 16
```

```text
== storage ==
Filesystem      Size  Used Avail Use% Mounted on
/dev/nvme0n1p2  3.7T  123G  3.4T   4% /
NAME         SIZE TYPE MOUNTPOINTS
nvme0n1      3.7T disk
|-nvme0n1p1  512M part /boot/efi
`-nvme0n1p2  3.7T part /

== disks (summary) ==
NAME     SIZE MODEL                      ROTA TYPE
nvme0n1  3.7T SAMSUNG MZALC4T0HBL1-00B07    0 disk
```

### Multi-target probe (Spark0 ok, Spark1 unreachable)

```text
== local meta ==
Sun May 10 01:11:45 UTC 2026
git: 3b928be
probe args: aitopatom-9ab9.local spark1.local
resolved targets: spark0@aitopatom-9ab9.local spark0@spark1.local

== target: spark0@spark1.local ==
ssh: Could not resolve hostname spark1.local: nodename nor servname provided, or not known
ssh: failed rc=255

== probe summary ==
ssh failures: 1
```

```text
== probe meta ==
Sun May 10 01:07:18 UTC 2026

== nvidia-smi version ==
NVIDIA-SMI version  : 580.142
NVML version        : 580.142
DRIVER version      : 580.142
CUDA Version        : 13.0

== nvidia-smi inventory (index + pci bus) ==
columns: index,gpu_name,pci.bus_id,driver_version,compute_cap,temperature.gpu,pstate,memory.total
0, NVIDIA GB10, 0000000F:01:00.0, 580.142, 12.1, 55, P0, [N/A]

== nvidia-smi pci ids (optional) ==
columns: index,pci.bus_id,pci.device_id,pci.sub_device_id
0, 0000000F:01:00.0, 0x2E1210DE, 0x10DE
selected compute_cap: 12.1
selected nvcc arch: sm_121

== nvidia-smi cuda version ==
CUDA Version: 13.0
```

```text
== nvidia-smi pcie link (max/current) ==
columns: index,pci.bus_id,pcie.link.gen.max,pcie.link.gen.current,pcie.link.width.max,pcie.link.width.current
0, 0000000F:01:00.0, 1, 1, 16, 1

== nvidia-smi -q pci link (capped) ==
        GPU Link Info
            PCIe Generation
                Max                                    : 1
                Current                                : 1
                Device Current                         : 1
                Device Max                             : 5
                Host Max                               : 5
            Link Width
                Max                                    : 16x
                Current                                : 1x

== pci link (sysfs, current/max) ==
-- 0000000F:01:00.0 -> 000f:01:00.0 --
path: 000f:00:00.0 000f:01:00.0
path 000f:00:00.0 max_link_speed: 32.0 GT/s PCIe
path 000f:00:00.0 max_link_width: 16
path 000f:01:00.0 current_link_speed: 2.5 GT/s PCIe
path 000f:01:00.0 current_link_width: 1
path 000f:01:00.0 max_link_speed: 2.5 GT/s PCIe
path 000f:01:00.0 max_link_width: 16
```

```text
== cuda toolkit ==
nvcc path: /usr/local/cuda/bin/nvcc (not on PATH)
Cuda compilation tools, release 13.0, V13.0.88

== nvcc supported gpu arch (capped) ==
compute_120
compute_121

== cuda headers (cuda.h) ==
/usr/local/cuda/include/cuda.h
#define CUDA_VERSION 13000

== cuda runtime probe (nvcc, no deps) ==
cuda driver api version: 13000 (13.0)
cuda runtime api version: 13000 (13.0)
device0 name: NVIDIA GB10
device0 cc: 12.1
device0 global mem (bytes): 128518373376
device0 sms: 48
```

```text
== cuda runtime probe (nvcc, no deps) ==
nvcc arch: sm_121
cuda devices: 1
device0 cc: 12.1
runtime max cc: 12.1
```

```text
== filesystems (type + opts) ==
/      ext4   rw,relatime,errors=remount-ro

== storage ==
Filesystem      Size  Used Avail Use% Mounted on
/dev/nvme0n1p2  3.7T  123G  3.4T   4% /

== disks (summary) ==
nvme0n1   3.7T SAMSUNG MZALC4T0HBL1-00B07    0 disk
```
