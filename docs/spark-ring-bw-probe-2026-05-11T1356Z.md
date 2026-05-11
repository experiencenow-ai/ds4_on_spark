== local meta ==
Mon May 11 13:56:20 UTC 2026
git: dacc09f
probe args: aitopatom-9ab9.local spark1.local spark2.local
resolved targets: spark0@aitopatom-9ab9.local spark0@spark1.local spark0@spark2.local
bw mb: 16
bw dir: both
ssh opts: -o BatchMode=yes -o ConnectTimeout=10 -o StrictHostKeyChecking=accept-new -o ServerAliveInterval=5 -o ServerAliveCountMax=2
known_hosts: spark0@aitopatom-9ab9.local -> /private/tmp/ds4_spark_known_hosts.aitopatom-9ab9.local
known_hosts: spark0@spark1.local -> /private/tmp/ds4_spark_known_hosts.spark1.local
known_hosts: spark0@spark2.local -> /private/tmp/ds4_spark_known_hosts.spark2.local

== target: spark0@aitopatom-9ab9.local ==
down (remote->mac) 16 MiB: 16777216 bytes transferred in 0.679153 secs (24703146 bytes/sec)
up (mac->remote) 16 MiB: 16777216 bytes (17 MB, 16 MiB) copied, 0.104922 s, 160 MB/s

== target: spark0@spark1.local ==
down (remote->mac) 16 MiB: 0 bytes transferred in 5.002827 secs (0 bytes/sec)
up (mac->remote) 16 MiB: failed

== target: spark0@spark2.local ==
down (remote->mac) 16 MiB: 0 bytes transferred in 5.005344 secs (0 bytes/sec)
up (mac->remote) 16 MiB: failed

== probe summary ==
failures: 2
