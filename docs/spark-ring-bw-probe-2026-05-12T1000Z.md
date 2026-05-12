== local meta ==
Tue May 12 10:01:42 UTC 2026
git: 0ccbe9e
probe args: spark0@aitopatom-9ab9.local spark1@spark1.local spark2@spark2.local
resolved targets: spark0@aitopatom-9ab9.local spark1@spark1.local spark2@spark2.local
bw mb: 16
bw dir: both
ssh opts: -o BatchMode=yes -o ConnectTimeout=10 -o StrictHostKeyChecking=accept-new -o ServerAliveInterval=5 -o ServerAliveCountMax=2
known_hosts: spark0@aitopatom-9ab9.local -> /private/tmp/ds4_spark_known_hosts.aitopatom-9ab9.local
known_hosts: spark1@spark1.local -> /private/tmp/ds4_spark_known_hosts.spark1.local
known_hosts: spark2@spark2.local -> /private/tmp/ds4_spark_known_hosts.spark2.local

== target: spark0@aitopatom-9ab9.local ==
down (remote->mac) 16 MiB: 16777216 bytes transferred in 0.470501 secs (35658194 bytes/sec) [MiB/s=34.0 Mbit/s=285.3]
up (mac->remote) 16 MiB: 16777216 bytes (17 MB, 16 MiB) copied, 0.0782411 s, 214 MB/s [MiB/s=204.5 Mbit/s=1715.4]

== target: spark1@spark1.local ==
down (remote->mac) 16 MiB: ssh status: resolve_failed
ssh: ssh: Could not resolve hostname spark1.local: nodename nor servname provided, or not known
dd: 0 bytes transferred in 5.005928 secs (0 bytes/sec)
failed
up (mac->remote) 16 MiB: ssh status: resolve_failed
ssh: ssh: Could not resolve hostname spark1.local: nodename nor servname provided, or not known
failed

== target: spark2@spark2.local ==
down (remote->mac) 16 MiB: ssh status: resolve_failed
ssh: ssh: Could not resolve hostname spark2.local: nodename nor servname provided, or not known
dd: 0 bytes transferred in 5.004445 secs (0 bytes/sec)
failed
up (mac->remote) 16 MiB: ssh status: resolve_failed
ssh: ssh: Could not resolve hostname spark2.local: nodename nor servname provided, or not known
failed

== probe summary ==
failures: 4
