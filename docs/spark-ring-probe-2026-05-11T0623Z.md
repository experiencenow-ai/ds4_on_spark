== local meta ==
Mon May 11 06:24:32 UTC 2026
git: 5e19d9f
probe args: aitopatom-9ab9.local spark1.local spark2.local spark3.local
resolved targets: spark0@aitopatom-9ab9.local spark0@spark1.local spark0@spark2.local spark0@spark3.local
host-only targets: aitopatom-9ab9.local spark1.local spark2.local spark3.local
ssh opts: -o BatchMode=yes -o ConnectTimeout=10 -o StrictHostKeyChecking=accept-new -o ServerAliveInterval=5 -o ServerAliveCountMax=2
known_hosts: spark0@aitopatom-9ab9.local -> /private/tmp/ds4_spark_known_hosts.aitopatom-9ab9.local
known_hosts: spark0@spark1.local -> /private/tmp/ds4_spark_known_hosts.spark1.local
known_hosts: spark0@spark2.local -> /private/tmp/ds4_spark_known_hosts.spark2.local
known_hosts: spark0@spark3.local -> /private/tmp/ds4_spark_known_hosts.spark3.local

== target: spark0@aitopatom-9ab9.local ==
== meta ==
Mon May 11 06:24:32 UTC 2026
target user: spark0

== identity ==
aitopatom-9ab9
Linux aitopatom-9ab9 6.17.0-1014-nvidia #14-Ubuntu SMP PREEMPT_DYNAMIC Tue Mar 17 19:01:40 UTC 2026 aarch64 aarch64 aarch64 GNU/Linux
 15:24:32 up 2 days,  9:27,  2 users,  load average: 0.01, 0.03, 0.11

== clock ==
               Local time: Mon 2026-05-11 15:24:33 KST
           Universal time: Mon 2026-05-11 06:24:33 UTC
                 RTC time: Mon 2026-05-11 06:24:32
                Time zone: Asia/Seoul (KST, +0900)
System clock synchronized: yes
              NTP service: active
          RTC in local TZ: no
-- date epoch --
1778480673

== network (summary) ==
lo               UNKNOWN        <redacted-mac> <LOOPBACK,UP,LOWER_UP> 
enP7s7           UP             <redacted-mac> <BROADCAST,MULTICAST,UP,LOWER_UP> 
enp1s0f0np0      DOWN           <redacted-mac> <NO-CARRIER,BROADCAST,MULTICAST,UP> 
enp1s0f1np1      DOWN           <redacted-mac> <NO-CARRIER,BROADCAST,MULTICAST,UP> 
enP2p1s0f0np0    DOWN           <redacted-mac> <NO-CARRIER,BROADCAST,MULTICAST,UP> 
enP2p1s0f1np1    DOWN           <redacted-mac> <NO-CARRIER,BROADCAST,MULTICAST,UP> 
wlP9s9           UP             <redacted-mac> <BROADCAST,MULTICAST,UP,LOWER_UP> 
docker0          DOWN           <redacted-mac> <NO-CARRIER,BROADCAST,MULTICAST,UP> 

lo               UNKNOWN        <redacted-ipv4>/8 <redacted-ipv6>/128 
enP7s7           UP             <redacted-ipv4>/24 <redacted-ipv6>/64 
enp1s0f0np0      DOWN           
enp1s0f1np1      DOWN           
enP2p1s0f0np0    DOWN           
enP2p1s0f1np1    DOWN           
wlP9s9           UP             <redacted-ipv4>/24 <redacted-ipv6>/64 
docker0          DOWN           <redacted-ipv4>/16 

== mtu (all links) ==
lo mtu 65536
enP7s7 mtu 9000
enp1s0f0np0 mtu 1500
enp1s0f1np1 mtu 1500
enP2p1s0f0np0 mtu 1500
enP2p1s0f1np1 mtu 1500
wlP9s9 mtu 1500
docker0 mtu 1500

== storage (non-secret) ==
-- lsblk (disks) --
NAME    TYPE   SIZE MODEL
loop0   loop     4K 
loop1   loop    69M 
loop2   loop  61.9M 
loop3   loop  10.2M 
loop4   loop 241.1M 
loop5   loop  15.6M 
loop6   loop   503M 
loop7   loop  12.2M 
loop8   loop 552.9M 
loop9   loop 174.6M 
loop10  loop  91.7M 
loop11  loop  42.6M 
loop12  loop 221.2M 
loop13  loop   552K 
loop14  loop    10M 
loop15  loop 234.8M 
loop16  loop   560K 
nvme0n1 disk   3.7T SAMSUNG MZALC4T0HBL1-00B07
-- lsblk (mounts, no loops) --
NAME        TYPE   SIZE MODEL                      MOUNTPOINT
nvme0n1     disk   3.7T SAMSUNG MZALC4T0HBL1-00B07 
|-nvme0n1p1 part   512M                            /boot/efi
`-nvme0n1p2 part   3.7T                            /

== gpu (non-secret) ==
NVIDIA-SMI version  : 580.142
NVML version        : 580.142
DRIVER version      : 580.142
CUDA Version        : 13.0
0, NVIDIA GB10, 12.1, 0000000F:01:00.0, 580.142


== target: spark0@spark1.local ==
ssh: Could not resolve hostname spark1.local: nodename nor servname provided, or not known
ssh: failed rc=255

== target: spark0@spark2.local ==
ssh: Could not resolve hostname spark2.local: nodename nor servname provided, or not known
ssh: failed rc=255

== target: spark0@spark3.local ==
ssh: Could not resolve hostname spark3.local: nodename nor servname provided, or not known
ssh: failed rc=255

== ring summary ==
ssh failures: 3
