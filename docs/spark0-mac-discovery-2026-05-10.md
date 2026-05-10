# Spark0 Mac Discovery Snapshot

Date: 2026-05-10 (UTC) from the Mac workspace.

Commands run:

```bash
REDACT=1 DS4_GIT_DIR=.git-codex DS4_GIT_WORK_TREE=. ./scripts/mac_spark_discovery.sh aitopatom-9ab9.local spark1.local | tee /private/tmp/ds4_mac_spark_discovery_redacted_2026-05-10T0007Z_loop_v11.txt
REDACT=1 DS4_GIT_DIR=.git-codex DS4_GIT_WORK_TREE=. ./scripts/mac_spark_discovery.sh aitopatom-9ab9.local spark1.local | tee /private/tmp/ds4_mac_spark_discovery_redacted_2026-05-10T0111Z_loop_v4.txt
```

Notes:

- This output is redacted (`REDACT=1`) to remove IPv4/IPv6/MAC addresses.
- `spark1.local` is still not reachable (likely not provisioned / not on the same mDNS domain yet).

## Excerpts (Redacted)

```text
== meta ==
Sun May 10 01:11:29 UTC 2026
git: 3b928be
targets: aitopatom-9ab9.local spark1.local

== ssh service browse, 5 seconds ==
Browsing for _ssh._tcp.local
DATE: ---Sun 10 May 2026---
Timestamp     A/R    Flags  if Domain               Service Type         Instance Name
 1:11:29.820  Add        3  10 local.               _ssh._tcp.           aitopatom-9ab9 SSH

== mdns resolution, 3 seconds each ==
-- aitopatom-9ab9.local --
Timestamp     A/R  Flags         IF  Hostname                               Address                                      TTL
 1:11:34.824  Add  40000003      26  aitopatom-9ab9.local.                  <redacted-ipv6>%en1  120
 1:11:34.824  Add  40000002      26  aitopatom-9ab9.local.                  <redacted-ipv4>                                120
-- spark1.local --

== known target checks ==
aitopatom-9ab9.local: ssh reachable
spark1.local: not reachable
```

```text
== meta ==
Sun May 10 00:07:25 UTC 2026
git: 228ec92
targets: aitopatom-9ab9.local spark1.local

== ssh service browse, 5 seconds ==
Browsing for _ssh._tcp.local
DATE: ---Sun 10 May 2026---
Timestamp     A/R    Flags  if Domain               Service Type         Instance Name
 0:07:25.630  Add        3  26 local.               _ssh._tcp.           aitopatom-9ab9 SSH

== mdns resolution, 3 seconds each ==
-- aitopatom-9ab9.local --
Timestamp     A/R  Flags         IF  Hostname                               Address                                      TTL
 0:07:30.634  Add  40000003      10  aitopatom-9ab9.local.                  <redacted-ipv6>%en0  120
 0:07:30.634  Add  40000002      10  aitopatom-9ab9.local.                  <redacted-ipv4>                                     120
-- spark1.local --

== known target checks ==
aitopatom-9ab9.local: ssh reachable
spark1.local: not reachable
```
