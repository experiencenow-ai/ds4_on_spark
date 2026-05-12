== local meta ==
Tue May 12 21:40:34 UTC 2026
git: 8f5ce72
probe args: spark0@aitopatom-9ab9.local spark1@spark1.local spark2@spark2.local
resolved targets: spark0@aitopatom-9ab9.local spark1@spark1.local spark2@spark2.local
lat iters: 3
ssh opts: -o BatchMode=yes -o ConnectTimeout=10 -o StrictHostKeyChecking=accept-new -o ServerAliveInterval=5 -o ServerAliveCountMax=2
known_hosts: spark0@aitopatom-9ab9.local -> /private/tmp/ds4_spark_known_hosts.aitopatom-9ab9.local
known_hosts: spark1@spark1.local -> /private/tmp/ds4_spark_known_hosts.spark1.local
known_hosts: spark2@spark2.local -> /private/tmp/ds4_spark_known_hosts.spark2.local

== target: spark0@aitopatom-9ab9.local ==
status: ok (n=3)
ssh_latency_ms_p50: 280.0
ssh_latency_ms_min: 270.0
ssh_latency_ms_max: 280.0
ssh_latency_ms_avg: 276.7

== target: spark1@spark1.local ==
sample 1: failed (resolve_failed)
ssh: Could not resolve hostname spark1.local: nodename nor servname provided, or not known
status: failed

== target: spark2@spark2.local ==
sample 1: failed (resolve_failed)
ssh: Could not resolve hostname spark2.local: nodename nor servname provided, or not known
status: failed

