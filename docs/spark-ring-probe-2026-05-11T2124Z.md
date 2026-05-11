== local meta ==
Mon May 11 21:25:03 UTC 2026
git: 51f62fd
probe args: aitopatom-9ab9.local spark1.local spark2.local
resolved targets: spark0@aitopatom-9ab9.local spark0@spark1.local spark0@spark2.local
topology: ring
ssh opts: -o BatchMode=yes -o ConnectTimeout=10 -o StrictHostKeyChecking=accept-new -o ServerAliveInterval=5 -o ServerAliveCountMax=2
known_hosts: spark0@aitopatom-9ab9.local -> /private/tmp/ds4_spark_known_hosts.aitopatom-9ab9.local
known_hosts: spark0@spark1.local -> /private/tmp/ds4_spark_known_hosts.spark1.local
known_hosts: spark0@spark2.local -> /private/tmp/ds4_spark_known_hosts.spark2.local

== target: spark0@aitopatom-9ab9.local ==
== probe meta ==
Mon May 11 21:25:03 UTC 2026
target user: spark0

== identity ==
aitopatom-9ab9
Linux aitopatom-9ab9 6.17.0-1014-nvidia #14-Ubuntu SMP PREEMPT_DYNAMIC Tue Mar 17 19:01:40 UTC 2026 aarch64 aarch64 aarch64 GNU/Linux

== clock ==
utc: 2026-05-11T21:25:03Z
epoch: 1778534703
NTPSynchronized=yes
TimeUSec=Tue 2026-05-12 06:25:04 KST

== network (links + addrs, compact) ==
lo               UNKNOWN        <redacted-mac> <LOOPBACK,UP,LOWER_UP> 
enP7s7           UP             <redacted-mac> <BROADCAST,MULTICAST,UP,LOWER_UP> 
enp1s0f0np0      DOWN           <redacted-mac> <NO-CARRIER,BROADCAST,MULTICAST,UP> 
enp1s0f1np1      DOWN           <redacted-mac> <NO-CARRIER,BROADCAST,MULTICAST,UP> 
enP2p1s0f0np0    DOWN           <redacted-mac> <NO-CARRIER,BROADCAST,MULTICAST,UP> 
enP2p1s0f1np1    DOWN           <redacted-mac> <NO-CARRIER,BROADCAST,MULTICAST,UP> 
wlP9s9           UP             <redacted-mac> <BROADCAST,MULTICAST,UP,LOWER_UP> 
docker0          DOWN           <redacted-mac> <NO-CARRIER,BROADCAST,MULTICAST,UP> 

== network (link speed, compact) ==
docker0 speed_mbps=unknown duplex=unknown
enP2p1s0f0np0 speed_mbps=unknown duplex=unknown
enP2p1s0f1np1 speed_mbps=unknown duplex=unknown
enP7s7 speed_mbps=10000 duplex=full
enp1s0f0np0 speed_mbps=unknown duplex=unknown
enp1s0f1np1 speed_mbps=unknown duplex=unknown
wlP9s9 speed_mbps=? duplex=?

== network (mtu, compact) ==
enP7s7 mtu=9000 state=UP
enp1s0f0np0 mtu=1500 state=DOWN
enp1s0f1np1 mtu=1500 state=DOWN
enP2p1s0f0np0 mtu=1500 state=DOWN
enP2p1s0f1np1 mtu=1500 state=DOWN
wlP9s9 mtu=1500 state=UP
docker0 mtu=1500 state=DOWN

lo               UNKNOWN        <redacted-ipv4>/8 
enP7s7           UP             <redacted-ipv4>/24 
wlP9s9           UP             <redacted-ipv4>/24 
docker0          DOWN           <redacted-ipv4>/16 

lo               UNKNOWN        <redacted-ipv6>/128 
enP7s7           UP             <redacted-ipv6>/64 
wlP9s9           UP             <redacted-ipv6>/64 

default via <redacted-ipv4> dev wlP9s9 proto dhcp src <redacted-ipv4> metric 600 

== storage (df, lsblk model/size) ==
Filesystem      Size  Used Avail Use% Mounted on
tmpfs            12G  3.6M   12G   1% /run
efivarfs        256K   20K  237K   8% /sys/firmware/efi/efivars
/dev/nvme0n1p2  3.7T  182G  3.4T   6% /
tmpfs            60G     0   60G   0% /dev/shm
tmpfs           5.0M  8.0K  5.0M   1% /run/lock
/dev/nvme0n1p1  511M  6.4M  505M   2% /boot/efi
tmpfs            12G  116K   12G   1% /run/user/1000
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
loop16    560K                               0 loop
loop17  221.2M                               0 loop
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

== peer ping (best effort, rtt) ==
peers: spark2.local spark1.local
spark2.local: ping_resolve_failed
spark1.local: ping_resolve_failed

== target: spark0@spark1.local ==
ssh: Could not resolve hostname spark1.local: nodename nor servname provided, or not known
ssh: failed rc=255

== target: spark0@spark2.local ==
ssh: Could not resolve hostname spark2.local: nodename nor servname provided, or not known
ssh: failed rc=255

== probe summary ==
ssh failures: 2
