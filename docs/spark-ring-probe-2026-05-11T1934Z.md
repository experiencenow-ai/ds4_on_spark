== local meta ==
Mon May 11 19:35:32 UTC 2026
git: 4e3a1c4
probe args: aitopatom-9ab9.local spark1.local spark2.local
resolved targets: spark0@aitopatom-9ab9.local spark0@spark1.local spark0@spark2.local
topology: ring
ssh opts: -o BatchMode=yes -o ConnectTimeout=10 -o StrictHostKeyChecking=accept-new -o ServerAliveInterval=5 -o ServerAliveCountMax=2
known_hosts: spark0@aitopatom-9ab9.local -> /private/tmp/ds4_spark_known_hosts.aitopatom-9ab9.local
known_hosts: spark0@spark1.local -> /private/tmp/ds4_spark_known_hosts.spark1.local
known_hosts: spark0@spark2.local -> /private/tmp/ds4_spark_known_hosts.spark2.local

== target: spark0@aitopatom-9ab9.local ==
ssh: Could not resolve hostname aitopatom-9ab9.local: nodename nor servname provided, or not known
ssh: failed rc=255

== target: spark0@spark1.local ==
ssh: Could not resolve hostname spark1.local: nodename nor servname provided, or not known
ssh: failed rc=255

== target: spark0@spark2.local ==
ssh: Could not resolve hostname spark2.local: nodename nor servname provided, or not known
ssh: failed rc=255

== probe summary ==
ssh failures: 3
