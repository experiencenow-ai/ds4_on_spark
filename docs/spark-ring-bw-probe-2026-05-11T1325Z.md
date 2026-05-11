== local meta ==
Mon May 11 13:25:11 UTC 2026
git: d5dcebf
probe args: aitopatom-9ab9.local spark1.local spark2.local
resolved targets: spark0@aitopatom-9ab9.local spark0@spark1.local spark0@spark2.local
bw mb: 8
bw dir: both
ssh opts: -o BatchMode=yes -o ConnectTimeout=10 -o StrictHostKeyChecking=accept-new -o ServerAliveInterval=5 -o ServerAliveCountMax=2
known_hosts: spark0@aitopatom-9ab9.local -> /private/tmp/ds4_spark_known_hosts.aitopatom-9ab9.local
known_hosts: spark0@spark1.local -> /private/tmp/ds4_spark_known_hosts.spark1.local
known_hosts: spark0@spark2.local -> /private/tmp/ds4_spark_known_hosts.spark2.local

== target: spark0@aitopatom-9ab9.local ==
down (remote->mac) 8 MiB: 0 bytes transferred in 0.280337 secs (0 bytes/sec)
up (mac->remote) 8 MiB: dd: invalid number: '1m'

== target: spark0@spark1.local ==
down (remote->mac) 8 MiB: 0 bytes transferred in 5.006116 secs (0 bytes/sec)
up (mac->remote) 8 MiB: failed

== target: spark0@spark2.local ==
down (remote->mac) 8 MiB: 0 bytes transferred in 5.004763 secs (0 bytes/sec)
up (mac->remote) 8 MiB: failed

== probe summary ==
failures: 2
