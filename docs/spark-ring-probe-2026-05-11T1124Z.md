== local meta ==
Mon May 11 11:26:20 UTC 2026
git: 6386c5b
probe args: aitopatom-9ab9.local spark1.local spark2.local
resolved targets: spark0@aitopatom-9ab9.local spark0@spark1.local spark0@spark2.local
topology: full
ssh opts: -o BatchMode=yes -o ConnectTimeout=10 -o StrictHostKeyChecking=accept-new -o ServerAliveInterval=5 -o ServerAliveCountMax=2
known_hosts: spark0@aitopatom-9ab9.local -> /private/tmp/ds4_spark_known_hosts.aitopatom-9ab9.local
known_hosts: spark0@spark1.local -> /private/tmp/ds4_spark_known_hosts.spark1.local
known_hosts: spark0@spark2.local -> /private/tmp/ds4_spark_known_hosts.spark2.local

== target: spark0@aitopatom-9ab9.local ==
== probe meta ==
Mon May 11 11:26:21 UTC 2026
target user: spark0

== identity ==
aitopatom-9ab9
Linux aitopatom-9ab9 6.17.0-1014-nvidia #14-Ubuntu SMP PREEMPT_DYNAMIC Tue Mar 17 19:01:40 UTC 2026 aarch64 aarch64 aarch64 GNU/Linux

== clock ==
utc: 2026-05-11T11:26:21Z
epoch: 1778498781
NTPSynchronized=yes
TimeUSec=Mon 2026-05-11 20:26:21 KST

== network (links + addrs, compact) ==
lo               UNKNOWN        <redacted-mac> <LOOPBACK,UP,LOWER_UP> 
enP7s7           UP             <redacted-mac> <BROADCAST,MULTICAST,UP,LOWER_UP> 
enp1s0f0np0      DOWN           <redacted-mac> <NO-CARRIER,BROADCAST,MULTICAST,UP> 
enp1s0f1np1      DOWN           <redacted-mac> <NO-CARRIER,BROADCAST,MULTICAST,UP> 
enP2p1s0f0np0    DOWN           <redacted-mac> <NO-CARRIER,BROADCAST,MULTICAST,UP> 
enP2p1s0f1np1    DOWN           <redacted-mac> <NO-CARRIER,BROADCAST,MULTICAST,UP> 
wlP9s9           UP             <redacted-mac> <BROADCAST,MULTICAST,UP,LOWER_UP> 
docker0          DOWN           <redacted-mac> <NO-CARRIER,BROADCAST,MULTICAST,UP> 

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
tmpfs            12G  3.3M   12G   1% /run
efivarfs        256K   20K  237K   8% /sys/firmware/efi/efivars
/dev/nvme0n1p2  3.7T  181G  3.4T   6% /
tmpfs            60G     0   60G   0% /dev/shm
tmpfs           5.0M  8.0K  5.0M   1% /run/lock
/dev/nvme0n1p1  511M  6.4M  505M   2% /boot/efi
tmpfs            12G  120K   12G   1% /run/user/1000
NAME        TYPE   SIZE MODEL                      MOUNTPOINT                          FSTYPE
loop0       loop     4K                            /snap/bare/5                        squashfs
loop1       loop    69M                            /snap/core22/2412                   squashfs
loop2       loop  61.9M                            /snap/core24/1588                   squashfs
loop3       loop  10.2M                            /snap/firmware-updater/168          squashfs
loop4       loop 241.1M                            /snap/firefox/8242                  squashfs
loop5       loop  15.6M                            /snap/firmware-updater/227          squashfs
loop6       loop   503M                            /snap/gnome-42-2204/245             squashfs
loop7       loop  12.2M                            /snap/snap-store/1217               squashfs
loop8       loop 552.9M                            /snap/gnome-46-2404/154             squashfs
loop9       loop 174.6M                            /snap/mesa-2404/1166                squashfs
loop10      loop  91.7M                            /snap/gtk-common-themes/1535        squashfs
loop11      loop  42.6M                            /snap/snapd/26869                   squashfs
loop12      loop 221.2M                            /snap/thunderbird/1092              squashfs
loop13      loop   552K                            /snap/snapd-desktop-integration/316 squashfs
loop14      loop    10M                            /snap/snap-store/1271               squashfs
loop15      loop 234.8M                            /snap/firefox/8278                  squashfs
loop16      loop   560K                            /snap/snapd-desktop-integration/363 squashfs
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
nvcc path: /usr/local/cuda/bin/nvcc
nvcc: NVIDIA (R) Cuda compiler driver
Copyright (c) 2005-2025 NVIDIA Corporation
Built on Wed_Aug_20_01:57:39_PM_PDT_2025
Cuda compilation tools, release 13.0, V13.0.88
Build cuda_13.0.r13.0/compiler.36424714_0

== peer ping (best effort, rtt) ==
peers: spark1.local spark2.local
spark1.local: ping_failed
spark2.local: ping_failed

== target: spark0@spark1.local ==
ssh: Could not resolve hostname spark1.local: nodename nor servname provided, or not known
ssh: failed rc=255

== target: spark0@spark2.local ==
ssh: Could not resolve hostname spark2.local: nodename nor servname provided, or not known
ssh: failed rc=255

== probe summary ==
ssh failures: 2
