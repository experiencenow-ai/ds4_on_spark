== local meta ==
Sun May 17 23:55:35 UTC 2026
git: (unknown)
probe args: spark0@aitopatom-9ab9.local spark1@edgexpert-d623.local
resolved targets: spark0@aitopatom-9ab9.local spark1@edgexpert-d623.local
topology: full
mtu payloads: 1472,8972
ssh opts: -o BatchMode=yes -o ConnectTimeout=10 -o StrictHostKeyChecking=accept-new -o ServerAliveInterval=5 -o ServerAliveCountMax=2
known_hosts: spark0@aitopatom-9ab9.local -> /private/tmp/ds4_spark_known_hosts.aitopatom-9ab9.local
known_hosts: spark1@edgexpert-d623.local -> /private/tmp/ds4_spark_known_hosts.edgexpert-d623.local

== target: spark0@aitopatom-9ab9.local ==
== probe meta ==
Sun May 17 23:55:35 UTC 2026
target user: spark0

== mtu probe (ipv4, df, best effort) ==
peers: edgexpert-d623.local
-- edgexpert-d623.local --
payload=1472: ok (no DF)
payload=8972: ok (no DF)

== target: spark1@edgexpert-d623.local ==
== probe meta ==
Sun May 17 23:55:35 UTC 2026
target user: spark1

== mtu probe (ipv4, df, best effort) ==
peers: aitopatom-9ab9.local
-- aitopatom-9ab9.local --
payload=1472: ok (no DF)
payload=8972: ok (no DF)
