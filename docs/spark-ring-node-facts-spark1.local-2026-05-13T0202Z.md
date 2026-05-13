== local meta ==
Wed May 13 02:04:31 UTC 2026
git: fd66e65
probe args: spark1.local
resolved targets: spark0@spark1.local
ssh opts: -o BatchMode=yes -o ConnectTimeout=10 -o StrictHostKeyChecking=accept-new -o ServerAliveInterval=5 -o ServerAliveCountMax=2
ssh wall timeout_s: 25
known_hosts: spark0@spark1.local -> /private/tmp/ds4_spark_known_hosts.spark1.local

== target: spark0@spark1.local ==
ssh: Could not resolve hostname spark1.local: nodename nor servname provided, or not known
ssh: failed rc=255

== probe summary ==
ssh failures: 1
