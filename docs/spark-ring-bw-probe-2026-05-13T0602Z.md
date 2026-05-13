== local meta ==
Wed May 13 06:03:57 UTC 2026
git: 93cc51c
probe args: aitopatom-9ab9.local spark1.local spark2.local
resolved targets: spark0@aitopatom-9ab9.local spark0@spark1.local spark0@spark2.local
bw mb: 16
bw dir: both
ssh opts: -o BatchMode=yes -o ConnectTimeout=10 -o StrictHostKeyChecking=accept-new -o ServerAliveInterval=5 -o ServerAliveCountMax=2
known_hosts: spark0@aitopatom-9ab9.local -> /private/tmp/ds4_spark_known_hosts.aitopatom-9ab9.local
known_hosts: spark0@spark1.local -> /private/tmp/ds4_spark_known_hosts.spark1.local
known_hosts: spark0@spark2.local -> /private/tmp/ds4_spark_known_hosts.spark2.local

== target: spark0@aitopatom-9ab9.local ==
down (remote->mac) 16 MiB: 16777216 bytes transferred in 0.376724 secs (44534503 bytes/sec) [MiB/s=42.5 Mbit/s=356.3]
up (mac->remote) 16 MiB: 16777216 bytes (17 MB, 16 MiB) copied, 0.0762678 s, 220 MB/s [MiB/s=209.8 Mbit/s=1759.8]

== target: spark0@spark1.local ==
down (remote->mac) 16 MiB: ssh status: resolve_failed
ssh: ssh: Could not resolve hostname spark1.local: nodename nor servname provided, or not known
dd: 0 bytes transferred in 5.006616 secs (0 bytes/sec)
failed
up (mac->remote) 16 MiB: ssh status: resolve_failed
ssh: ssh: Could not resolve hostname spark1.local: nodename nor servname provided, or not known
failed

== target: spark0@spark2.local ==
down (remote->mac) 16 MiB: ssh status: resolve_failed
ssh: ssh: Could not resolve hostname spark2.local: nodename nor servname provided, or not known
dd: 0 bytes transferred in 5.005777 secs (0 bytes/sec)
failed
up (mac->remote) 16 MiB: ssh status: resolve_failed
ssh: ssh: Could not resolve hostname spark2.local: nodename nor servname provided, or not known
failed

== probe summary ==
failures: 4
