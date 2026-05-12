== meta ==
Tue May 12 10:26:30 UTC 2026
git: 6b1cd1a
targets: spark0@aitopatom-9ab9.local spark1@spark1.local spark2@spark2.local

== interfaces ==
-- en0 --
	inet6 <redacted-ipv6>%en0 prefixlen 64 secured scopeid 0xa 
	inet <redacted-ipv4> netmask 0xffff0000 broadcast <redacted-ipv4>
	status: active
-- en1 --
	inet6 <redacted-ipv6>%en1 prefixlen 64 secured scopeid 0x1a 
	inet <redacted-ipv4> netmask 0xffffff00 broadcast <redacted-ipv4>
	status: active

== routes ==
Routing tables

Internet:
Destination        Gateway            Flags               Netif Expire
default            <redacted-ipv4>      UGScg                 en1       
127                <redacted-ipv4>          UCS                   lo0       
<redacted-ipv4>          <redacted-ipv4>          UH                    lo0       
<redacted-ipv4>     <redacted-ipv4>     UH                    lo0       
169.254            link#26            UCS                   en1      !
169.254            link#10            UCSI                  en0      !
<redacted-ipv4cidr>       link#26            UCS                   en1      !
<redacted-ipv4>      <redacted-mac>  UHLWIi                en1   1040
<redacted-ipv4>      <redacted-mac>  UHLWI                 en1      !
<redacted-ipv4>      <redacted-mac>   UHLWI                 en1      !
<redacted-ipv4cidr>   link#26            UCS                   en1      !
<redacted-ipv4>      <redacted-mac>  UHLWI                 lo0       
<redacted-ipv4cidr>   link#26            UCS                   en1      !
<redacted-ipv4>      <redacted-mac>  UHLWIir               en1   1200
<redacted-ipv4>      <redacted-mac>  UHLWbI                en1      !
<redacted-ipv4cidr>       link#10            UCS                   en0      !
<redacted-ipv4cidr>   link#10            UCS                   en0      !
<redacted-ipv4>      <redacted-mac>  UHLWIi                lo0       
<redacted-ipv4>    <redacted-mac>  UHLWbI                en0      !
<redacted-ipv4cidr>          link#26            UmCS                  en1      !
<redacted-ipv4cidr>          link#10            UmCSI                 en0      !
<redacted-ipv4>        <redacted-mac>      UHmLWI                en0       
<redacted-ipv4>        <redacted-mac>      UHmLWI                en1       
<redacted-ipv4cidr> link#26            UCS                   en1      !
<redacted-ipv4cidr> link#10            UCSI                  en0      !
Routing tables

Internet6:
Destination                             Gateway                                 Flags               Netif Expire
default                                 <redacted-ipv6>%utun0                            UGcIg               utun0       
default                                 <redacted-ipv6>%utun1                            UGcIg               utun1       
default                                 <redacted-ipv6>%utun2                            UGcIg               utun2       
default                                 <redacted-ipv6>%utun3                            UGcIg               utun3       
<redacted-ipv6>                                     <redacted-ipv6>                                     UHL                   lo0       
<redacted-ipv6>%lo0/64                           <redacted-ipv6>%lo0                             UcI                   lo0       
<redacted-ipv6>%lo0                             link#1                                  UHLI                  lo0       
<redacted-ipv6>%en0/64                           link#10                                 UCI                   en0       
<redacted-ipv6>%en0           <redacted-mac>                       UHLI                  lo0       
<redacted-ipv6>%en0           <redacted-mac>                        UHLWIi                en0       
<redacted-ipv6>%en1/64                           link#26                                 UCI                   en1       
<redacted-ipv6>%en1             <redacted-mac>                       UHLWI                 en1       
<redacted-ipv6>%en1             <redacted-mac>                       UHLI                  lo0       
<redacted-ipv6>%en1           <redacted-mac>                       UHLWI                 en1       
<redacted-ipv6>%awdl0         <redacted-mac>                       UHLI                  lo0       
<redacted-ipv6>%llw0          <redacted-mac>                       UHLI                  lo0       
<redacted-ipv6>%utun0/64                         <redacted-ipv6>%utun0         UcI                 utun0       
<redacted-ipv6>%utun0         link#29                                 UHLI                  lo0       
<redacted-ipv6>%utun1/64                         <redacted-ipv6>%utun1          UcI                 utun1       
<redacted-ipv6>%utun1          link#30                                 UHLI                  lo0       
<redacted-ipv6>%utun2/64                         <redacted-ipv6>%utun2         UcI                 utun2       
<redacted-ipv6>%utun2         link#31                                 UHLI                  lo0       
<redacted-ipv6>%utun3/64                         <redacted-ipv6>%utun3           UcI                 utun3       
<redacted-ipv6>%utun3           link#32                                 UHLI                  lo0       
<redacted-ipv6>/8                                <redacted-ipv6>                                     UmCI                  lo0       
<redacted-ipv6>/8                                link#10                                 UmCI                  en0       
<redacted-ipv6>/8                                link#26                                 UmCI                  en1       
<redacted-ipv6>/8                                link#27                                 UmCI                awdl0       
<redacted-ipv6>/8                                link#28                                 UmCI                 llw0       
<redacted-ipv6>/8                                <redacted-ipv6>%utun0         UmCI                utun0       
<redacted-ipv6>/8                                <redacted-ipv6>%utun1          UmCI                utun1       
<redacted-ipv6>/8                                <redacted-ipv6>%utun2         UmCI                utun2       
<redacted-ipv6>/8                                <redacted-ipv6>%utun3           UmCI                utun3       
<redacted-ipv6>%lo0/32                           <redacted-ipv6>                                     UmCI                  lo0       
<redacted-ipv6>%en0/32                           link#10                                 UmCI                  en0       
<redacted-ipv6>%en1/32                           link#26                                 UmCI                  en1       

== arp ==
? (<redacted-ipv4>) on en1 ifscope [ethernet]
? (<redacted-ipv4>) on en1 ifscope [ethernet]
? (<redacted-ipv4>) on en1 ifscope [ethernet]
? (<redacted-ipv4>) on en1 ifscope permanent [ethernet]
? (<redacted-ipv4>) on en1 ifscope [ethernet]
? (<redacted-ipv4>) on en1 ifscope [ethernet]
? (<redacted-ipv4>) on en0 ifscope permanent [ethernet]
? (<redacted-ipv4>) on en0 ifscope [ethernet]
? (<redacted-ipv4>) on en0 ifscope permanent [ethernet]
? (<redacted-ipv4>) on en1 ifscope permanent [ethernet]

== ssh service browse, 5 seconds ==
Browsing for _ssh._tcp.local
DATE: ---Tue 12 May 2026---
10:26:30.817  ...STARTING...
Timestamp     A/R    Flags  if Domain               Service Type         Instance Name
10:26:30.817  Add        3  10 local.               _ssh._tcp.           Mac Studio
10:26:30.817  Add        3   1 local.               _ssh._tcp.           Mac Studio
10:26:30.817  Add        3  10 local.               _ssh._tcp.           aitopatom-9ab9 SSH
10:26:30.817  Add        3  26 local.               _ssh._tcp.           Mac Studio
10:26:30.817  Add        2  26 local.               _ssh._tcp.           aitopatom-9ab9 SSH

== mdns resolution, 3 seconds each ==
-- aitopatom-9ab9.local --
DATE: ---Tue 12 May 2026---
10:26:35.825  ...STARTING...
Timestamp     A/R  Flags         IF  Hostname                               Address                                      TTL
10:26:35.826  Add  40000003      26  aitopatom-9ab9.local.                  <redacted-ipv6>%en1  120
10:26:35.826  Add  40000002      26  aitopatom-9ab9.local.                  <redacted-ipv4>                                120
-- spark1.local --
-- spark2.local --

== route selection (macOS) ==
-- aitopatom-9ab9.local --
route: socket: Operation not permitted
-- spark1.local --
route: socket: Operation not permitted
-- spark2.local --
route: socket: Operation not permitted

== known target checks ==
spark0@aitopatom-9ab9.local: ssh reachable
spark1@spark1.local: not reachable
spark2@spark2.local: not reachable

== ping (mac->targets, compact) ==
aitopatom-9ab9.local: tx=3 rx=3 loss=0.0% rtt_avg_ms=277.842
spark1.local: resolve_failed
spark2.local: resolve_failed
