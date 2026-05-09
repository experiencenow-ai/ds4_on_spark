# Spark0 Mac Discovery Snapshot

Date: 2026-05-09 (UTC) from the Mac workspace.

Commands run:

```bash
REDACT=1 ./scripts/mac_spark_discovery.sh > /private/tmp/ds4_mac_spark_discovery_redacted_2026-05-09.txt
```

Notes:

- This output is redacted (`REDACT=1`) to remove IPv4/IPv6/MAC addresses.
- Default targets include `aitopatom-9ab9.local` and `spark1.local`.

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
