# Spark0 Probe (2026-05-10)

Host:

- mDNS name: `aitopatom-9ab9.local`
- Linux hostname: `aitopatom-9ab9`
- User: `spark0`

Commands run from the Mac:

```bash
REDACT=1 SPARK_KNOWN_HOSTS_PER_HOST=1 DS4_GIT_DIR=.git-codex DS4_GIT_WORK_TREE=. ./scripts/spark_probe.sh spark0@aitopatom-9ab9.local | tee /private/tmp/ds4_spark0_probe_redacted_2026-05-10T0007Z_loop_v11.txt
```

Additional probe run (later the same day):

```bash
REDACT=1 SPARK_KNOWN_HOSTS_PER_HOST=1 DS4_GIT_DIR=.git-codex DS4_GIT_WORK_TREE=. ./scripts/spark_probe.sh spark0@aitopatom-9ab9.local | tee /private/tmp/ds4_spark0_probe_redacted_2026-05-10T0109Z_loop_v4.txt
```

Notes:

- This output is redacted (`REDACT=1`) to remove IPv4/IPv6/MAC addresses and GPU UUID tokens.
- CUDA compute capability is recorded from both `nvidia-smi` (when the field exists) and the tiny `nvcc` runtime probe (`device0 cc: ...`).
- PCIe link state is captured from `nvidia-smi -q` and sysfs (`/sys/bus/pci/devices/*/current_link_*`) because `lspci -vv` capability fields may be restricted without elevated privileges.

## Probe Excerpts (Redacted)

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
== filesystems (type + opts) ==
/      ext4   rw,relatime,errors=remount-ro

== storage ==
Filesystem      Size  Used Avail Use% Mounted on
/dev/nvme0n1p2  3.7T  123G  3.4T   4% /

== disks (summary) ==
nvme0n1   3.7T SAMSUNG MZALC4T0HBL1-00B07    0 disk
```
