== local meta ==
Mon May 11 12:28:21 UTC 2026
git: d951bff
probe args: aitopatom-9ab9.local
resolved targets: spark0@aitopatom-9ab9.local
ssh opts: -o BatchMode=yes -o ConnectTimeout=10 -o StrictHostKeyChecking=accept-new -o ServerAliveInterval=5 -o ServerAliveCountMax=2
known_hosts: spark0@aitopatom-9ab9.local -> /private/tmp/ds4_spark_known_hosts.aitopatom-9ab9.local

== target: spark0@aitopatom-9ab9.local ==
== probe meta ==
Mon May 11 12:28:21 UTC 2026
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
Byte Order:                              Little Endian
CPU(s):                                  20
Model name:                              Cortex-X925
Thread(s) per core:                      1
Core(s) per socket:                      10
Socket(s):                               1
Model name:                              Cortex-A725
Thread(s) per core:                      1
Core(s) per socket:                      10
Socket(s):                               1
NUMA node(s):                            1

== memory ==
               total        used        free      shared  buff/cache   available
Mem:           119Gi       3.7Gi        25Gi        56Mi        91Gi       115Gi
Swap:           15Gi       620Mi        15Gi

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

== pci nvidia ==
0000:00:00.0 PCI bridge: NVIDIA Corporation Device 22ce (rev 01)
0002:00:00.0 PCI bridge: NVIDIA Corporation Device 22ce (rev 01)
0004:00:00.0 PCI bridge: NVIDIA Corporation Device 22ce (rev 01)
0007:00:00.0 PCI bridge: NVIDIA Corporation Device 22d0 (rev 01)
0009:00:00.0 PCI bridge: NVIDIA Corporation Device 22d0 (rev 01)
000f:00:00.0 PCI bridge: NVIDIA Corporation Device 22d1
000f:01:00.0 VGA compatible controller: NVIDIA Corporation Device 2e12 (rev a1)

== pci nvidia (numeric ids) ==
0000:00:00.0 PCI bridge [0604]: NVIDIA Corporation Device [10de:22ce] (rev 01)
0002:00:00.0 PCI bridge [0604]: NVIDIA Corporation Device [10de:22ce] (rev 01)
0004:00:00.0 PCI bridge [0604]: NVIDIA Corporation Device [10de:22ce] (rev 01)
0007:00:00.0 PCI bridge [0604]: NVIDIA Corporation Device [10de:22d0] (rev 01)
0009:00:00.0 PCI bridge [0604]: NVIDIA Corporation Device [10de:22d0] (rev 01)
000f:00:00.0 PCI bridge [0604]: NVIDIA Corporation Device [10de:22d1]
000f:01:00.0 VGA compatible controller [0300]: NVIDIA Corporation Device [10de:2e12] (rev a1)

== nvidia-smi version ==
NVIDIA-SMI version  : 580.142
NVML version        : 580.142
DRIVER version      : 580.142
CUDA Version        : 13.0

== nvidia-smi inventory (index + pci bus) ==
columns: index,gpu_name,pci.bus_id,driver_version,compute_cap,memory.total
0, NVIDIA GB10, 0000000F:01:00.0, 580.142, 12.1, [N/A]
note: nvidia-smi memory.total is [N/A] (unified memory); use == memory == and the cuda runtime probe global mem bytes

== nvidia-smi pci ids (optional) ==
columns: index,pci.bus_id,pci.device_id,pci.sub_device_id
0, 0000000F:01:00.0, 0x2E1210DE, 0x10DE
selected compute_cap: 12.1
selected nvcc arch: sm_121

== nvidia-smi cuda version ==
CUDA Version: 13.0

== nvidia-smi -q fabric/c2c (summary) ==
Product Architecture: Blackwell
Peer Type: Direct Connected
GPU C2C Mode: Enabled

== probe mode ==
facts-only: 1

== nvidia-smi pcie link (max/current) ==
columns: index,pci.bus_id,pcie.link.gen.max,pcie.link.gen.current,pcie.link.width.max,pcie.link.width.current
0, 0000000F:01:00.0, 1, 1, 16, 1
warning: nvidia-smi pcie.gen.max=1 but -q shows device_max=5 host_max=5 (bus 0000000F:01:00.0)

== nvidia-smi pcie link (gpu/host max, optional) ==
columns: index,pci.bus_id,pcie.link.gen.gpucurrent,pcie.link.gen.gpumax,pcie.link.gen.hostmax,pcie.link.width.current,pcie.link.width.max
0, 0000000F:01:00.0, 1, 5, 5, 1, 16

== pci link (sysfs, gpu endpoints, current/max) ==
-- 0000000F:01:00.0 -> 000f:01:00.0 --
current_link_speed: 2.5 GT/s PCIe
current_link_width: 1
max_link_speed: 2.5 GT/s PCIe
max_link_width: 16
warning: sysfs pcie.gen.max=1 but -q shows device_max=5 host_max=5 (bus 0000000F:01:00.0)

== cuda toolkit ==
nvcc path: /usr/local/cuda/bin/nvcc (not on PATH)
nvcc: NVIDIA (R) Cuda compiler driver
Copyright (c) 2005-2025 NVIDIA Corporation
Built on Wed_Aug_20_01:57:39_PM_PDT_2025
Cuda compilation tools, release 13.0, V13.0.88
Build cuda_13.0.r13.0/compiler.36424714_0
-rwxr-xr-x 1 root root 24513032 Aug 21  2025 /usr/local/cuda/bin/nvcc

nvcc supports gpu code: sm_121
ptxas: /usr/local/cuda/bin/ptxas
ptxas: NVIDIA (R) Ptx optimizing assembler
Copyright (c) 2005-2025 NVIDIA Corporation
Built on Wed_Aug_20_01:53:56_PM_PDT_2025
lrwxrwxrwx 1 root root 22 Dec 17 21:40 /usr/local/cuda -> /etc/alternatives/cuda
/usr/local/cuda-13.0

== cuda version.json (summary) ==
cuda: 13.0.3

== cuda headers (cuda.h) ==
/usr/local/cuda/include/cuda.h
#define CUDA_VERSION 13000

== cuda/toolchain facts (summary) ==
driver: 580.142
smi CUDA: 13.0
nvcc release: 13.0
cuda version.json: 13.0.3
cuda.h CUDA_VERSION: 13000
compute_cap: 12.1
nvcc arch: sm_121

== cuda libraries (ldconfig, first hits) ==
	libcudart.so.13 (libc6,AArch64) => /usr/local/cuda/targets/sbsa-linux/lib/libcudart.so.13
	libcudart.so (libc6,AArch64) => /usr/local/cuda/targets/sbsa-linux/lib/libcudart.so
	libcuda.so.1 (libc6,AArch64) => /lib/aarch64-linux-gnu/libcuda.so.1

== cudnn (headers + libs) ==
cudnn headers not found


== cuda demo_suite (deviceQuery, optional) ==
deviceQuery not found

== cuda runtime probe (nvcc, no deps) ==
nvcc arch: sm_121
cuda devices: 1
cuda driver api version: 13000 (13.0)
cuda runtime api version: 13000 (13.0)
device0 name: NVIDIA GB10
device0 cc: 12.1
device0 global mem (bytes): 128518373376
device0 sms: 48
device0 pci bus id: 000F:01:00.0
runtime max cc: 12.1

== nvidia-smi pcie link (max/current, post-load) ==
columns: index,pci.bus_id,pcie.link.gen.max,pcie.link.gen.current,pcie.link.width.max,pcie.link.width.current
0, 0000000F:01:00.0, 1, 1, 16, 1
warning: nvidia-smi pcie.gen.max=1 but -q shows device_max=5 host_max=5 (bus 0000000F:01:00.0)

== nvidia-smi pcie link (gpu/host max, optional, post-load) ==
columns: index,pci.bus_id,pcie.link.gen.gpucurrent,pcie.link.gen.gpumax,pcie.link.gen.hostmax,pcie.link.width.current,pcie.link.width.max
0, 0000000F:01:00.0, 1, 5, 5, 1, 16

== pci link (sysfs, gpu endpoints, current/max, post-load) ==
-- 0000000F:01:00.0 -> 000f:01:00.0 --
current_link_speed: 2.5 GT/s PCIe
current_link_width: 1
max_link_speed: 2.5 GT/s PCIe
max_link_width: 16
warning: sysfs pcie.gen.max=1 but -q shows device_max=5 host_max=5 (bus 0000000F:01:00.0)


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
driver: r8127
version: 11.014.00-NAPI
firmware-version: 
bus-info: 0007:01:00.0
-- ethtool wlP9s9 --
Settings for wlP9s9:
	Link detected: yes
driver: mt7925e
version: 6.17.0-1014-nvidia
firmware-version: ____000000-20251210093025
bus-info: 0009:01:00.0

== filesystems (type + opts) ==
/      ext4   rw,relatime,errors=remount-ro

== storage ==
== disks (summary) ==
NAME     SIZE MODEL                      ROTA TYPE
nvme0n1  3.7T SAMSUNG MZALC4T0HBL1-00B07    0 disk

== nvidia driver (proc) ==
NVRM version: NVIDIA UNIX Open Kernel Module for aarch64  580.142  Release Build  (dvs-builder@U22-I3-H10-02-1)  Tue Mar  3 19:08:06 UTC 2026
GCC version:  gcc version 13.3.0 (Ubuntu 13.3.0-6ubuntu2~24.04.1) 

== kernel modules (nvidia) ==
nvidia_uvm           1900544  4
nvidia_drm            135168  11
nvidia_modeset       1957888  12 nvidia_drm
nvidia              14675968  183 nvidia_uvm,nvidia_modeset

== modinfo nvidia (summary) ==
filename:       /lib/modules/6.17.0-1014-nvidia/kernel/nvidia-580-open/nvidia.ko
version:        580.142
srcversion:     C4BC8E95CA62E8363647ABA
vermagic:       6.17.0-1014-nvidia SMP preempt mod_unload modversions aarch64

== /dev nvidia nodes ==
crw-rw-rw- 1 root root 195, 254 May  9 05:57 /dev/nvidia-modeset
crw-rw-rw- 1 root root 498,   0 May  9 05:57 /dev/nvidia-uvm
crw-rw-rw- 1 root root 498,   1 May  9 05:57 /dev/nvidia-uvm-tools
crw-rw-rw- 1 root root 195,   0 May  9 05:57 /dev/nvidia0
crw-rw-rw- 1 root root 195, 255 May  9 05:57 /dev/nvidiactl

/dev/nvidia-caps:
total 0
cr-------- 1 root root 502, 1 May  9 05:59 nvidia-cap1
cr--r--r-- 1 root root 502, 2 May  9 05:59 nvidia-cap2

