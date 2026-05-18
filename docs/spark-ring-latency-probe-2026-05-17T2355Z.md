== local meta ==
Sun May 17 23:55:32 UTC 2026
git: (unknown)
probe args: spark0@aitopatom-9ab9.local spark1@edgexpert-d623.local
resolved targets: spark0@aitopatom-9ab9.local spark1@edgexpert-d623.local
lat iters: 3
ssh opts: -o BatchMode=yes -o ConnectTimeout=10 -o StrictHostKeyChecking=accept-new -o ServerAliveInterval=5 -o ServerAliveCountMax=2
known_hosts: spark0@aitopatom-9ab9.local -> /private/tmp/ds4_spark_known_hosts.aitopatom-9ab9.local
known_hosts: spark1@edgexpert-d623.local -> /private/tmp/ds4_spark_known_hosts.edgexpert-d623.local

== target: spark0@aitopatom-9ab9.local ==
status: ok (n=3)
ssh_latency_ms_p50: 320.0
ssh_latency_ms_min: 320.0
ssh_latency_ms_max: 340.0
ssh_latency_ms_avg: 326.7

== target: spark1@edgexpert-d623.local ==
status: ok (n=3)
ssh_latency_ms_p50: 320.0
ssh_latency_ms_min: 320.0
ssh_latency_ms_max: 400.0
ssh_latency_ms_avg: 346.7
