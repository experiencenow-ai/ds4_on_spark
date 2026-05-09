# Spark0 Mac Discovery Snapshot

Date: 2026-05-09 (UTC) from the Mac workspace.

Commands run:

```bash
REDACT=1 ./scripts/mac_spark_discovery.sh > /private/tmp/ds4_mac_spark_discovery_redacted_2026-05-09.txt
```

Notes:

- This output is redacted (`REDACT=1`) to remove IPv4/IPv6/MAC addresses.
- Default targets include `aitopatom-9ab9.local` and `spark1.local`.
- When using `DS4_GIT_DIR` to force a stable `git: <hash>` in the script output, you can also set `DS4_GIT_WORK_TREE=/path/to/worktree` if the git dir is not tied to the current working directory (defaults to `$PWD`).

## Update: Discovery Refresh (2026-05-09 03:48Z)

Commands run:

```bash
REDACT=1 DS4_GIT_DIR=/private/tmp/ds4_git/.git ./scripts/mac_spark_discovery.sh aitopatom-9ab9.local spark1.local > /private/tmp/ds4_mac_spark_discovery_redacted_2026-05-09_07.txt
```

Notes:

- This output is redacted (`REDACT=1`) to remove IPv4/IPv6/MAC addresses.

```text
== meta ==
Sat May  9 03:48:32 UTC 2026
git: 28dad98

== interfaces ==
-- en0 --
	inet6 <redacted-ipv6>%en0 prefixlen 64 secured scopeid 0xa 
	inet <redacted-ipv4> netmask 0xffff0000 broadcast <redacted-ipv4>
	status: active
-- en1 --
	inet6 <redacted-ipv6>%en1 prefixlen 64 secured scopeid 0x1a 
	inet <redacted-ipv4> netmask 0xffffff00 broadcast <redacted-ipv4>
	status: active

== routes (redacted) ==
Routing tables

Internet:
Destination        Gateway            Flags               Netif Expire
default            <redacted-ipv4>      UGScg                 en1       
127                <redacted-ipv4>          UCS                   lo0       
<redacted-ipv4>          <redacted-ipv4>          UH                    lo0       
<redacted-ipv4>     <redacted-ipv4>     UH                    lo0       
169.254            link#26            UCS                   en1      !
169.254            link#10            UCSI                  en0      !
172.16.11/24       link#26            UCS                   en1      !
<redacted-ipv4>      <redacted-mac>  UHLWI                 en1   1041
<redacted-ipv4>      <redacted-mac>  UHLWIi                en1   1189
<redacted-ipv4>      <redacted-mac>  UHLWI                 en1      !
<redacted-ipv4>      <redacted-mac>   UHLWI                 en1    606
<redacted-ipv4>/32   link#26            UCS                   en1      !
<redacted-ipv4>/32   link#26            UCS                   en1      !
<redacted-ipv4>      <redacted-mac>  UHLWIir               en1   1185
<redacted-ipv4>      <redacted-mac>  UHLWbI                en1      !
192.168.0/16       link#10            UCS                   en0      !
<redacted-ipv4>/32   link#10            UCS                   en0      !
224.0.0/4          link#26            UmCS                  en1      !
224.0.0/4          link#10            UmCSI                 en0      !
<redacted-ipv4>        <redacted-mac>      UHmLWI                en0       
<redacted-ipv4>        <redacted-mac>      UHmLWI                en1       
<redacted-ipv4>/32 link#26            UCS                   en1      !
<redacted-ipv4>/32 link#10            UCSI                  en0      !
Routing tables

Internet6:
Destination                             Gateway                                 Flags               Netif Expire
default                                 <redacted-ipv6>                            UGcg                 en1       
default                                 <redacted-ipv6>                            UGcg                 en0       
<redacted-ipv6>                             <redacted-ipv6>                             UH                    lo0       
<redacted-ipv6>                                 <redacted-ipv6>                             UHLW                 en1       
<redacted-ipv6>                                 <redacted-ipv6>                             UHLW                 en0       
<redacted-ipv6>                                 <redacted-ipv6>                             UHLW                 en1       
<redacted-ipv6>                                 <redacted-ipv6>                             UHLW                 en0       
<redacted-ipv6>                               <redacted-ipv6>                             UHLW                 en1       
<redacted-ipv6>                               <redacted-ipv6>                             UHLW                 en0       
<redacted-ipv6>%lo0                           <redacted-ipv6>%lo0                           UH                    lo0       
<redacted-ipv6>                               <redacted-ipv6>                             UHLW                 en1       
<redacted-ipv6>                               <redacted-ipv6>                             UHLW                 en0       
<redacted-ipv6>                               <redacted-ipv6>                             UHLW                 en1       
<redacted-ipv6>                               <redacted-ipv6>                             UHLW                 en0       
<redacted-ipv6>                               <redacted-ipv6>                             UHLW                 en1       
<redacted-ipv6>                               <redacted-ipv6>                             UHLW                 en0       
<redacted-ipv6>                               <redacted-ipv6>                             UHLW                 en1       
<redacted-ipv6>                               <redacted-ipv6>                             UHLW                 en0       
<redacted-ipv6>                               <redacted-ipv6>                             UHLW                 en1       
<redacted-ipv6>                               <redacted-ipv6>                             UHLW                 en0       
<redacted-ipv6>                               <redacted-ipv6>                             UHLW                 en1       
<redacted-ipv6>                               <redacted-ipv6>                             UHLW                 en0       
<redacted-ipv6>                               <redacted-ipv6>                             UHLW                 en1       
<redacted-ipv6>                               <redacted-ipv6>                             UHLW                 en0       
<redacted-ipv6>                               <redacted-ipv6>                             UHLW                 en1       
<redacted-ipv6>                               <redacted-ipv6>                             UHLW                 en0       
<redacted-ipv6>                               <redacted-ipv6>                             UHLW                 en1       
<redacted-ipv6>                               <redacted-ipv6>                             UHLW                 en0       
<redacted-ipv6>                               <redacted-ipv6>                             UHLW                 en1       
<redacted-ipv6>                               <redacted-ipv6>                             UHLW                 en0       
<redacted-ipv6>%en1                           <redacted-ipv6>%en1                           UHLW                 en1       
<redacted-ipv6>%en0                           <redacted-ipv6>%en0                           UHLW                 en0       
ff00::/8                                ::                                      UmCS                  en1       
ff00::/8                                ::                                      UmCS                  en0       

== arp ==

== ssh service browse, 5 seconds ==
Browsing for _ssh._tcp.local
DATE: ---Sat 09 May 2026---
03:48:37.319  ...STARTING...
Timestamp     A/R    Flags  if Domain               Service Type         Instance Name
03:48:37.320  Add        2   4 local.               _ssh._tcp.           11Mac-mini._ssh._tcp.local.
03:48:37.320  Add        2   4 local.               _ssh._tcp.           aitopatom-9ab9 SSH._ssh._tcp.local.
03:48:37.320  Add        2   4 local.               _ssh._tcp.           11Mac-mini._ssh._tcp.local.
03:48:37.321  Add        2   4 local.               _ssh._tcp.           11Mac-mini._ssh._tcp.local.

== mdns resolution, 3 seconds each ==
-- aitopatom-9ab9.local --
Timestamp     A/R    Flags  if Hostname                               Address                                  TTL
03:48:42.328  Add        2  10 aitopatom-9ab9.local.                   <redacted-ipv4>                         120
03:48:42.328  Add        2  10 aitopatom-9ab9.local.                   <redacted-ipv6>                         120
03:48:42.329  Add        2  10 aitopatom-9ab9.local.                   <redacted-ipv4>                         120
03:48:42.329  Add        2  10 aitopatom-9ab9.local.                   <redacted-ipv6>                         120
-- spark1.local --

== known target checks ==
aitopatom-9ab9.local: ssh reachable
spark1.local: not reachable
```

## Update: Discovery Refresh (2026-05-09 12:00Z)

Commands run:

```bash
REDACT=1 DS4_GIT_DIR=/private/tmp/ds4_git_spark_access_probe15_0w1j2j/repo/.git DS4_GIT_WORK_TREE='/Users/mac/.codex/worktrees/bbda/New project 4' ./scripts/mac_spark_discovery.sh aitopatom-9ab9.local spark1.local > /private/tmp/ds4_mac_spark_discovery_redacted_2026-05-09_probe15d_gitdir.txt
```

Notes:

- This output is redacted (`REDACT=1`) to remove IPv4/IPv6/MAC addresses.
- Spark1 is still not reachable from the Mac on TCP/22 (as of this snapshot).
- Used `DS4_GIT_DIR` + `DS4_GIT_WORK_TREE` overrides for a stable `git: <hash>` stamp (the provided worktree `.git` can be stale due to provenance/permissions).

```text
== meta ==
Sat May  9 12:00:21 UTC 2026
git: 59d06d0

== ssh service browse, 5 seconds ==
Browsing for _ssh._tcp.local
DATE: ---Sat 09 May 2026---
12:00:21.896  ...STARTING...
Timestamp     A/R    Flags  if Domain               Service Type         Instance Name
12:00:21.896  Add        3  10 local.               _ssh._tcp.           aitopatom-9ab9 SSH

== known target checks ==
aitopatom-9ab9.local: ssh reachable
spark1.local: not reachable
```

## Update: Discovery Refresh (2026-05-09 11:26Z)

Commands run:

```bash
REDACT=1 ./scripts/mac_spark_discovery.sh aitopatom-9ab9.local spark1.local > /private/tmp/ds4_mac_spark_discovery_redacted_2026-05-09T1126Z_probe14.txt
```

Notes:

- This output is redacted (`REDACT=1`) to remove IPv4/IPv6/MAC addresses.

```text
== meta ==
Sat May  9 11:26:07 UTC 2026
git: f0c1afa

== ssh service browse, 5 seconds ==
Browsing for _ssh._tcp.local
DATE: ---Sat 09 May 2026---
11:26:07.960  ...STARTING...
Timestamp     A/R    Flags  if Domain               Service Type         Instance Name
11:26:07.960  Add        3  26 local.               _ssh._tcp.           aitopatom-9ab9 SSH

== known target checks ==
aitopatom-9ab9.local: ssh reachable
spark1.local: not reachable
```

## Update: Discovery Refresh (2026-05-09 10:54Z)

Commands run:

```bash
REDACT=1 DS4_GIT_DIR=/private/tmp/ds4_git_spark_access_eb97.Ti5juo/repo/.git DS4_GIT_WORK_TREE='/Users/mac/.codex/worktrees/eb97/New project 4' ./scripts/mac_spark_discovery.sh spark0@aitopatom-9ab9.local spark1.local > /private/tmp/ds4_mac_spark_discovery_redacted_2026-05-09T10-55Z_probe13.txt
```

Notes:

- This output is redacted (`REDACT=1`) to remove IPv4/IPv6/MAC addresses.
- Targets can be passed as `user@host`; the script strips `user@` for the mDNS + TCP/22 checks.

```text
== meta ==
Sat May  9 10:54:36 UTC 2026
git: cd2867f

== known target checks ==
spark0@aitopatom-9ab9.local: ssh reachable
spark1.local: not reachable
```

## Update: Discovery Refresh (2026-05-09 10:27Z)

Commands run:

```bash
REDACT=1 DS4_GIT_DIR=/private/tmp/ds4_git/.git DS4_GIT_WORK_TREE='/Users/mac/.codex/worktrees/27d3/New project 4' ./scripts/mac_spark_discovery.sh aitopatom-9ab9.local spark1.local > /private/tmp/ds4_mac_spark_discovery_redacted_2026-05-09_probe12.txt
```

Notes:

- This output is redacted (`REDACT=1`) to remove IPv4/IPv6/MAC addresses.

```text
== meta ==
Sat May  9 10:27:38 UTC 2026
git: bd10301

== ssh service browse, 5 seconds ==
Browsing for _ssh._tcp.local
DATE: ---Sat 09 May 2026---
10:27:38.140  ...STARTING...
Timestamp     A/R    Flags  if Domain               Service Type         Instance Name
10:27:38.140  Add        3   1 local.               _ssh._tcp.           Mac Studio
10:27:38.140  Add        3  10 local.               _ssh._tcp.           Mac Studio
10:27:38.140  Add        3  10 local.               _ssh._tcp.           aitopatom-9ab9 SSH
10:27:38.140  Add        3  26 local.               _ssh._tcp.           Mac Studio
10:27:38.140  Add        2  26 local.               _ssh._tcp.           aitopatom-9ab9 SSH

== mdns resolution, 3 seconds each ==
-- aitopatom-9ab9.local --
DATE: ---Sat 09 May 2026---
10:27:43.145  ...STARTING...
Timestamp     A/R  Flags         IF  Hostname                               Address                                      TTL
10:27:43.146  Add  40000003      10  aitopatom-9ab9.local.                  <redacted-ipv6>%en0  120
10:27:43.146  Add  40000002      10  aitopatom-9ab9.local.                  <redacted-ipv4>                                     120
-- spark1.local --

== known target checks ==
aitopatom-9ab9.local: ssh reachable
spark1.local: not reachable
```

## Update: Discovery Refresh (2026-05-09 09:57Z)

Commands run:

```bash
REDACT=1 DS4_GIT_DIR=/private/tmp/ds4_git/.git DS4_GIT_WORK_TREE='/Users/mac/.codex/worktrees/3934/New project 4' ./scripts/mac_spark_discovery.sh spark0@aitopatom-9ab9.local spark1.local > /private/tmp/ds4_mac_spark_discovery_redacted_2026-05-09_probe11.txt
```

Notes:

- This output is redacted (`REDACT=1`) to remove IPv4/IPv6/MAC addresses.

```text
== meta ==
Sat May  9 09:57:47 UTC 2026
git: afb55a8

== mdns resolution, 3 seconds each ==
-- aitopatom-9ab9.local --
Timestamp     A/R  Flags         IF  Hostname                               Address                                      TTL
 9:57:52.436  Add  40000003      26  aitopatom-9ab9.local.                  <redacted-ipv6>%en1  120
 9:57:52.437  Add  40000002      26  aitopatom-9ab9.local.                  <redacted-ipv4>                                120
-- spark1.local --

== known target checks ==
spark0@aitopatom-9ab9.local: ssh reachable
spark1.local: not reachable
```

## Update: Discovery Refresh (2026-05-09 07:27Z)

Commands run:

```bash
REDACT=1 ./scripts/mac_spark_discovery.sh spark0@aitopatom-9ab9.local spark1.local > /private/tmp/ds4_mac_spark_discovery_redacted_2026-05-09T0727Z_probe9.txt
```

Notes:

- This output is redacted (`REDACT=1`) to remove IPv4/IPv6/MAC addresses.
- `scripts/mac_spark_discovery.sh` now accepts `user@host` targets and strips the `user@` prefix for mDNS resolution and TCP/22 checks.

```text
== meta ==
Sat May  9 07:27:14 UTC 2026
git: 9172681

== ssh service browse, 5 seconds ==
Browsing for _ssh._tcp.local
DATE: ---Sat 09 May 2026---
Timestamp     A/R    Flags  if Domain               Service Type         Instance Name
 7:27:14.301  Add        3  26 local.               _ssh._tcp.           aitopatom-9ab9 SSH

== mdns resolution, 3 seconds each ==
-- aitopatom-9ab9.local --
DATE: ---Sat 09 May 2026---
Timestamp     A/R  Flags         IF  Hostname                               Address                                      TTL
 7:27:19.311  Add  40000003      10  aitopatom-9ab9.local.                  <redacted-ipv6>%en0  120
 7:27:19.311  Add  40000003      10  aitopatom-9ab9.local.                  <redacted-ipv4>                                     120
-- spark1.local --

== known target checks ==
spark0@aitopatom-9ab9.local: ssh reachable
spark1.local: not reachable
```

## Update: Discovery Refresh (2026-05-09 08:27Z)

Commands run:

```bash
REDACT=1 DS4_GIT_DIR=/private/tmp/ds4_git/.git ./scripts/mac_spark_discovery.sh spark0@aitopatom-9ab9.local spark1.local > /private/tmp/ds4_mac_spark_discovery_redacted_2026-05-09T0827Z_probe11.txt
```

Notes:

- This output is redacted (`REDACT=1`) to remove IPv4/IPv6/MAC addresses.
- The `== routes ==` label is emitted unconditionally; redaction is controlled by `REDACT=1`.

```text
== meta ==
Sat May  9 08:27:01 UTC 2026
git: 0984f56

== routes ==
Routing tables

== mdns resolution, 3 seconds each ==
-- aitopatom-9ab9.local --
DATE: ---Sat 09 May 2026---
-- spark1.local --

== known target checks ==
spark0@aitopatom-9ab9.local: ssh reachable
spark1.local: not reachable
```

## Update: Discovery Refresh (2026-05-09 06:26Z)

Commands run:

```bash
REDACT=1 ./scripts/mac_spark_discovery.sh aitopatom-9ab9.local spark1.local > /private/tmp/ds4_mac_spark_discovery_redacted_2026-05-09_0626Z.txt
```

```text
== meta ==
Sat May  9 06:26:39 UTC 2026
git: 3a6df73

== ssh service browse, 5 seconds ==
Browsing for _ssh._tcp.local
DATE: ---Sat 09 May 2026---
Timestamp     A/R    Flags  if Domain               Service Type         Instance Name
 6:26:39.921  Add        3  26 local.               _ssh._tcp.           aitopatom-9ab9 SSH
 6:26:39.921  Add        3  10 local.               _ssh._tcp.           aitopatom-9ab9 SSH

== mdns resolution, 3 seconds each ==
-- aitopatom-9ab9.local --
DATE: ---Sat 09 May 2026---
Timestamp     A/R  Flags         IF  Hostname                               Address                                      TTL
 6:26:45.124  Add  3             10  aitopatom-9ab9.local.                  <redacted-ipv4>                                     120
 6:26:45.124  Add  2             10  aitopatom-9ab9.local.                  <redacted-ipv6>%en0  120
-- spark1.local --

== known target checks ==
aitopatom-9ab9.local: ssh reachable
spark1.local: not reachable
```

## Update: Discovery Refresh (2026-05-09 05:26Z)

Commands run:

```bash
REDACT=1 ./scripts/mac_spark_discovery.sh aitopatom-9ab9.local spark1.local > /private/tmp/ds4_mac_spark_discovery_redacted_2026-05-09_0526Z.txt
```

Notes:

- This output is redacted (`REDACT=1`) to remove IPv4/IPv6/MAC addresses.

```text
== meta ==
Sat May  9 05:26:44 UTC 2026
git: 310531d

== known target checks ==
aitopatom-9ab9.local: ssh reachable
spark1.local: not reachable
```

## Update: Discovery Refresh (2026-05-09 04:52Z)

Commands run:

```bash
REDACT=1 DS4_GIT_DIR=/private/tmp/ds4_git/.git ./scripts/mac_spark_discovery.sh aitopatom-9ab9.local spark1.local > /private/tmp/ds4_mac_spark_discovery_redacted_2026-05-09_12.txt
```

Notes:

- This output is redacted (`REDACT=1`) to remove IPv4/IPv6/MAC addresses.

```text
== meta ==
Sat May  9 04:52:08 UTC 2026
git: 94439ed

== interfaces ==
-- en0 --
	inet6 <redacted-ipv6>%en0 prefixlen 64 secured scopeid 0xa 
	inet <redacted-ipv4> netmask 0xffff0000 broadcast <redacted-ipv4>
	status: active
-- en1 --
	inet6 <redacted-ipv6>%en1 prefixlen 64 secured scopeid 0x1a 
	inet <redacted-ipv4> netmask 0xffffff00 broadcast <redacted-ipv4>
	status: active

== routes (redacted) ==
Routing tables

Internet:
Destination        Gateway            Flags               Netif Expire
default            <redacted-ipv4>      UGScg                 en1       
127                <redacted-ipv4>          UCS                   lo0       
<redacted-ipv4>          <redacted-ipv4>          UH                    lo0       
<redacted-ipv4>     <redacted-ipv4>     UH                    lo0       
169.254            link#26            UCS                   en1      !
169.254            link#10            UCSI                  en0      !
172.16.11/24       link#26            UCS                   en1      !
<redacted-ipv4>      <redacted-mac>  UHLWI                 en1      !
<redacted-ipv4>      <redacted-mac>  UHLWIi                en1   1190
<redacted-ipv4>      <redacted-mac>  UHLWI                 en1      !
<redacted-ipv4>      <redacted-mac>   UHLWI                 en1     74
<redacted-ipv4>      <redacted-mac>  UHLWI                 en1      !
<redacted-ipv4>      <redacted-mac>   UHLWI                 en1     57
<redacted-ipv4>/32   link#26            UCS                   en1      !
<redacted-ipv4>/32   link#26            UCS                   en1      !
<redacted-ipv4>      <redacted-mac>  UHLWIir               en1   1199
<redacted-ipv4>      <redacted-mac>  UHLWbI                en1      !
192.168.0/16       link#10            UCS                   en0      !
<redacted-ipv4>/32   link#10            UCS                   en0      !
224.0.0/4          link#26            UmCS                  en1      !
224.0.0/4          link#10            UmCSI                 en0      !
<redacted-ipv4>        <redacted-ipv6>      UHmLWI                en0       
<redacted-ipv4>        <redacted-ipv6>      UHmLWI                en1       
<redacted-ipv4>/32 link#26            UCS                   en1      !
<redacted-ipv4>/32 link#10            UCSI                  en0      !
Routing tables

Internet6:
Destination                             Gateway                                 Flags               Netif Expire
default                                 fe80::%utun0                            UGcIg               utun0       
default                                 fe80::%utun1                            UGcIg               utun1       
default                                 fe80::%utun2                            UGcIg               utun2       
default                                 fe80::%utun3                            UGcIg               utun3       
::1                                     ::1                                     UHL                   lo0       
fe80::%lo0/64                           fe80::1%lo0                             UcI                   lo0       
fe80::1%lo0                             link#1                                  UHLI                  lo0       
fe80::%en0/64                           link#10                                 UCI                   en0       
<redacted-ipv6>%en0           <redacted-mac>                       UHLI                  lo0       
<redacted-ipv6>%en0           <redacted-ipv6>                        UHLWIi                en0       
fe80::%en1/64                           link#26                                 UCI                   en1       
<redacted-ipv6>%en1             <redacted-mac>                       UHLWI                 en1       
<redacted-ipv6>%en1             <redacted-mac>                       UHLI                  lo0       
<redacted-ipv6>%en1           <redacted-mac>                       UHLWI                 en1       
fe80::%awdl0/64                         link#27                                 UCI                 awdl0       
<redacted-ipv6>%awdl0         <redacted-mac>                       UHLI                  lo0       
fe80::%llw0/64                          link#28                                 UCI                  llw0       
<redacted-ipv6>%llw0          <redacted-mac>                       UHLI                  lo0       
fe80::%utun0/64                         <redacted-ipv6>%utun0         UcI                 utun0       
<redacted-ipv6>%utun0         link#29                                 UHLI                  lo0       
fe80::%utun1/64                         <redacted-ipv6>%utun1          UcI                 utun1       
<redacted-ipv6>%utun1          link#30                                 UHLI                  lo0       
fe80::%utun2/64                         <redacted-ipv6>%utun2         UcI                 utun2       
<redacted-ipv6>%utun2         link#31                                 UHLI                  lo0       
fe80::%utun3/64                         <redacted-ipv6>%utun3           UcI                 utun3       
<redacted-ipv6>%utun3           link#32                                 UHLI                  lo0       
ff00::/8                                ::1                                     UmCI                  lo0       
ff00::/8                                link#10                                 UmCI                  en0       
ff00::/8                                link#26                                 UmCI                  en1       
ff00::/8                                link#27                                 UmCI                awdl0       
ff00::/8                                link#28                                 UmCI                 llw0       
ff00::/8                                <redacted-ipv6>%utun0         UmCI                utun0       
ff00::/8                                <redacted-ipv6>%utun1          UmCI                utun1       
ff00::/8                                <redacted-ipv6>%utun2         UmCI                utun2       
ff00::/8                                <redacted-ipv6>%utun3           UmCI                utun3       
ff01::%lo0/32                           ::1                                     UmCI                  lo0       

== arp ==
? (<redacted-ipv4>) on en1 ifscope [ethernet]
? (<redacted-ipv4>) on en1 ifscope [ethernet]
? (<redacted-ipv4>) on en1 ifscope [ethernet]
? (<redacted-ipv4>) on en1 ifscope [ethernet]
? (<redacted-ipv4>) on en1 ifscope [ethernet]
? (<redacted-ipv4>) on en0 ifscope permanent [ethernet]
? (<redacted-ipv4>) on en1 ifscope permanent [ethernet]

== ssh service browse, 5 seconds ==
Browsing for _ssh._tcp.local
DATE: ---Sat 09 May 2026---
 4:52:08.989  ...STARTING...
Timestamp     A/R    Flags  if Domain               Service Type         Instance Name
 4:52:08.989  Add        3   1 local.               _ssh._tcp.           Mac Studio
 4:52:08.989  Add        3  10 local.               _ssh._tcp.           Mac Studio
 4:52:08.989  Add        3  10 local.               _ssh._tcp.           aitopatom-9ab9 SSH
 4:52:08.990  Add        3  26 local.               _ssh._tcp.           Mac Studio
 4:52:08.990  Add        2  26 local.               _ssh._tcp.           aitopatom-9ab9 SSH

== mdns resolution, 3 seconds each ==
-- aitopatom-9ab9.local --
DATE: ---Sat 09 May 2026---
 4:52:13.997  ...STARTING...
Timestamp     A/R  Flags         IF  Hostname                               Address                                      TTL
 4:52:13.998  Add  40000003      26  aitopatom-9ab9.local.                  <redacted-ipv6>%en1  120
 4:52:13.998  Add  40000002      26  aitopatom-9ab9.local.                  <redacted-ipv4>                                120
-- spark1.local --

== known target checks ==
aitopatom-9ab9.local: ssh reachable
spark1.local: not reachable
```

## Update: Discovery Refresh (2026-05-09 04:23Z)

Commands run:

```bash
REDACT=1 DS4_GIT_DIR=/private/tmp/ds4_git/.git ./scripts/mac_spark_discovery.sh aitopatom-9ab9.local spark1.local > /private/tmp/ds4_mac_spark_discovery_redacted_2026-05-09_10.txt
```

Notes:

- This output is redacted (`REDACT=1`) to remove IPv4/IPv6/MAC addresses.

```text
== meta ==
Sat May  9 04:23:18 UTC 2026
git: 275b31c

== interfaces ==
-- en0 --
	inet6 <redacted-ipv6>%en0 prefixlen 64 secured scopeid 0xa 
	inet <redacted-ipv4> netmask 0xffff0000 broadcast <redacted-ipv4>
	status: active
-- en1 --
	inet6 <redacted-ipv6>%en1 prefixlen 64 secured scopeid 0x1a 
	inet <redacted-ipv4> netmask 0xffffff00 broadcast <redacted-ipv4>
	status: active

== routes (redacted) ==
Routing tables

Internet:
Destination        Gateway            Flags               Netif Expire
default            <redacted-ipv4>      UGScg                 en1       
127                <redacted-ipv4>          UCS                   lo0       
<redacted-ipv4>          <redacted-ipv4>          UH                    lo0       
<redacted-ipv4>     <redacted-ipv4>     UH                    lo0       
169.254            link#26            UCS                   en1      !
169.254            link#10            UCSI                  en0      !
172.16.11/24       link#26            UCS                   en1      !
<redacted-ipv4>      <redacted-mac>  UHLWI                 en1      !
<redacted-ipv4>      <redacted-mac>  UHLWIi                en1   1189
<redacted-ipv4>      <redacted-mac>  UHLWI                 en1      !
<redacted-ipv4>      <redacted-mac>   UHLWI                 en1      !
<redacted-ipv4>      <redacted-mac>  UHLWI                 en1      !
<redacted-ipv4>/32   link#26            UCS                   en1      !
<redacted-ipv4>/32   link#26            UCS                   en1      !
<redacted-ipv4>      <redacted-mac>  UHLWIir               en1   1169
<redacted-ipv4>      <redacted-mac>  UHLWbI                en1      !
192.168.0/16       link#10            UCS                   en0      !
<redacted-ipv4>/32   link#10            UCS                   en0      !
224.0.0/4          link#26            UmCS                  en1      !
224.0.0/4          link#10            UmCSI                 en0      !
<redacted-ipv4>        <redacted-mac>      UHmLWI                en0       
<redacted-ipv4>        <redacted-mac>      UHmLWI                en1       
<redacted-ipv4>/32 link#26            UCS                   en1      !
<redacted-ipv4>/32 link#10            UCSI                  en0      !
Routing tables

Internet6:
Destination                             Gateway                                 Flags               Netif Expire
default                                 fe80::%utun0                            UGcIg               utun0       
default                                 fe80::%utun1                            UGcIg               utun1       
default                                 fe80::%utun2                            UGcIg               utun2       
default                                 fe80::%utun3                            UGcIg               utun3       
::1                                     ::1                                     UHL                   lo0       
fe80::%lo0/64                           fe80::1%lo0                             UcI                   lo0       
fe80::1%lo0                             link#1                                  UHLI                  lo0       
fe80::%en0/64                           link#10                                 UCI                   en0       
<redacted-ipv6>%en0           <redacted-mac>                       UHLI                  lo0       
<redacted-ipv6>%en0           <redacted-mac>                        UHLWIi                en0       
fe80::%en1/64                           link#26                                 UCI                   en1       
<redacted-ipv6>%en1             <redacted-mac>                       UHLWI                 en1       
<redacted-ipv6>%en1             <redacted-mac>                       UHLI                  lo0       
<redacted-ipv6>%en1           <redacted-mac>                       UHLWI                 en1       
fe80::%awdl0/64                         link#27                                 UCI                 awdl0       
<redacted-ipv6>%awdl0         <redacted-mac>                       UHLI                  lo0       
fe80::%llw0/64                          link#28                                 UCI                  llw0       
<redacted-ipv6>%llw0          <redacted-mac>                       UHLI                  lo0       
fe80::%utun0/64                         <redacted-ipv6>%utun0         UcI                 utun0       
<redacted-ipv6>%utun0         link#29                                 UHLI                  lo0       
fe80::%utun1/64                         <redacted-ipv6>%utun1          UcI                 utun1       
<redacted-ipv6>%utun1          link#30                                 UHLI                  lo0       
fe80::%utun2/64                         <redacted-ipv6>%utun2         UcI                 utun2       
<redacted-ipv6>%utun2         link#31                                 UHLI                  lo0       
fe80::%utun3/64                         <redacted-ipv6>%utun3           UcI                 utun3       
<redacted-ipv6>%utun3           link#32                                 UHLI                  lo0       
ff00::/8                                ::1                                     UmCI                  lo0       
ff00::/8                                link#10                                 UmCI                  en0       
ff00::/8                                link#26                                 UmCI                  en1       
ff00::/8                                link#27                                 UmCI                awdl0       
ff00::/8                                link#28                                 UmCI                 llw0       
ff00::/8                                <redacted-ipv6>%utun0         UmCI                utun0       
ff00::/8                                <redacted-ipv6>%utun1          UmCI                utun1       
ff00::/8                                <redacted-ipv6>%utun2         UmCI                utun2       
ff00::/8                                <redacted-ipv6>%utun3           UmCI                utun3       
ff01::%lo0/32                           ::1                                     UmCI                  lo0       

== arp ==
? (<redacted-ipv4>) on en1 ifscope [ethernet]
? (<redacted-ipv4>) on en1 ifscope [ethernet]
? (<redacted-ipv4>) on en1 ifscope [ethernet]
? (<redacted-ipv4>) on en1 ifscope [ethernet]
? (<redacted-ipv4>) on en1 ifscope [ethernet]
? (<redacted-ipv4>) on en1 ifscope [ethernet]
? (<redacted-ipv4>) on en1 ifscope [ethernet]
? (<redacted-ipv4>) on en0 ifscope permanent [ethernet]
? (<redacted-ipv4>) on en1 ifscope permanent [ethernet]

== ssh service browse, 5 seconds ==
Browsing for _ssh._tcp.local
DATE: ---Sat 09 May 2026---
 4:23:18.161  ...STARTING...
Timestamp     A/R    Flags  if Domain               Service Type         Instance Name
 4:23:18.161  Add        3  26 local.               _ssh._tcp.           aitopatom-9ab9 SSH
 4:23:18.161  Add        3   1 local.               _ssh._tcp.           Mac Studio
 4:23:18.161  Add        3  26 local.               _ssh._tcp.           Mac Studio
 4:23:18.162  Add        3  10 local.               _ssh._tcp.           Mac Studio
 4:23:18.162  Add        2  10 local.               _ssh._tcp.           aitopatom-9ab9 SSH

== mdns resolution, 3 seconds each ==
-- aitopatom-9ab9.local --
DATE: ---Sat 09 May 2026---
 4:23:23.174  ...STARTING...
Timestamp     A/R  Flags         IF  Hostname                               Address                                      TTL
 4:23:23.174  Add  40000003      26  aitopatom-9ab9.local.                  <redacted-ipv6>%en1  120
 4:23:23.174  Add  40000003      10  aitopatom-9ab9.local.                  <redacted-ipv6>%en0  120
 4:23:23.174  Add  40000003      26  aitopatom-9ab9.local.                  <redacted-ipv4>                                120
 4:23:23.174  Add  40000002      10  aitopatom-9ab9.local.                  <redacted-ipv4>                                     120
-- spark1.local --

== known target checks ==
aitopatom-9ab9.local: ssh reachable
spark1.local: not reachable
```

## Update: Discovery Refresh (2026-05-09 05:58Z)

Commands run:

```bash
REDACT=1 DS4_GIT_DIR=/private/tmp/ds4_git/.git ./scripts/mac_spark_discovery.sh aitopatom-9ab9.local spark1.local > /private/tmp/ds4_mac_spark_discovery_redacted_2026-05-09_probe7_2.txt
```

Notes:

- This output is redacted (`REDACT=1`) to remove IPv4/IPv6/MAC addresses.

```text
== meta ==
Sat May  9 05:58:03 UTC 2026
git: 5f2798c

== ssh service browse, 5 seconds ==
Browsing for _ssh._tcp.local
DATE: ---Sat 09 May 2026---
Timestamp     A/R    Flags  if Domain               Service Type         Instance Name
 5:58:03.806  Add        3  10 local.               _ssh._tcp.           aitopatom-9ab9 SSH

== mdns resolution, 3 seconds each ==
-- aitopatom-9ab9.local --
DATE: ---Sat 09 May 2026---
Timestamp     A/R  Flags         IF  Hostname                               Address                                      TTL
 5:58:08.812  Add  40000003      10  aitopatom-9ab9.local.                  <redacted-ipv4>                                     120
-- spark1.local --

== known target checks ==
aitopatom-9ab9.local: ssh reachable
spark1.local: not reachable
```

```text
== meta ==
Sat May  9 00:33:47 UTC 2026

== interfaces ==
-- en0 --
	inet6 <redacted-ipv6>%en0 prefixlen 64 secured scopeid 0xa 
	inet <redacted-ipv4> netmask 0xffff0000 broadcast <redacted-ipv4>
	status: active
-- en1 --
	inet6 <redacted-ipv6>%en1 prefixlen 64 secured scopeid 0x1a 
	inet <redacted-ipv4> netmask 0xffffff00 broadcast <redacted-ipv4>
	status: active

== routes (redacted) ==
Routing tables

Internet:
Destination        Gateway            Flags               Netif Expire
default            <redacted-ipv4>      UGScg                 en1       
127                <redacted-ipv4>          UCS                   lo0       
<redacted-ipv4>          <redacted-ipv4>          UH                    lo0       
<redacted-ipv4>     <redacted-ipv4>     UH                    lo0       
169.254            link#26            UCS                   en1      !
169.254            link#10            UCSI                  en0      !
172.16.11/24       link#26            UCS                   en1      !
<redacted-ipv4>      <redacted-mac>  UHLWIi                en1   1170
<redacted-ipv4>      <redacted-mac>  UHLWI                 en1      !
<redacted-ipv4>      <redacted-ipv6>   UHLWI                 en1    940
<redacted-ipv4>/32   link#26            UCS                   en1      !
<redacted-ipv4>/32   link#26            UCS                   en1      !
<redacted-ipv4>      <redacted-mac>  UHLWIir               en1   1199
<redacted-ipv4>      <redacted-mac>  UHLWbI                en1      !
192.168.0/16       link#10            UCS                   en0      !
<redacted-ipv4>/32   link#10            UCS                   en0      !
224.0.0/4          link#26            UmCS                  en1      !
224.0.0/4          link#10            UmCSI                 en0      !
<redacted-ipv4>        <redacted-ipv6>      UHmLWI                en0       
<redacted-ipv4>        <redacted-ipv6>      UHmLWI                en1       
<redacted-ipv4>/32 link#26            UCS                   en1      !
<redacted-ipv4>/32 link#10            UCSI                  en0      !
Routing tables

Internet6:
Destination                             Gateway                                 Flags               Netif Expire
default                                 fe80::%utun0                            UGcIg               utun0       
default                                 fe80::%utun1                            UGcIg               utun1       
default                                 fe80::%utun2                            UGcIg               utun2       
default                                 fe80::%utun3                            UGcIg               utun3       
::1                                     ::1                                     UHL                   lo0       
fe80::%lo0/64                           fe80::1%lo0                             UcI                   lo0       
fe80::1%lo0                             link#1                                  UHLI                  lo0       
fe80::%en0/64                           link#10                                 UCI                   en0       
<redacted-ipv6>%en0           <redacted-mac>                       UHLI                  lo0       
<redacted-ipv6>%en0           <redacted-ipv6>                        UHLWIi                en0       
fe80::%en1/64                           link#26                                 UCI                   en1       
<redacted-ipv6>%en1             <redacted-mac>                       UHLWI                 en1       
<redacted-ipv6>%en1             <redacted-mac>                       UHLI                  lo0       
<redacted-ipv6>%en1           <redacted-mac>                       UHLWI                 en1       
fe80::%awdl0/64                         link#27                                 UCI                 awdl0       
<redacted-ipv6>%awdl0         <redacted-mac>                       UHLI                  lo0       
fe80::%llw0/64                          link#28                                 UCI                  llw0       
<redacted-ipv6>%llw0          <redacted-mac>                       UHLI                  lo0       
fe80::%utun0/64                         <redacted-ipv6>%utun0         UcI                 utun0       
<redacted-ipv6>%utun0         link#29                                 UHLI                  lo0       
fe80::%utun1/64                         <redacted-ipv6>%utun1          UcI                 utun1       
<redacted-ipv6>%utun1          link#30                                 UHLI                  lo0       
fe80::%utun2/64                         <redacted-ipv6>%utun2         UcI                 utun2       
<redacted-ipv6>%utun2         link#31                                 UHLI                  lo0       
fe80::%utun3/64                         <redacted-ipv6>%utun3           UcI                 utun3       
<redacted-ipv6>%utun3           link#32                                 UHLI                  lo0       
ff00::/8                                ::1                                     UmCI                  lo0       
ff00::/8                                link#10                                 UmCI                  en0       
ff00::/8                                link#26                                 UmCI                  en1       
ff00::/8                                link#27                                 UmCI                awdl0       
ff00::/8                                link#28                                 UmCI                 llw0       
ff00::/8                                <redacted-ipv6>%utun0         UmCI                utun0       
ff00::/8                                <redacted-ipv6>%utun1          UmCI                utun1       
ff00::/8                                <redacted-ipv6>%utun2         UmCI                utun2       
ff00::/8                                <redacted-ipv6>%utun3           UmCI                utun3       
ff01::%lo0/32                           ::1                                     UmCI                  lo0       

== arp ==
? (<redacted-ipv4>) on en1 ifscope [ethernet]
? (<redacted-ipv4>) on en1 ifscope [ethernet]
? (<redacted-ipv4>) on en1 ifscope [ethernet]
? (<redacted-ipv4>) on en1 ifscope [ethernet]
? (<redacted-ipv4>) on en1 ifscope [ethernet]
? (<redacted-ipv4>) on en0 ifscope permanent [ethernet]
? (<redacted-ipv4>) on en1 ifscope permanent [ethernet]

== ssh service browse, 5 seconds ==
Browsing for _ssh._tcp.local
DATE: ---Sat 09 May 2026---
 0:33:47.224  ...STARTING...
Timestamp     A/R    Flags  if Domain               Service Type         Instance Name
 0:33:47.224  Add        3   1 local.               _ssh._tcp.           Mac Studio
 0:33:47.224  Add        3  10 local.               _ssh._tcp.           Mac Studio
 0:33:47.224  Add        3  10 local.               _ssh._tcp.           aitopatom-9ab9 SSH
 0:33:47.225  Add        3  26 local.               _ssh._tcp.           Mac Studio
 0:33:47.225  Add        2  26 local.               _ssh._tcp.           aitopatom-9ab9 SSH

== mdns resolution, 3 seconds each ==
-- aitopatom-9ab9.local --
DATE: ---Sat 09 May 2026---
 0:33:52.227  ...STARTING...
Timestamp     A/R  Flags         IF  Hostname                               Address                                      TTL
 0:33:52.333  Add  3             10  aitopatom-9ab9.local.                  <redacted-ipv4>                                     120
 0:33:52.333  Add  3             10  aitopatom-9ab9.local.                  <redacted-ipv6>%en0  120
 0:33:52.334  Add  3             26  aitopatom-9ab9.local.                  <redacted-ipv4>                                120
 0:33:52.334  Add  2             26  aitopatom-9ab9.local.                  <redacted-ipv6>%en1  120
-- spark1.local --

== known target checks ==
aitopatom-9ab9.local: ssh reachable
spark1.local: not reachable
```
