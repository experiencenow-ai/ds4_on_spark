== local meta ==
Mon May 11 18:56:21 UTC 2026
git: 92a9cd7
probe args: aitopatom-9ab9.local spark1.local spark2.local
resolved targets: spark0@aitopatom-9ab9.local spark0@spark1.local spark0@spark2.local
bw mb: 16
bw dir: both
ssh opts: -o BatchMode=yes -o ConnectTimeout=10 -o StrictHostKeyChecking=accept-new -o ServerAliveInterval=5 -o ServerAliveCountMax=2
known_hosts: spark0@aitopatom-9ab9.local -> /private/tmp/ds4_spark_known_hosts.aitopatom-9ab9.local
known_hosts: spark0@spark1.local -> /private/tmp/ds4_spark_known_hosts.spark1.local
known_hosts: spark0@spark2.local -> /private/tmp/ds4_spark_known_hosts.spark2.local

== target: spark0@aitopatom-9ab9.local ==
down (remote->mac) 16 MiB: 16777216 bytes transferred in 0.570524 secs (29406679 bytes/sec)
up (mac->remote) 16 MiB: 16777216 bytes (17 MB, 16 MiB) copied, 0.0549248 s, 305 MB/s

== target: spark0@spark1.local ==
down (remote->mac) 16 MiB: 0 bytes transferred in 5.006571 secs (0 bytes/sec)
ssh: ssh: Could not resolve hostname spark1.local: nodename nor servname provided, or not known
failed
up (mac->remote) 16 MiB: failed

== target: spark0@spark2.local ==
down (remote->mac) 16 MiB: 0 bytes transferred in 5.005639 secs (0 bytes/sec)
ssh: ssh: Could not resolve hostname spark2.local: nodename nor servname provided, or not known
failed
up (mac->remote) 16 MiB: failed

== probe summary ==
failures: 4
