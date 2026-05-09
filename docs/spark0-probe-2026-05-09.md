# Spark0 Probe (2026-05-09)

Host:

- mDNS name: `aitopatom-9ab9.local`
- Linux hostname: `aitopatom-9ab9`
- User: `spark0`

Commands run from the Mac:

```bash
REDACT=1 SPARK_KNOWN_HOSTS_PER_HOST=1 ./scripts/spark_probe.sh spark0@aitopatom-9ab9.local | tee /private/tmp/ds4_spark0_probe_redacted_2026-05-09_14z.txt
```

Notes:

- This output is redacted (`REDACT=1`) to remove IPv4/IPv6/MAC addresses and GPU UUID tokens.
- PCIe link state is captured from both `nvidia-smi` and sysfs (`/sys/bus/pci/devices/*/current_link_*`) because `lspci -vv` capability fields can be restricted without root on this host.

## Probe Excerpts (Redacted)

```text
== nvidia-smi inventory (index + pci bus) ==
columns: index,gpu_name,pci.bus_id,driver_version,compute_cap,temperature.gpu,pstate,memory.total
0, NVIDIA GB10, 0000000F:01:00.0, 580.142, 12.1, 48, P0, [N/A]
selected compute_cap: 12.1
selected nvcc arch: sm_121

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
