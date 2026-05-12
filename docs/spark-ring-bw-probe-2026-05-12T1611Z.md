== local meta ==
Tue May 12 16:13:20 UTC 2026
git: 2cc6b9b
probe args: spark0@aitopatom-9ab9.local spark1@spark1.local spark2@spark2.local
resolved targets: spark0@aitopatom-9ab9.local spark1@spark1.local spark2@spark2.local
bw mb: 16
bw dir: both
ssh opts: -o BatchMode=yes -o ConnectTimeout=10 -o StrictHostKeyChecking=accept-new -o ServerAliveInterval=5 -o ServerAliveCountMax=2
known_hosts: spark0@aitopatom-9ab9.local -> /private/tmp/ds4_spark_known_hosts.aitopatom-9ab9.local
known_hosts: spark1@spark1.local -> /private/tmp/ds4_spark_known_hosts.spark1.local
known_hosts: spark2@spark2.local -> /private/tmp/ds4_spark_known_hosts.spark2.local

== target: spark0@aitopatom-9ab9.local ==
down (remote->mac) 16 MiB: 16777216 bytes transferred in 1.167933 secs (14364879 bytes/sec) [MiB/s=13.7 Mbit/s=114.9]
up (mac->remote) 16 MiB: 16777216 bytes (17 MB, 16 MiB) copied, 0.752042 s, 22.3 MB/s [MiB/s=21.3 Mbit/s=178.5]

== target: spark1@spark1.local ==
down (remote->mac) 16 MiB: ssh status: resolve_failed
ssh: ssh: Could not resolve hostname spark1.local: nodename nor servname provided, or not known
dd: 0 bytes transferred in 5.005515 secs (0 bytes/sec)
failed
up (mac->remote) 16 MiB: ssh status: resolve_failed
ssh: ssh: Could not resolve hostname spark1.local: nodename nor servname provided, or not known
failed

== target: spark2@spark2.local ==
down (remote->mac) 16 MiB: ssh status: resolve_failed
ssh: ssh: Could not resolve hostname spark2.local: nodename nor servname provided, or not known
dd: 0 bytes transferred in 5.005210 secs (0 bytes/sec)
failed
up (mac->remote) 16 MiB: ssh status: resolve_failed
ssh: ssh: Could not resolve hostname spark2.local: nodename nor servname provided, or not known
failed

== probe summary ==
failures: 4
