# Spark0 Probe (2026-05-09)

Host:

- mDNS name: `aitopatom-9ab9.local`
- Linux hostname: `aitopatom-9ab9`
- User: `spark0`

Commands run from the Mac:

```bash
REDACT=1 SPARK_KNOWN_HOSTS_PER_HOST=1 ./scripts/spark_probe.sh spark0@aitopatom-9ab9.local | tee /private/tmp/ds4_spark0_probe_redacted_2026-05-09T144215Z_probe11.txt
```

Notes:

- This output is redacted (`REDACT=1`) to remove IPv4/IPv6/MAC addresses and GPU UUID tokens.
- PCIe link state is captured from both `nvidia-smi` and sysfs (`/sys/bus/pci/devices/*/current_link_*`) because `lspci -vv` capability fields can be restricted without root on this host.
- The probe prints a second `post-load` PCIe link snapshot after the CUDA runtime probe, to check whether link speed/width changes under GPU activity.

## Probe Excerpts (Redacted)

```text
== pci nvidia (numeric ids) ==
0000:00:00.0 PCI bridge [0604]: NVIDIA Corporation Device [10de:22ce] (rev 01)
000f:01:00.0 VGA compatible controller [0300]: NVIDIA Corporation Device [10de:2e12] (rev a1)

== nvidia-smi inventory (index + pci bus) ==
columns: index,gpu_name,pci.bus_id,driver_version,compute_cap,temperature.gpu,pstate,memory.total
0, NVIDIA GB10, 0000000F:01:00.0, 580.142, 12.1, 48, P0, [N/A]
selected compute_cap: 12.1
selected nvcc arch: sm_121

== nvidia-smi pci ids (optional) ==
columns: index,pci.bus_id,pci.device_id,pci.sub_device_id
0, 0000000F:01:00.0, 0x2E1210DE, 0x10DE

== nvidia-smi cuda version ==
CUDA Version: 13.0

== nvidia-smi pcie link (max/current) ==
columns: index,pci.bus_id,pcie.link.gen.max,pcie.link.gen.current,pcie.link.width.max,pcie.link.width.current
0, 0000000F:01:00.0, 1, 1, 16, 1

== pci link (sysfs, current/max) ==
-- 0000000F:01:00.0 -> 000f:01:00.0 --
current_link_speed: 2.5 GT/s PCIe
current_link_width: 1
max_link_speed: 2.5 GT/s PCIe
max_link_width: 16
```

```text
== cuda toolkit ==
Cuda compilation tools, release 13.0, V13.0.88

== cuda headers (cuda.h) ==
#define CUDA_VERSION 13000

== cuda runtime probe (nvcc, no deps) ==
nvcc arch: sm_121
cuda driver api version: 13000
cuda runtime api version: 13000
device0 name: NVIDIA GB10
device0 cc: 12.1
device0 global mem (bytes): 128518373376
device0 sms: 48

== nvidia-smi pcie link (max/current, post-load) ==
columns: index,pci.bus_id,pcie.link.gen.max,pcie.link.gen.current,pcie.link.width.max,pcie.link.width.current
0, 0000000F:01:00.0, 1, 1, 16, 1

== pci link (sysfs, current/max, post-load) ==
-- 0000000F:01:00.0 -> 000f:01:00.0 --
current_link_speed: 2.5 GT/s PCIe
current_link_width: 1
max_link_speed: 2.5 GT/s PCIe
max_link_width: 16
```

## Update: Probe Refresh (2026-05-09 15:42Z)

Commands run from the Mac:

```bash
REDACT=1 SPARK_KNOWN_HOSTS_PER_HOST=1 ./scripts/spark_probe.sh spark0@aitopatom-9ab9.local | tee /private/tmp/ds4_spark0_probe_redacted_2026-05-09T154208Z_probe12.txt
```

```text
== network links (no IPs) ==
-- ethtool enP7s7 --
	Speed: 10000Mb/s
	Duplex: Full
	Auto-negotiation: on
	Link detected: yes
```

```text
== filesystems (type + opts) ==
/      ext4   rw,relatime,errors=remount-ro

== storage ==
Filesystem      Size  Used Avail Use% Mounted on
/dev/nvme0n1p2  3.7T  126G  3.4T   4% /

== disks (summary) ==
nvme0n1   3.7T SAMSUNG MZALC4T0HBL1-00B07    0 disk
```

## Update: Probe Refresh (2026-05-09 16:10Z)

Commands run from the Mac:

```bash
REDACT=1 SPARK_KNOWN_HOSTS_PER_HOST=1 DS4_GIT_DIR=/private/tmp/ds4_git_spark_access_probe_loop_1778342741/.git DS4_GIT_WORK_TREE=/private/tmp/ds4_git_spark_access_probe_loop_1778342741 ./scripts/spark_probe.sh spark0@aitopatom-9ab9.local | tee /private/tmp/ds4_spark0_probe_redacted_2026-05-09T161030Z_probe13.txt
```

```text
== local meta ==
Sat May  9 16:10:30 UTC 2026
git: 51720ee
probe targets: spark0@aitopatom-9ab9.local
ssh opts: -o BatchMode=yes -o ConnectTimeout=10 -o StrictHostKeyChecking=accept-new -o ServerAliveInterval=5 -o ServerAliveCountMax=2
```

```text
== pci link (sysfs, current/max) ==
-- 0000000F:01:00.0 -> 000f:01:00.0 --
vendor: 0x10de
device: 0x2e12
subsystem_vendor: 0x10de
subsystem_device: 0x0000
class: 0x030000
```

## Update: Probe Refresh (2026-05-09 16:39Z)

Commands run from the Mac:

```bash
REDACT=1 SPARK_KNOWN_HOSTS_PER_HOST=1 ./scripts/spark_probe.sh spark0@aitopatom-9ab9.local | tee /private/tmp/ds4_spark0_probe_redacted_2026-05-09T163948Z_probe16.txt
```

```text
== local meta ==
Sat May  9 16:39:48 UTC 2026
git: c8f2283
```

```text
== lspci gpu link state (capped) ==
-- 000f:01:00.0 --
no LnkCap/LnkSta fields found; header:
000f:01:00.0 VGA compatible controller: NVIDIA Corporation Device 2e12 (rev a1) (prog-if 00 [VGA controller])
```

```text
== nvidia-smi pcie link (max/current) ==
columns: index,pci.bus_id,pcie.link.gen.max,pcie.link.gen.current,pcie.link.width.max,pcie.link.width.current
0, 0000000F:01:00.0, 1, 1, 16, 1
```

```text
== cuda runtime probe (nvcc, no deps) ==
nvcc arch: sm_121
device0 cc: 12.1
```

## Update: Probe Refresh (2026-05-09 17:35Z)

Commands run from the Mac:

```bash
REDACT=1 SPARK_KNOWN_HOSTS_PER_HOST=1 ./scripts/spark_probe.sh spark0@aitopatom-9ab9.local | tee /private/tmp/ds4_spark0_probe_redacted_2026-05-09T1735Z_probe8.txt
```

```text
== local meta ==
Sat May  9 17:35:39 UTC 2026
git: ad143d0
probe targets: spark0@aitopatom-9ab9.local
known_hosts: spark0@aitopatom-9ab9.local -> /private/tmp/ds4_spark_known_hosts.aitopatom-9ab9.local
```

```text
== nvidia-smi inventory (index + pci bus) ==
columns: index,gpu_name,pci.bus_id,driver_version,compute_cap,temperature.gpu,pstate,memory.total
0, NVIDIA GB10, 0000000F:01:00.0, 580.142, 12.1, 47, P0, [N/A]
selected compute_cap: 12.1
selected nvcc arch: sm_121

== nvidia-smi cuda version ==
CUDA Version: 13.0
```

```text
== cuda toolkit ==
Cuda compilation tools, release 13.0, V13.0.88

== nvcc supported gpu arch (capped) ==
compute_120
compute_121

== cuda runtime probe (nvcc, no deps) ==
nvcc arch: sm_121
cuda driver api version: 13000
cuda runtime api version: 13000
device0 name: NVIDIA GB10
device0 cc: 12.1
device0 global mem (bytes): 128518373376
device0 sms: 48
```

## Update: Probe Refresh (2026-05-09 18:11Z)

Commands run from the Mac:

```bash
REDACT=1 SPARK_KNOWN_HOSTS_PER_HOST=1 ./scripts/spark_probe.sh spark0@aitopatom-9ab9.local | tee /private/tmp/ds4_spark0_probe_redacted_2026-05-09T1815Z_loop_v2c.txt
```

## Update: Probe Refresh (2026-05-09 19:06Z)

Commands run from the Mac:

```bash
REDACT=1 SPARK_KNOWN_HOSTS_PER_HOST=1 ./scripts/spark_probe.sh spark0@aitopatom-9ab9.local | tee /private/tmp/ds4_spark0_probe_redacted_2026-05-09T1906Z_loop_v4.txt
```

```text
== local meta ==
Sat May  9 19:06:32 UTC 2026
git: 49403f0
probe targets: spark0@aitopatom-9ab9.local
known_hosts: spark0@aitopatom-9ab9.local -> /private/tmp/ds4_spark_known_hosts.aitopatom-9ab9.local
```

```text
== nvidia-smi inventory (index + pci bus) ==
columns: index,gpu_name,pci.bus_id,driver_version,compute_cap,temperature.gpu,pstate,memory.total
0, NVIDIA GB10, 0000000F:01:00.0, 580.142, 12.1, 47, P0, [N/A]
selected compute_cap: 12.1
selected nvcc arch: sm_121

== nvidia-smi cuda version ==
CUDA Version: 13.0
```

```text
== cuda toolkit ==
nvcc path: /usr/local/cuda/bin/nvcc (not on PATH)
Cuda compilation tools, release 13.0, V13.0.88

== cuda runtime probe (nvcc, no deps) ==
nvcc arch: sm_121
cuda driver api version: 13000
cuda runtime api version: 13000
device0 name: NVIDIA GB10
device0 cc: 12.1
```

```text
== pci link (sysfs, current/max) ==
-- 0000000F:01:00.0 -> 000f:01:00.0 --
sysfs: /sys/devices/pci000f:00/000f:00:00.0/000f:01:00.0
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
== cuda toolkit ==
nvcc path: /usr/local/cuda/bin/nvcc (not on PATH)
Cuda compilation tools, release 13.0, V13.0.88
```

## Update: Probe Refresh (2026-05-09 18:39Z)

Commands run from the Mac:

```bash
REDACT=1 SPARK_KNOWN_HOSTS_PER_HOST=1 ./scripts/spark_probe.sh spark0@aitopatom-9ab9.local | tee /private/tmp/ds4_spark0_probe_redacted_2026-05-09T1841Z_loop_v3.txt
```

```text
== local meta ==
Sat May  9 18:39:08 UTC 2026
git: a3b6ed6
probe targets: spark0@aitopatom-9ab9.local
known_hosts: spark0@aitopatom-9ab9.local -> /private/tmp/ds4_spark_known_hosts.aitopatom-9ab9.local
```

```text
== memory ==
               total        used        free      shared  buff/cache   available
Mem:           119Gi        90Gi       5.1Gi       465Mi        25Gi        29Gi
Swap:           15Gi       743Mi        15Gi
```

```text
== network links (no IPs) ==
-- ethtool enP7s7 --
driver: r8127
version: 11.014.00-NAPI
bus-info: 0007:01:00.0
-- ethtool wlP9s9 --
driver: mt7925e
version: 6.17.0-1014-nvidia
firmware-version: ____000000-20251210093025
bus-info: 0009:01:00.0
```

```text
== rdma (roce/infiniband, optional) ==
-- roceP2p1s0f0 --
hca_type: MT4129
port1: state=1: DOWN phys=3: Disabled rate=40 Gb/sec (4X QDR) layer=Ethernet
-- rocep1s0f0 --
hca_type: MT4129
port1: state=1: DOWN phys=3: Disabled rate=40 Gb/sec (4X QDR) layer=Ethernet
```

## Update: Probe Refresh (2026-05-09 19:39Z)

Commands run from the Mac:

```bash
REDACT=1 SPARK_KNOWN_HOSTS_PER_HOST=1 DS4_GIT_DIR=.git-codex DS4_GIT_WORK_TREE=. ./scripts/spark_probe.sh spark0@aitopatom-9ab9.local | tee /private/tmp/ds4_spark0_probe_redacted_2026-05-09T1939Z_loop_v5.txt
```

```text
== local meta ==
Sat May  9 19:38:56 UTC 2026
git: 3fd13b3
probe targets: spark0@aitopatom-9ab9.local
known_hosts: spark0@aitopatom-9ab9.local -> /private/tmp/ds4_spark_known_hosts.aitopatom-9ab9.local
```

```text
== nvidia-smi inventory (index + pci bus) ==
columns: index,gpu_name,pci.bus_id,driver_version,compute_cap,temperature.gpu,pstate,memory.total
0, NVIDIA GB10, 0000000F:01:00.0, 580.142, 12.1, 47, P0, [N/A]
selected compute_cap: 12.1
selected nvcc arch: sm_121

== nvidia-smi pcie link (max/current) ==
columns: index,pci.bus_id,pcie.link.gen.max,pcie.link.gen.current,pcie.link.width.max,pcie.link.width.current
0, 0000000F:01:00.0, 1, 1, 16, 1

== pci link (sysfs, current/max) ==
-- 0000000F:01:00.0 -> 000f:01:00.0 --
sysfs: /sys/devices/pci000f:00/000f:00:00.0/000f:01:00.0
path: 000f:00:00.0 000f:01:00.0
path 000f:00:00.0 max_link_speed: 32.0 GT/s PCIe
path 000f:00:00.0 max_link_width: 16
path 000f:01:00.0 max_link_speed: 2.5 GT/s PCIe
path 000f:01:00.0 max_link_width: 16
path 000f:01:00.0 current_link_speed: 2.5 GT/s PCIe
path 000f:01:00.0 current_link_width: 1
```

```text
== cuda toolkit ==
Cuda compilation tools, release 13.0, V13.0.88

== cuda runtime probe (nvcc, no deps) ==
device0 cc: 12.1
```
