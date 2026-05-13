== local meta ==
Wed May 13 00:06:23 UTC 2026
git: 6562530
probe args: aitopatom-9ab9.local spark1.local spark2.local
resolved targets: spark0@aitopatom-9ab9.local spark0@spark1.local spark0@spark2.local
lat iters: 3
ssh opts: -o BatchMode=yes -o ConnectTimeout=10 -o StrictHostKeyChecking=accept-new -o ServerAliveInterval=5 -o ServerAliveCountMax=2
known_hosts: spark0@aitopatom-9ab9.local -> /private/tmp/ds4_spark_known_hosts.aitopatom-9ab9.local
known_hosts: spark0@spark1.local -> /private/tmp/ds4_spark_known_hosts.spark1.local
known_hosts: spark0@spark2.local -> /private/tmp/ds4_spark_known_hosts.spark2.local

== target: spark0@aitopatom-9ab9.local ==
status: ok (n=3)
ssh_latency_ms_p50: 280.0
ssh_latency_ms_min: 280.0
ssh_latency_ms_max: 290.0
ssh_latency_ms_avg: 283.3

== target: spark0@spark1.local ==
sample 1: failed (resolve_failed)
ssh: Could not resolve hostname spark1.local: nodename nor servname provided, or not known
status: failed

== target: spark0@spark2.local ==
sample 1: failed (resolve_failed)
ssh: Could not resolve hostname spark2.local: nodename nor servname provided, or not known
status: failed

