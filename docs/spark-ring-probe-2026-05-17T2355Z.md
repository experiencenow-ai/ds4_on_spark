== local meta ==
Sun May 17 23:55:26 UTC 2026
git: 93cc51c
probe args: spark0@aitopatom-9ab9.local spark1@edgexpert-d623.local
resolved targets: spark0@aitopatom-9ab9.local spark1@edgexpert-d623.local
topology: ring
ssh opts: -o BatchMode=yes -o ConnectTimeout=10 -o StrictHostKeyChecking=accept-new -o ServerAliveInterval=5 -o ServerAliveCountMax=2
known_hosts: spark0@aitopatom-9ab9.local -> /private/tmp/ds4_spark_known_hosts.aitopatom-9ab9.local
known_hosts: spark1@edgexpert-d623.local -> /private/tmp/ds4_spark_known_hosts.edgexpert-d623.local

== target: spark0@aitopatom-9ab9.local ==
== probe meta ==
Sun May 17 23:55:26 UTC 2026
target user: spark0

== identity ==
aitopatom-9ab9
Linux aitopatom-9ab9 6.17.0-1014-nvidia #14-Ubuntu SMP PREEMPT_DYNAMIC Tue Mar 17 19:01:40 UTC 2026 aarch64 aarch64 aarch64 GNU/Linux

== clock ==
utc: 2026-05-17T23:55:26Z
epoch: 1779062126
skew_s (remote-local): 0
NTPSynchronized=yes
TimeUSec=Mon 2026-05-18 08:55:26 KST

== network (links + addrs, compact) ==
lo               UNKNOWN        <redacted-mac> <LOOPBACK,UP,LOWER_UP>
enP7s7           UP             <redacted-mac> <BROADCAST,MULTICAST,UP,LOWER_UP>
enp1s0f0np0      UP             <redacted-mac> <BROADCAST,MULTICAST,UP,LOWER_UP>
enp1s0f1np1      UP             <redacted-mac> <BROADCAST,MULTICAST,UP,LOWER_UP>
enP2p1s0f0np0    UP             <redacted-mac> <BROADCAST,MULTICAST,UP,LOWER_UP>
enP2p1s0f1np1    UP             <redacted-mac> <BROADCAST,MULTICAST,UP,LOWER_UP>
wlP9s9           UP             <redacted-mac> <BROADCAST,MULTICAST,UP,LOWER_UP>
docker0          DOWN           <redacted-mac> <NO-CARRIER,BROADCAST,MULTICAST,UP>

== network (link speed, compact) ==
docker0 speed_mbps=unknown duplex=unknown
enP2p1s0f0np0 speed_mbps=200000 duplex=full
enP2p1s0f1np1 speed_mbps=200000 duplex=full
enP7s7 speed_mbps=10000 duplex=full
enp1s0f0np0 speed_mbps=200000 duplex=full
enp1s0f1np1 speed_mbps=200000 duplex=full
wlP9s9 speed_mbps=? duplex=?

== network (mtu, compact) ==
enP7s7 mtu=9000 state=UP
enp1s0f0np0 mtu=9000 state=UP
enp1s0f1np1 mtu=9000 state=UP
enP2p1s0f0np0 mtu=9000 state=UP
enP2p1s0f1np1 mtu=9000 state=UP
wlP9s9 mtu=1500 state=UP
docker0 mtu=1500 state=DOWN

== network (iface matrix, compact) ==
docker0 state=DOWN mtu=1500 speed_mbps=unknown duplex=unknown v4=<redacted-ipv4cidr> v6=-
enP2p1s0f0np0 state=UP mtu=9000 speed_mbps=200000 duplex=full v4=<redacted-ipv4cidr> v6=<redacted-ipv6>/64
enP2p1s0f1np1 state=UP mtu=9000 speed_mbps=200000 duplex=full v4=<redacted-ipv4cidr> v6=<redacted-ipv6>/64
enP7s7 state=UP mtu=9000 speed_mbps=10000 duplex=full v4=<redacted-ipv4cidr>,<redacted-ipv4>/16 v6=<redacted-ipv6>/64
enp1s0f0np0 state=UP mtu=9000 speed_mbps=200000 duplex=full v4=<redacted-ipv4cidr> v6=<redacted-ipv6>/64
enp1s0f1np1 state=UP mtu=9000 speed_mbps=200000 duplex=full v4=<redacted-ipv4cidr> v6=<redacted-ipv6>/64
wlP9s9 state=UP mtu=1500 speed_mbps=? duplex=? v4=<redacted-ipv4cidr> v6=<redacted-ipv6>/64

lo               UNKNOWN        <redacted-ipv4cidr>
enP7s7           UP             <redacted-ipv4cidr> <redacted-ipv4>/16
enp1s0f0np0      UP             <redacted-ipv4cidr>
enp1s0f1np1      UP             <redacted-ipv4cidr>
enP2p1s0f0np0    UP             <redacted-ipv4cidr>
enP2p1s0f1np1    UP             <redacted-ipv4cidr>
wlP9s9           UP             <redacted-ipv4cidr>
docker0          DOWN           <redacted-ipv4cidr>

lo               UNKNOWN        <redacted-ipv6>/128
enP7s7           UP             <redacted-ipv6>/64
enp1s0f0np0      UP             <redacted-ipv6>/64
enp1s0f1np1      UP             <redacted-ipv6>/64
enP2p1s0f0np0    UP             <redacted-ipv6>/64
enP2p1s0f1np1    UP             <redacted-ipv6>/64
wlP9s9           UP             <redacted-ipv6>/64

default via <redacted-ipv4> dev wlP9s9 proto dhcp src <redacted-ipv4> metric 600

== storage (df, lsblk model/size) ==
Filesystem      Size  Used Avail Use% Mounted on
tmpfs            12G   29M   12G   1% /run
efivarfs        256K   20K  237K   8% /sys/firmware/efi/efivars
/dev/nvme0n1p2  3.7T  309G  3.2T   9% /
tmpfs            60G     0   60G   0% /dev/shm
tmpfs           5.0M  8.0K  5.0M   1% /run/lock
/dev/nvme0n1p1  511M  6.4M  505M   2% /boot/efi
tmpfs            12G  100K   12G   1% /run/user/126
tmpfs            12G   88K   12G   1% /run/user/1000
== disks (summary) ==
NAME      SIZE MODEL                      ROTA TYPE
nvme0n1   3.7T SAMSUNG MZALC4T0HBL1-00B07    0 disk

== lsblk (mounts, no loop, capped) ==
NAME        TYPE   SIZE MODEL                      MOUNTPOINT                          FSTYPE
nvme0n1     disk   3.7T SAMSUNG MZALC4T0HBL1-00B07
|-nvme0n1p1 part   512M                            /boot/efi                           vfat
`-nvme0n1p2 part   3.7T                            /                                   ext4

== gpu/toolchain facts (compact) ==
NVIDIA-SMI version  : 580.142
NVML version        : 580.142
DRIVER version      : 580.142
CUDA Version        : 13.0
columns: index,gpu_name,pci.bus_id,driver_version,compute_cap,memory.total
0, NVIDIA GB10, 0000000F:01:00.0, 580.142, 12.1, [N/A]
note: nvidia-smi memory.total is [N/A] (unified memory); use free -h for system RAM
nvcc path: /usr/local/cuda/bin/nvcc
nvcc: NVIDIA (R) Cuda compiler driver
Copyright (c) 2005-2025 NVIDIA Corporation
Built on Wed_Aug_20_01:57:39_PM_PDT_2025
Cuda compilation tools, release 13.0, V13.0.88
Build cuda_13.0.r13.0/compiler.36424714_0
cuda version.json: 13.0.3
cuda.h CUDA_VERSION: 13000

== cuda/toolchain facts (summary) ==
driver: 580.142
smi CUDA: 13.0
nvcc release: 13.0
cuda version.json: 13.0.3
cuda.h CUDA_VERSION: 13000
compute_cap: 12.1

== peer ping (best effort, rtt) ==
peers: edgexpert-d623.local
edgexpert-d623.local: ping_ok loss=0% rtt_ms=109.299/300.447/437.564/139.353

== target: spark1@edgexpert-d623.local ==
== probe meta ==
Sun May 17 23:55:29 UTC 2026
target user: spark1

== identity ==
edgexpert-d623
Linux edgexpert-d623 6.17.0-1014-nvidia #14-Ubuntu SMP PREEMPT_DYNAMIC Tue Mar 17 19:01:40 UTC 2026 aarch64 aarch64 aarch64 GNU/Linux

== clock ==
utc: 2026-05-17T23:55:29Z
epoch: 1779062129
skew_s (remote-local): 0
NTPSynchronized=yes
TimeUSec=Mon 2026-05-18 08:55:29 KST

== network (links + addrs, compact) ==
lo               UNKNOWN        <redacted-mac> <LOOPBACK,UP,LOWER_UP>
enP7s7           DOWN           <redacted-mac> <NO-CARRIER,BROADCAST,MULTICAST,UP>
enp1s0f0np0      UP             <redacted-mac> <BROADCAST,MULTICAST,UP,LOWER_UP>
enp1s0f1np1      UP             <redacted-mac> <BROADCAST,MULTICAST,UP,LOWER_UP>
enP2p1s0f0np0    UP             <redacted-mac> <BROADCAST,MULTICAST,UP,LOWER_UP>
enP2p1s0f1np1    UP             <redacted-mac> <BROADCAST,MULTICAST,UP,LOWER_UP>
wlP9s9           UP             <redacted-mac> <BROADCAST,MULTICAST,UP,LOWER_UP>
docker0          DOWN           <redacted-mac> <NO-CARRIER,BROADCAST,MULTICAST,UP>

== network (link speed, compact) ==
docker0 speed_mbps=unknown duplex=unknown
enP2p1s0f0np0 speed_mbps=200000 duplex=full
enP2p1s0f1np1 speed_mbps=200000 duplex=full
enP7s7 speed_mbps=unknown duplex=unknown
enp1s0f0np0 speed_mbps=200000 duplex=full
enp1s0f1np1 speed_mbps=200000 duplex=full
wlP9s9 speed_mbps=? duplex=?

== network (mtu, compact) ==
enP7s7 mtu=1500 state=DOWN
enp1s0f0np0 mtu=9000 state=UP
enp1s0f1np1 mtu=9000 state=UP
enP2p1s0f0np0 mtu=9000 state=UP
enP2p1s0f1np1 mtu=9000 state=UP
wlP9s9 mtu=1500 state=UP
docker0 mtu=1500 state=DOWN

== network (iface matrix, compact) ==
docker0 state=DOWN mtu=1500 speed_mbps=unknown duplex=unknown v4=<redacted-ipv4cidr> v6=-
enP2p1s0f0np0 state=UP mtu=9000 speed_mbps=200000 duplex=full v4=<redacted-ipv4cidr> v6=<redacted-ipv6>/64
enP2p1s0f1np1 state=UP mtu=9000 speed_mbps=200000 duplex=full v4=<redacted-ipv4cidr> v6=<redacted-ipv6>/64
enP7s7 state=DOWN mtu=1500 speed_mbps=unknown duplex=unknown v4=- v6=-
enp1s0f0np0 state=UP mtu=9000 speed_mbps=200000 duplex=full v4=<redacted-ipv4cidr> v6=<redacted-ipv6>/64
enp1s0f1np1 state=UP mtu=9000 speed_mbps=200000 duplex=full v4=<redacted-ipv4cidr> v6=<redacted-ipv6>/64
wlP9s9 state=UP mtu=1500 speed_mbps=? duplex=? v4=<redacted-ipv4cidr> v6=<redacted-ipv6>/64

lo               UNKNOWN        <redacted-ipv4cidr>
enp1s0f0np0      UP             <redacted-ipv4cidr>
enp1s0f1np1      UP             <redacted-ipv4cidr>
enP2p1s0f0np0    UP             <redacted-ipv4cidr>
enP2p1s0f1np1    UP             <redacted-ipv4cidr>
wlP9s9           UP             <redacted-ipv4cidr>
docker0          DOWN           <redacted-ipv4cidr>

lo               UNKNOWN        <redacted-ipv6>/128
enp1s0f0np0      UP             <redacted-ipv6>/64
enp1s0f1np1      UP             <redacted-ipv6>/64
enP2p1s0f0np0    UP             <redacted-ipv6>/64
enP2p1s0f1np1    UP             <redacted-ipv6>/64
wlP9s9           UP             <redacted-ipv6>/64

default via <redacted-ipv4> dev wlP9s9 proto dhcp src <redacted-ipv4> metric 600

== storage (df, lsblk model/size) ==
Filesystem      Size  Used Avail Use% Mounted on
tmpfs            13G  8.5M   13G   1% /run
efivarfs        256K   19K  238K   8% /sys/firmware/efi/efivars
/dev/nvme0n1p2  3.7T  190G  3.3T   6% /
tmpfs            61G     0   61G   0% /dev/shm
tmpfs           5.0M  8.0K  5.0M   1% /run/lock
/dev/nvme0n1p1  511M  6.4M  505M   2% /boot/efi
tmpfs            13G   88K   13G   1% /run/user/1000
== disks (summary) ==
NAME      SIZE MODEL                      ROTA TYPE
nvme0n1   3.7T SAMSUNG MZALC4T0HBL1-00B07    0 disk

== lsblk (mounts, no loop, capped) ==
NAME        TYPE   SIZE MODEL                      MOUNTPOINT                          FSTYPE
nvme0n1     disk   3.7T SAMSUNG MZALC4T0HBL1-00B07
|-nvme0n1p1 part   512M                            /boot/efi                           vfat
`-nvme0n1p2 part   3.7T                            /                                   ext4

== gpu/toolchain facts (compact) ==
NVIDIA-SMI version  : 580.142
NVML version        : 580.142
DRIVER version      : 580.142
CUDA Version        : 13.0
columns: index,gpu_name,pci.bus_id,driver_version,compute_cap,memory.total
0, NVIDIA GB10, 0000000F:01:00.0, 580.142, 12.1, [N/A]
note: nvidia-smi memory.total is [N/A] (unified memory); use free -h for system RAM
nvcc path: /usr/local/cuda/bin/nvcc
nvcc: NVIDIA (R) Cuda compiler driver
Copyright (c) 2005-2025 NVIDIA Corporation
Built on Wed_Aug_20_01:57:39_PM_PDT_2025
Cuda compilation tools, release 13.0, V13.0.88
Build cuda_13.0.r13.0/compiler.36424714_0
cuda version.json: 13.0.3
cuda.h CUDA_VERSION: 13000

== cuda/toolchain facts (summary) ==
driver: 580.142
smi CUDA: 13.0
nvcc release: 13.0
cuda version.json: 13.0.3
cuda.h CUDA_VERSION: 13000
compute_cap: 12.1

== peer ping (best effort, rtt) ==
peers: aitopatom-9ab9.local
aitopatom-9ab9.local: ping_ok loss=0% rtt_ms=43.426/64.371/84.385/16.734

== clock (summary, remote-local) ==
aitopatom-9ab9.local epoch=1779062126 skew_s=0
edgexpert-d623.local epoch=1779062129 skew_s=0

skew span_s: 0 (min=0 max=0)
