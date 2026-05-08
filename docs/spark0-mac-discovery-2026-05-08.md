# Spark0 Mac Discovery (2026-05-08)

Command run from the Mac repo root:

```bash
REDACT=1 ./scripts/mac_spark_discovery.sh
```

Output (redacted to avoid MAC + private LAN identifiers):

```text
== meta ==
Fri May  8 22:11:50 UTC 2026

== interfaces ==
-- en0 --
	inet6 <redacted-ipv6>%en0 prefixlen 64 secured scopeid 0xa 
	inet <redacted-ipv4> netmask 0xffff0000 broadcast <redacted-ipv4>
	status: active
-- en1 --
	inet6 <redacted-ipv6>%en1 prefixlen 64 secured scopeid 0x1a 
	inet <redacted-ipv4> netmask 0xffffff00 broadcast <redacted-ipv4>
	status: active

== arp ==
? (<redacted-ipv4>) on en1 ifscope [ethernet]
? (<redacted-ipv4>) on en1 ifscope [ethernet]
? (<redacted-ipv4>) on en1 ifscope [ethernet]
? (<redacted-ipv4>) on en1 ifscope [ethernet]
? (<redacted-ipv4>) on en1 ifscope [ethernet]
? (<redacted-ipv4>) on en0 ifscope [ethernet]
? (<redacted-ipv4>) on en0 ifscope [ethernet]
? (<redacted-ipv4>) on en0 ifscope [ethernet]
? (<redacted-ipv4>) on en0 ifscope permanent [ethernet]
? (<redacted-ipv4>) on en1 ifscope permanent [ethernet]

== ssh service browse, 5 seconds ==
Browsing for _ssh._tcp.local
DATE: ---Fri 08 May 2026---
22:11:50.962  ...STARTING...
Timestamp     A/R    Flags  if Domain               Service Type         Instance Name
22:11:50.962  Add        3  10 local.               _ssh._tcp.           aitopatom-9ab9 SSH
22:11:50.962  Add        3   1 local.               _ssh._tcp.           Mac Studio
22:11:50.963  Add        3  10 local.               _ssh._tcp.           Mac Studio
22:11:50.963  Add        3  26 local.               _ssh._tcp.           Mac Studio
22:11:50.963  Add        2  26 local.               _ssh._tcp.           aitopatom-9ab9 SSH

== mdns resolution, 3 seconds each ==
-- aitopatom-9ab9.local --
DATE: ---Fri 08 May 2026---
22:11:55.964  ...STARTING...
Timestamp     A/R  Flags         IF  Hostname                               Address                                      TTL
22:11:55.965  Add  40000003      26  aitopatom-9ab9.local.                  <redacted-ipv6>%en1  120
22:11:55.965  Add  40000003      10  aitopatom-9ab9.local.                  <redacted-ipv6>%en0  120
22:11:55.965  Add  40000003      26  aitopatom-9ab9.local.                  <redacted-ipv4>                                120
22:11:55.965  Add  40000002      10  aitopatom-9ab9.local.                  <redacted-ipv4>                                     120

== known target checks ==
aitopatom-9ab9.local: ssh reachable
<redacted-ipv4>: not reachable
<redacted-ipv4>: not reachable
<redacted-ipv4>: not reachable
<redacted-ipv4>: not reachable
```
