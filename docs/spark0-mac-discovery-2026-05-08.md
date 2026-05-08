# Spark0 Mac Discovery (2026-05-08)

Command run from the Mac repo root:

```bash
./scripts/mac_spark_discovery.sh
```

Output (redacted to avoid MAC addresses):

```text
== interfaces ==
-- en0 --
-- en1 --

== arp ==
? (172.16.11.215) on en1 ifscope [ethernet]
? (172.16.11.228) on en1 ifscope [ethernet]
? (172.16.11.234) on en1 ifscope [ethernet]
? (172.16.11.254) on en1 ifscope [ethernet]
? (172.16.11.255) on en1 ifscope [ethernet]
? (224.0.0.251) on en1 ifscope permanent [ethernet]

== ssh service browse, 5 seconds ==
Browsing for _ssh._tcp.local
Timestamp     A/R    Flags  if Domain               Service Type         Instance Name
...           Add        3  10 local.               _ssh._tcp.           aitopatom-9ab9 SSH

== known target checks ==
aitopatom-9ab9.local: ssh reachable
10.0.0.2: not reachable
```
