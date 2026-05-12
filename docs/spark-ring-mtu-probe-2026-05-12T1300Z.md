== local meta ==
Tue May 12 13:02:19 UTC 2026
git: 5ba74df
probe args: spark0@aitopatom-9ab9.local spark1@spark1.local spark2@spark2.local
resolved targets: spark0@aitopatom-9ab9.local spark1@spark1.local spark2@spark2.local
topology: full
mtu payloads: 1472,8972
ssh opts: -o BatchMode=yes -o ConnectTimeout=10 -o StrictHostKeyChecking=accept-new -o ServerAliveInterval=5 -o ServerAliveCountMax=2
known_hosts: spark0@aitopatom-9ab9.local -> /private/tmp/ds4_spark_known_hosts.aitopatom-9ab9.local
known_hosts: spark1@spark1.local -> /private/tmp/ds4_spark_known_hosts.spark1.local
known_hosts: spark2@spark2.local -> /private/tmp/ds4_spark_known_hosts.spark2.local

== target: spark0@aitopatom-9ab9.local ==
== probe meta ==
Tue May 12 13:02:20 UTC 2026
target user: spark0

== mtu probe (ipv4, df, best effort) ==
peers: spark1.local spark2.local
-- spark1.local --
payload=1472: fail status=resolve_failed
payload=8972: fail status=resolve_failed
-- spark2.local --
payload=1472: fail status=resolve_failed
payload=8972: fail status=resolve_failed

== target: spark1@spark1.local ==
ssh: Could not resolve hostname spark1.local: nodename nor servname provided, or not known
ssh: failed rc=255

== target: spark2@spark2.local ==
ssh: Could not resolve hostname spark2.local: nodename nor servname provided, or not known
ssh: failed rc=255

== probe summary ==
ssh failures: 2
