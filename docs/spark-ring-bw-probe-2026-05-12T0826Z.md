== local meta ==
Tue May 12 08:28:02 UTC 2026
git: c943f69
probe args: aitopatom-9ab9.local spark1.local spark2.local
resolved targets: spark0@aitopatom-9ab9.local spark0@spark1.local spark0@spark2.local
bw mb: 16
bw dir: both
ssh opts: -o BatchMode=yes -o ConnectTimeout=10 -o StrictHostKeyChecking=accept-new -o ServerAliveInterval=5 -o ServerAliveCountMax=2
known_hosts: spark0@aitopatom-9ab9.local -> /private/tmp/ds4_spark_known_hosts.aitopatom-9ab9.local
known_hosts: spark0@spark1.local -> /private/tmp/ds4_spark_known_hosts.spark1.local
known_hosts: spark0@spark2.local -> /private/tmp/ds4_spark_known_hosts.spark2.local

== target: spark0@aitopatom-9ab9.local ==
down (remote->mac) 16 MiB: 16777216 bytes transferred in 2.015934 secs (8322304 bytes/sec) [MiB/s=7.9 Mbit/s=66.6]
up (mac->remote) 16 MiB: 16777216 bytes (17 MB, 16 MiB) copied, 1.296 s, 12.9 MB/s [MiB/s=12.3 Mbit/s=103.6]

== target: spark0@spark1.local ==
down (remote->mac) 16 MiB: ssh status: resolve_failed
ssh: ssh: Could not resolve hostname spark1.local: nodename nor servname provided, or not known
dd: 0 bytes transferred in 5.003749 secs (0 bytes/sec)
failed
up (mac->remote) 16 MiB: ssh status: resolve_failed
ssh: ssh: Could not resolve hostname spark1.local: nodename nor servname provided, or not known
failed

== target: spark0@spark2.local ==
down (remote->mac) 16 MiB: ssh status: resolve_failed
ssh: ssh: Could not resolve hostname spark2.local: nodename nor servname provided, or not known
dd: 0 bytes transferred in 5.004052 secs (0 bytes/sec)
failed
up (mac->remote) 16 MiB: ssh status: resolve_failed
ssh: ssh: Could not resolve hostname spark2.local: nodename nor servname provided, or not known
failed

== probe summary ==
failures: 4
