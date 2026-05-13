== local meta ==
Wed May 13 01:02:45 UTC 2026
git: 5cb1967
probe args: aitopatom-9ab9.local spark1.local spark2.local
resolved targets: spark0@aitopatom-9ab9.local spark0@spark1.local spark0@spark2.local
bw mb: 16
bw dir: both
ssh opts: -o BatchMode=yes -o ConnectTimeout=10 -o StrictHostKeyChecking=accept-new -o ServerAliveInterval=5 -o ServerAliveCountMax=2
known_hosts: spark0@aitopatom-9ab9.local -> /private/tmp/ds4_spark_known_hosts.aitopatom-9ab9.local
known_hosts: spark0@spark1.local -> /private/tmp/ds4_spark_known_hosts.spark1.local
known_hosts: spark0@spark2.local -> /private/tmp/ds4_spark_known_hosts.spark2.local

== target: spark0@aitopatom-9ab9.local ==
down (remote->mac) 16 MiB: 16777216 bytes transferred in 0.397049 secs (42254775 bytes/sec) [MiB/s=40.3 Mbit/s=338.0]
up (mac->remote) 16 MiB: 16777216 bytes (17 MB, 16 MiB) copied, 0.0849333 s, 198 MB/s [MiB/s=188.4 Mbit/s=1580.3]

== target: spark0@spark1.local ==
down (remote->mac) 16 MiB: ssh status: resolve_failed
ssh: ssh: Could not resolve hostname spark1.local: nodename nor servname provided, or not known
dd: 0 bytes transferred in 5.004263 secs (0 bytes/sec)
failed
up (mac->remote) 16 MiB: ssh status: resolve_failed
ssh: ssh: Could not resolve hostname spark1.local: nodename nor servname provided, or not known
failed

== target: spark0@spark2.local ==
down (remote->mac) 16 MiB: ssh status: resolve_failed
ssh: ssh: Could not resolve hostname spark2.local: nodename nor servname provided, or not known
dd: 0 bytes transferred in 5.004954 secs (0 bytes/sec)
failed
up (mac->remote) 16 MiB: ssh status: resolve_failed
ssh: ssh: Could not resolve hostname spark2.local: nodename nor servname provided, or not known
failed

== probe summary ==
failures: 4
