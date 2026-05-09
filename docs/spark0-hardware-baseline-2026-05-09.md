# Spark0 Hardware Baseline

Date: 2026-05-09 (UTC) from the Mac workspace.

Host:

- mDNS name used for probes: `aitopatom-9ab9.local`
- Linux hostname: `aitopatom-9ab9`
- Login user used for probes: `spark0`

Commands run:

```bash
REDACT=1 ./scripts/spark_probe.sh spark0@aitopatom-9ab9.local > /private/tmp/spark0_probe_redacted_2026-05-09_01.txt
```

High-level facts observed (from the probe output below):

- OS: Ubuntu 24.04.4 LTS (Noble)
- Kernel: `6.17.0-1014-nvidia`
- Architecture: `aarch64` (little-endian)
- CPU: 20 cores total (10x Cortex-X925 + 10x Cortex-A725)
- Memory: 119 GiB total RAM, 15 GiB swap
- GPU: `NVIDIA GB10`
- Driver (nvidia-smi): `580.142`
- CUDA version reported by nvidia-smi: `13.0`
- CUDA compute capability (nvidia-smi + nvcc probe): `12.1`
- CUDA toolkit (nvcc): 13.0 (V13.0.88)
- `nvcc` path: `/usr/local/cuda/bin/nvcc` (not on default `PATH`)
- `ptxas` path: `/usr/local/cuda/bin/ptxas`
- CUDA driver/runtime API version (nvcc probe): `13000` (CUDA 13.0)
- Wired NIC: `enP7s7`, MTU 9000, link speed 10Gb/s (ethtool)
- Default route: via Wi-Fi during probe
- Root filesystem: ~3.7 TiB NVMe, model `SAMSUNG MZALC4T0HBL1-00B07`
- NVIDIA driver (proc): Open Kernel Module `580.142` build timestamp `2026-03-03`
- cuDNN: not detected (no headers/libs found via probe)

## Spark Probe Output (Redacted)

Notes:

- This output is redacted (`REDACT=1`) to remove IPv4/IPv6/MAC addresses.
- Re-run without `REDACT=1` only for local debugging; do not commit raw network identifiers.

## Update: Probe Refresh (2026-05-09 03:48Z)

Commands run:

```bash
REDACT=1 DS4_GIT_DIR=/private/tmp/ds4_git/.git ./scripts/spark_probe.sh spark0@aitopatom-9ab9.local > /private/tmp/spark0_probe_redacted_2026-05-09_07.txt
```

Notes:

- This output is redacted (`REDACT=1`) to remove IPv4/IPv6/MAC addresses and GPU UUID tokens.

```text
== local meta ==
Sat May  9 03:48:26 UTC 2026
git: 28dad98
probe target: spark0@aitopatom-9ab9.local

== probe meta ==
Sat May  9 03:48:26 UTC 2026
target user: spark0

== identity ==
aitopatom-9ab9
uid=1000(spark0) gid=1000(spark0) groups=1000(spark0),4(adm),27(sudo),29(audio),30(dip),46(plugdev),100(users),122(lpadmin)
Linux aitopatom-9ab9 6.17.0-1014-nvidia #14-Ubuntu SMP PREEMPT_DYNAMIC Tue Mar 17 19:01:40 UTC 2026 aarch64 aarch64 aarch64 GNU/Linux

== os ==
PRETTY_NAME="Ubuntu 24.04.4 LTS"
NAME="Ubuntu"
VERSION_ID="24.04"
VERSION="24.04.4 LTS (Noble Numbat)"
VERSION_CODENAME=noble
ID=ubuntu
ID_LIKE=debian
HOME_URL="https://www.ubuntu.com/"
SUPPORT_URL="https://help.ubuntu.com/"
BUG_REPORT_URL="https://bugs.launchpad.net/ubuntu/"
PRIVACY_POLICY_URL="https://www.ubuntu.com/legal/terms-and-policies/privacy-policy"
UBUNTU_CODENAME=noble
LOGO=ubuntu-logo

== cpu ==
Architecture:                            aarch64
CPU op-mode(s):                          64-bit
Byte Order:                              Little Endian
CPU(s):                                  20
On-line CPU(s) list:                     0-19
Vendor ID:                               ARM
Model name:                              Cortex-X925
Model:                                   1
Thread(s) per core:                      1
Core(s) per socket:                      10
Socket(s):                               1
Stepping:                                r0p1
Frequency boost:                         disabled
CPU(s) scaling MHz:                      100%
CPU max MHz:                             3900.0000
CPU min MHz:                             1378.0000
BogoMIPS:                                2000.00
Flags:                                   fp asimd evtstrm aes pmull sha1 sha2 crc32 atomics fphp asimdhp cpuid asimdrdm jscvt fcma lrcpc dcpop sha3 sm3 sm4 asimddp sha512 sve asimdfhm dit uscat ilrcpc flagm sb paca pacg dcpodp sve2 sveaes svepmull svebitperm svesha3 svesm4 flagm2 frint svei8mm svebf16 i8mm bf16 dgh bti ecv afp wfxt
Model name:                              Cortex-A725
Model:                                   1
Thread(s) per core:                      1
Core(s) per socket:                      10
Socket(s):                               1
Stepping:                                r0p1
Frequency boost:                         disabled
CPU(s) scaling MHz:                      100%
CPU max MHz:                             2808.0000
CPU min MHz:                             338.0000
BogoMIPS:                                2000.00
Flags:                                   fp asimd evtstrm aes pmull sha1 sha2 crc32 atomics fphp asimdhp cpuid asimdrdm jscvt fcma lrcpc dcpop sha3 sm3 sm4 asimddp sha512 sve asimdfhm dit uscat ilrcpc flagm sb paca pacg dcpodp sve2 sveaes svepmull svebitperm svesha3 svesm4 flagm2 frint svei8mm svebf16 i8mm bf16 dgh bti ecv afp wfxt
L1d cache:                               1.3 MiB (20 instances)
L1i cache:                               1.3 MiB (20 instances)
L2 cache:                                25 MiB (20 instances)
L3 cache:                                24 MiB (2 instances)
NUMA node(s):                            1
NUMA node0 CPU(s):                       0-19
Vulnerability Gather data sampling:      Not affected
Vulnerability Ghostwrite:                Not affected
Vulnerability Indirect target selection: Not affected
Vulnerability Itlb multihit:             Not affected
Vulnerability L1tf:                      Not affected
Vulnerability Mds:                       Not affected
Vulnerability Meltdown:                  Not affected
Vulnerability Mmio stale data:           Not affected
Vulnerability Reg file data sampling:    Not affected
Vulnerability Retbleed:                  Not affected
Vulnerability Spec rstack overflow:      Not affected
Vulnerability Spec store bypass:         Mitigation; Speculative Store Bypass disabled via prctl
Vulnerability Spectre v1:                Mitigation; __user pointer sanitization
Vulnerability Spectre v2:                Mitigation; CSV2, BHB
Vulnerability Srbds:                     Not affected
Vulnerability Tsa:                       Not affected
Vulnerability Tsx async abort:           Not affected
Vulnerability Vmscape:                   Not affected

== memory ==
               total        used        free      shared  buff/cache   available
Mem:           119Gi       4.1Gi       114Gi        61Mi       2.5Gi       115Gi
Swap:           15Gi          0B        15Gi

== toolchain ==
gcc (Ubuntu 13.3.0-6ubuntu2~24.04.1) 13.3.0
g++ (Ubuntu 13.3.0-6ubuntu2~24.04.1) 13.3.0
cmake version 3.28.3
GNU Make 4.3
Python 3.12.3

== pci nvidia ==
0000:00:00.0 PCI bridge: NVIDIA Corporation Device 22ce (rev 01)
0002:00:00.0 PCI bridge: NVIDIA Corporation Device 22ce (rev 01)
0004:00:00.0 PCI bridge: NVIDIA Corporation Device 22ce (rev 01)
0007:00:00.0 PCI bridge: NVIDIA Corporation Device 22d0 (rev 01)
0009:00:00.0 PCI bridge: NVIDIA Corporation Device 22d0 (rev 01)
000f:00:00.0 PCI bridge: NVIDIA Corporation Device 22d1
000f:01:00.0 VGA compatible controller: NVIDIA Corporation Device 2e12 (rev a1)

== nvidia-smi query (driver + compute capability) ==
NVIDIA GB10, 580.142, 12.1, 48, P0, [N/A]

== nvidia-smi cuda version ==
CUDA Version                                           : 13.0

== nvidia-smi gpu list ==
GPU 0: NVIDIA GB10 (UUID: <redacted-gpu-uuid>)

== cuda toolkit ==
nvcc: NVIDIA (R) Cuda compiler driver
Copyright (c) 2005-2025 NVIDIA Corporation
Built on Wed_Aug_20_01:57:39_PM_PDT_2025
Cuda compilation tools, release 13.0, V13.0.88
Build cuda_13.0.r13.0/compiler.36424714_0
-rwxr-xr-x 1 root root 24513032 Aug 21  2025 /usr/local/cuda/bin/nvcc
ptxas: /usr/local/cuda/bin/ptxas
ptxas: NVIDIA (R) Ptx optimizing assembler
Copyright (c) 2005-2025 NVIDIA Corporation
Built on Wed_Aug_20_01:53:56_PM_PDT_2025
lrwxrwxrwx 1 root root 22 Dec 17 21:40 /usr/local/cuda -> /etc/alternatives/cuda
/usr/local/cuda-13.0

== cuda libraries (ldconfig, first hits) ==
	libcudart.so.13 (libc6,AArch64) => /usr/local/cuda/targets/sbsa-linux/lib/libcudart.so.13
	libcudart.so (libc6,AArch64) => /usr/local/cuda/targets/sbsa-linux/lib/libcudart.so
	libcuda.so.1 (libc6,AArch64) => /lib/aarch64-linux-gnu/libcuda.so.1

== cudnn (headers + libs) ==
cudnn headers not found


== cuda runtime probe (nvcc, no deps) ==
cuda devices: 1
cuda driver api version: 13000
cuda runtime api version: 13000
device0 name: NVIDIA GB10
device0 cc: 12.1
device0 global mem (bytes): 128518373376

== network ==
lo               UNKNOWN        <redacted-ipv4>/8 
enP7s7           UP             <redacted-ipv4>/24 
wlP9s9           UP             <redacted-ipv4>/24 
docker0          DOWN           <redacted-ipv4>/16 
default via <redacted-ipv4> dev wlP9s9 proto dhcp src <redacted-ipv4> metric 600 
<redacted-ipv4>/24 dev enP7s7 proto kernel scope link src <redacted-ipv4> metric 100 
<redacted-ipv4>/24 dev wlP9s9 proto kernel scope link src <redacted-ipv4> metric 600 
<redacted-ipv4>/16 dev docker0 proto kernel scope link src <redacted-ipv4> linkdown 
fe80::/64 dev wlP9s9 proto kernel metric 1024 pref medium
fe80::/64 dev enP7s7 proto kernel metric 1024 pref medium

== network links (no IPs) ==
lo               UNKNOWN        <redacted-mac> <LOOPBACK,UP,LOWER_UP> 
enP7s7           UP             <redacted-mac> <BROADCAST,MULTICAST,UP,LOWER_UP> 
enp1s0f0np0      DOWN           <redacted-mac> <NO-CARRIER,BROADCAST,MULTICAST,UP> 
enp1s0f1np1      DOWN           <redacted-mac> <NO-CARRIER,BROADCAST,MULTICAST,UP> 
enP2p1s0f0np0    DOWN           <redacted-mac> <NO-CARRIER,BROADCAST,MULTICAST,UP> 
enP2p1s0f1np1    DOWN           <redacted-mac> <NO-CARRIER,BROADCAST,MULTICAST,UP> 
wlP9s9           UP             <redacted-mac> <BROADCAST,MULTICAST,UP,LOWER_UP> 
docker0          DOWN           <redacted-mac> <NO-CARRIER,BROADCAST,MULTICAST,UP> 
-- ethtool enP7s7 --
Settings for enP7s7:
	Speed: 10000Mb/s
	Duplex: Full
	Auto-negotiation: on
	Link detected: yes
-- ethtool wlP9s9 --
Settings for wlP9s9:
	Link detected: yes

== storage ==
Filesystem      Size  Used Avail Use% Mounted on
/dev/nvme0n1p2  3.7T   39G  3.5T   2% /
/dev/nvme0n1p2  3.7T   39G  3.5T   2% /
NAME          SIZE TYPE MOUNTPOINTS
loop0           4K loop /snap/bare/5
loop1          69M loop /snap/core22/2412
loop2        61.9M loop /snap/core24/1588
loop3        10.2M loop /snap/firmware-updater/168
loop4       241.1M loop /snap/firefox/8242
loop5        15.6M loop /snap/firmware-updater/227
loop6         503M loop /snap/gnome-42-2204/245
loop7        12.2M loop /snap/snap-store/1217
loop8       552.9M loop /snap/gnome-46-2404/154
loop9       174.6M loop /snap/mesa-2404/1166
loop10       91.7M loop /snap/gtk-common-themes/1535
loop11       42.6M loop /snap/snapd/26869
loop12      221.2M loop /snap/thunderbird/1092
loop13       14.2M loop /snap/snapd-desktop-integration/253
loop14       44.4M loop /snap/snapd/24792
loop15      308.6M loop /snap/gnome-46-2404/90
loop16       10.7M loop /snap/firmware-updater/147
nvme0n1       3.7T disk 
├─nvme0n1p1     1G part /boot/efi
└─nvme0n1p2   3.7T part /

== disks (summary) ==
NAME      SIZE MODEL                     ROTA TYPE
nvme0n1   3.7T SAMSUNG MZALC4T0HBL1-00B07    0 disk

== nvidia driver (proc) ==
NVRM version: NVIDIA UNIX Open Kernel Module for aarch64  580.142  Release Build  (buildbrain@mobile-u64-6932-d7000)  Tue Mar  4 03:38:52 UTC 2026
GCC version:  gcc version 13.3.0 (Ubuntu 13.3.0-6ubuntu2~24.04.1)
```

```text
== local meta ==
Sat May  9 01:04:52 UTC 2026
probe target: spark0@aitopatom-9ab9.local

== probe meta ==
Sat May  9 01:04:53 UTC 2026
target user: spark0

== identity ==
aitopatom-9ab9
uid=1000(spark0) gid=1000(spark0) groups=1000(spark0),4(adm),27(sudo),29(audio),30(dip),46(plugdev),100(users),122(lpadmin)
Linux aitopatom-9ab9 6.17.0-1014-nvidia #14-Ubuntu SMP PREEMPT_DYNAMIC Tue Mar 17 19:01:40 UTC 2026 aarch64 aarch64 aarch64 GNU/Linux

== os ==
PRETTY_NAME="Ubuntu 24.04.4 LTS"
NAME="Ubuntu"
VERSION_ID="24.04"
VERSION="24.04.4 LTS (Noble Numbat)"
VERSION_CODENAME=noble
ID=ubuntu
ID_LIKE=debian
HOME_URL="https://www.ubuntu.com/"
SUPPORT_URL="https://help.ubuntu.com/"
BUG_REPORT_URL="https://bugs.launchpad.net/ubuntu/"
PRIVACY_POLICY_URL="https://www.ubuntu.com/legal/terms-and-policies/privacy-policy"
UBUNTU_CODENAME=noble
LOGO=ubuntu-logo

== cpu ==
Architecture:                            aarch64
CPU op-mode(s):                          64-bit
Byte Order:                              Little Endian
CPU(s):                                  20
On-line CPU(s) list:                     0-19
Vendor ID:                               ARM
Model name:                              Cortex-X925
Model:                                   1
Thread(s) per core:                      1
Core(s) per socket:                      10
Socket(s):                               1
Stepping:                                r0p1
Frequency boost:                         disabled
CPU(s) scaling MHz:                      100%
CPU max MHz:                             3900.0000
CPU min MHz:                             1378.0000
BogoMIPS:                                2000.00
Flags:                                   fp asimd evtstrm aes pmull sha1 sha2 crc32 atomics fphp asimdhp cpuid asimdrdm jscvt fcma lrcpc dcpop sha3 sm3 sm4 asimddp sha512 sve asimdfhm dit uscat ilrcpc flagm sb paca pacg dcpodp sve2 sveaes svepmull svebitperm svesha3 svesm4 flagm2 frint svei8mm svebf16 i8mm bf16 dgh bti ecv afp wfxt
Model name:                              Cortex-A725
Model:                                   1
Thread(s) per core:                      1
Core(s) per socket:                      10
Socket(s):                               1
Stepping:                                r0p1
CPU(s) scaling MHz:                      100%
CPU max MHz:                             2808.0000
CPU min MHz:                             338.0000
BogoMIPS:                                2000.00
Flags:                                   fp asimd evtstrm aes pmull sha1 sha2 crc32 atomics fphp asimdhp cpuid asimdrdm jscvt fcma lrcpc dcpop sha3 sm3 sm4 asimddp sha512 sve asimdfhm dit uscat ilrcpc flagm sb paca pacg dcpodp sve2 sveaes svepmull svebitperm svesha3 svesm4 flagm2 frint svei8mm svebf16 i8mm bf16 dgh bti ecv afp wfxt
L1d cache:                               1.3 MiB (20 instances)
L1i cache:                               1.3 MiB (20 instances)
L2 cache:                                25 MiB (20 instances)
L3 cache:                                24 MiB (2 instances)
NUMA node(s):                            1
NUMA node0 CPU(s):                       0-19
Vulnerability Gather data sampling:      Not affected
Vulnerability Ghostwrite:                Not affected
Vulnerability Indirect target selection: Not affected
Vulnerability Itlb multihit:             Not affected
Vulnerability L1tf:                      Not affected
Vulnerability Mds:                       Not affected
Vulnerability Meltdown:                  Not affected
Vulnerability Mmio stale data:           Not affected
Vulnerability Old microcode:             Not affected
Vulnerability Reg file data sampling:    Not affected
Vulnerability Retbleed:                  Not affected
Vulnerability Spec rstack overflow:      Not affected
Vulnerability Spec store bypass:         Mitigation; Speculative Store Bypass disabled via prctl
Vulnerability Spectre v1:                Mitigation; __user pointer sanitization
Vulnerability Spectre v2:                Mitigation; CSV2, BHB
Vulnerability Srbds:                     Not affected
Vulnerability Tsa:                       Not affected
Vulnerability Tsx async abort:           Not affected
Vulnerability Vmscape:                   Not affected

== memory ==
               total        used        free      shared  buff/cache   available
Mem:           119Gi       4.2Gi       114Gi        61Mi       2.5Gi       115Gi
Swap:           15Gi          0B        15Gi

== toolchain ==
gcc (Ubuntu 13.3.0-6ubuntu2~24.04.1) 13.3.0
g++ (Ubuntu 13.3.0-6ubuntu2~24.04.1) 13.3.0
cmake version 3.28.3
GNU Make 4.3
Python 3.12.3

== pci nvidia ==
0000:00:00.0 PCI bridge: NVIDIA Corporation Device 22ce (rev 01)
0002:00:00.0 PCI bridge: NVIDIA Corporation Device 22ce (rev 01)
0004:00:00.0 PCI bridge: NVIDIA Corporation Device 22ce (rev 01)
0007:00:00.0 PCI bridge: NVIDIA Corporation Device 22d0 (rev 01)
0009:00:00.0 PCI bridge: NVIDIA Corporation Device 22d0 (rev 01)
000f:00:00.0 PCI bridge: NVIDIA Corporation Device 22d1
000f:01:00.0 VGA compatible controller: NVIDIA Corporation Device 2e12 (rev a1)

== nvidia-smi query (driver + compute capability) ==
NVIDIA GB10, 580.142, 12.1, 46, P0, [N/A]

== nvidia-smi cuda version ==
CUDA Version                                           : 13.0

== cuda toolkit ==
nvcc: NVIDIA (R) Cuda compiler driver
Copyright (c) 2005-2025 NVIDIA Corporation
Built on Wed_Aug_20_01:57:39_PM_PDT_2025
Cuda compilation tools, release 13.0, V13.0.88
Build cuda_13.0.r13.0/compiler.36424714_0
-rwxr-xr-x 1 root root 24513032 Aug 21  2025 /usr/local/cuda/bin/nvcc
lrwxrwxrwx 1 root root 22 Dec 17 21:40 /usr/local/cuda -> /etc/alternatives/cuda
/usr/local/cuda-13.0

== cuda libraries (ldconfig, first hits) ==
	libcudart.so.13 (libc6,AArch64) => /usr/local/cuda/targets/sbsa-linux/lib/libcudart.so.13
	libcudart.so (libc6,AArch64) => /usr/local/cuda/targets/sbsa-linux/lib/libcudart.so
	libcuda.so.1 (libc6,AArch64) => /lib/aarch64-linux-gnu/libcuda.so.1

== cudnn (headers + libs) ==
cudnn headers not found


== cuda runtime probe (nvcc, no deps) ==
cuda devices: 1
device0 name: NVIDIA GB10
device0 cc: 12.1
driver version: 13000
runtime version: 13000
global mem (bytes): 128518373376

== network ==
lo               UNKNOWN        <redacted-ipv4>/8 
enP7s7           UP             <redacted-ipv4>/24 
wlP9s9           UP             <redacted-ipv4>/24 
docker0          DOWN           <redacted-ipv4>/16 
default via <redacted-ipv4> dev wlP9s9 proto dhcp src <redacted-ipv4> metric 600 
<redacted-ipv4>/24 dev enP7s7 proto kernel scope link src <redacted-ipv4> metric 100 
<redacted-ipv4>/24 dev wlP9s9 proto kernel scope link src <redacted-ipv4> metric 600 
<redacted-ipv4>/16 dev docker0 proto kernel scope link src <redacted-ipv4> linkdown 
fe80::/64 dev wlP9s9 proto kernel metric 1024 pref medium
fe80::/64 dev enP7s7 proto kernel metric 1024 pref medium

== network links (no IPs) ==
lo               UNKNOWN        <redacted-mac> <LOOPBACK,UP,LOWER_UP> 
enP7s7           UP             <redacted-mac> <BROADCAST,MULTICAST,UP,LOWER_UP> 
enp1s0f0np0      DOWN           <redacted-mac> <NO-CARRIER,BROADCAST,MULTICAST,UP> 
enp1s0f1np1      DOWN           <redacted-mac> <NO-CARRIER,BROADCAST,MULTICAST,UP> 
enP2p1s0f0np0    DOWN           <redacted-mac> <NO-CARRIER,BROADCAST,MULTICAST,UP> 
enP2p1s0f1np1    DOWN           <redacted-mac> <NO-CARRIER,BROADCAST,MULTICAST,UP> 
wlP9s9           UP             <redacted-mac> <BROADCAST,MULTICAST,UP,LOWER_UP> 
docker0          DOWN           <redacted-mac> <NO-CARRIER,BROADCAST,MULTICAST,UP> 
-- ethtool enP7s7 --
Settings for enP7s7:
	Speed: 10000Mb/s
	Duplex: Full
	Auto-negotiation: on
	Link detected: yes
-- ethtool wlP9s9 --
Settings for wlP9s9:
	Link detected: yes

== storage ==
Filesystem      Size  Used Avail Use% Mounted on
/dev/nvme0n1p2  3.7T   39G  3.5T   2% /
/dev/nvme0n1p2  3.7T   39G  3.5T   2% /
NAME          SIZE TYPE MOUNTPOINTS
loop0           4K loop /snap/bare/5
loop1          69M loop /snap/core22/2412
loop2        61.9M loop /snap/core24/1588
loop3        10.2M loop /snap/firmware-updater/168
loop4       241.1M loop /snap/firefox/8242
loop5        15.6M loop /snap/firmware-updater/227
loop6         503M loop /snap/gnome-42-2204/245
loop7        12.2M loop /snap/snap-store/1217
loop8       552.9M loop /snap/gnome-46-2404/154
loop9       174.6M loop /snap/mesa-2404/1166
loop10       91.7M loop /snap/gtk-common-themes/1535
loop11       42.6M loop /snap/snapd/26869
loop12      221.2M loop /snap/thunderbird/1092
loop13        552K loop /snap/snapd-desktop-integration/316
loop14         10M loop /snap/snap-store/1271
loop15      234.8M loop /snap/firefox/8278
nvme0n1       3.7T disk 
|-nvme0n1p1   512M part /boot/efi
`-nvme0n1p2   3.7T part /

== disks (summary) ==
NAME      SIZE MODEL                      ROTA TYPE
loop0       4K                               0 loop
loop1      69M                               0 loop
loop2    61.9M                               0 loop
loop3    10.2M                               0 loop
loop4   241.1M                               0 loop
loop5    15.6M                               0 loop
loop6     503M                               0 loop
loop7    12.2M                               0 loop
loop8   552.9M                               0 loop
loop9   174.6M                               0 loop
loop10   91.7M                               0 loop
loop11   42.6M                               0 loop
loop12  221.2M                               0 loop
loop13    552K                               0 loop
loop14     10M                               0 loop
loop15  234.8M                               0 loop
nvme0n1   3.7T SAMSUNG MZALC4T0HBL1-00B07    0 disk

== nvidia driver (proc) ==
NVRM version: NVIDIA UNIX Open Kernel Module for aarch64  580.142  Release Build  (dvs-builder@U22-I3-H10-02-1)  Tue Mar  3 19:08:06 UTC 2026
GCC version:  gcc version 13.3.0 (Ubuntu 13.3.0-6ubuntu2~24.04.1) 
```

## Update: Probe Refresh (2026-05-09 04:23Z)

Commands run:

```bash
REDACT=1 DS4_GIT_DIR=/private/tmp/ds4_git/.git ./scripts/spark_probe.sh spark0@aitopatom-9ab9.local > /private/tmp/spark0_probe_redacted_2026-05-09_10.txt
```

Notes:

- This output is redacted (`REDACT=1`) to remove IPv4/IPv6/MAC addresses and GPU UUID tokens.
- The `nvidia-smi` section includes GPU `index` + `pci.bus_id` to make multi-GPU hosts easier to compare across reboots.

```text
== nvidia-smi inventory (index + pci bus) ==
0, NVIDIA GB10, 0000000F:01:00.0, 580.142, 12.1, 47, P0, [N/A]

== nvidia-smi cuda version ==
CUDA Version                                           : 13.0

== nvidia-smi gpu list ==
GPU 0: NVIDIA GB10 (UUID: <redacted-gpu-uuid>)

== cuda toolkit ==
nvcc: NVIDIA (R) Cuda compiler driver
Copyright (c) 2005-2025 NVIDIA Corporation
Built on Wed_Aug_20_01:57:39_PM_PDT_2025
Cuda compilation tools, release 13.0, V13.0.88
Build cuda_13.0.r13.0/compiler.36424714_0
-rwxr-xr-x 1 root root 24513032 Aug 21  2025 /usr/local/cuda/bin/nvcc
ptxas: /usr/local/cuda/bin/ptxas
ptxas: NVIDIA (R) Ptx optimizing assembler
Copyright (c) 2005-2025 NVIDIA Corporation
Built on Wed_Aug_20_01:53:56_PM_PDT_2025
lrwxrwxrwx 1 root root 22 Dec 17 21:40 /usr/local/cuda -> /etc/alternatives/cuda
/usr/local/cuda-13.0

== cuda libraries (ldconfig, first hits) ==
	libcudart.so.13 (libc6,AArch64) => /usr/local/cuda/targets/sbsa-linux/lib/libcudart.so.13
	libcudart.so (libc6,AArch64) => /usr/local/cuda/targets/sbsa-linux/lib/libcudart.so
	libcuda.so.1 (libc6,AArch64) => /lib/aarch64-linux-gnu/libcuda.so.1

== cudnn (headers + libs) ==
cudnn headers not found


== cuda runtime probe (nvcc, no deps) ==
cuda devices: 1
cuda driver api version: 13000
cuda runtime api version: 13000
device0 name: NVIDIA GB10
device0 cc: 12.1
device0 global mem (bytes): 128518373376
device0 sms: 48
```

## Update: Probe Refresh (2026-05-09 04:52Z)

Commands run:

```bash
REDACT=1 DS4_GIT_DIR=/private/tmp/ds4_git/.git ./scripts/spark_probe.sh spark0@aitopatom-9ab9.local > /private/tmp/spark0_probe_redacted_2026-05-09_12.txt
```

Notes:

- This output is redacted (`REDACT=1`) to remove IPv4/IPv6/MAC addresses and GPU UUID tokens.

```text
== nvidia-smi inventory (index + pci bus) ==
0, NVIDIA GB10, 0000000F:01:00.0, 580.142, 12.1, 48, P0, [N/A]

== nvidia-smi cuda version ==
CUDA Version                                           : 13.0

== cuda runtime probe (nvcc, no deps) ==
cuda devices: 1
cuda driver api version: 13000
cuda runtime api version: 13000
device0 name: NVIDIA GB10
device0 cc: 12.1
device0 global mem (bytes): 128518373376
device0 sms: 48

== disks (summary) ==
NAME      SIZE MODEL                      ROTA TYPE
nvme0n1   3.7T SAMSUNG MZALC4T0HBL1-00B07    0 disk
```

## Update: Probe Refresh (2026-05-09 05:26Z)

Commands run:

```bash
REDACT=1 ./scripts/spark_probe.sh spark0@aitopatom-9ab9.local > /private/tmp/spark0_probe_redacted_2026-05-09_0526Z.txt
```

Notes:

- This output is redacted (`REDACT=1`) to remove IPv4/IPv6/MAC addresses and GPU UUID tokens.
- Includes `nvidia-smi topo -m` (capped) and kernel module metadata (`lsmod`, `modinfo nvidia`) for driver/toolkit cross-checks.

```text
== local meta ==
Sat May  9 05:26:33 UTC 2026
git: 310531d
probe target: spark0@aitopatom-9ab9.local

== nvidia-smi inventory (index + pci bus) ==
0, NVIDIA GB10, 0000000F:01:00.0, 580.142, 12.1, 49, P0, [N/A]

== nvidia-smi topo (capped) ==
	GPU0	NIC0	NIC1	NIC2	NIC3	CPU Affinity	NUMA Affinity	GPU NUMA ID
GPU0	 X 	NODE	NODE	NODE	NODE	0-19	0		N/A

== cuda headers (cuda.h) ==
/usr/local/cuda/include/cuda.h
#define CUDA_VERSION 13000

== modinfo nvidia (summary) ==
filename:       /lib/modules/6.17.0-1014-nvidia/kernel/nvidia-580-open/nvidia.ko
version:        580.142
vermagic:       6.17.0-1014-nvidia SMP preempt mod_unload modversions aarch64
```
