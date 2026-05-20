# SPARKNETWORK

Load this file first for any Centaur/Spark networking work. The machine-readable
source of truth is [`sparknetwork.json`](sparknetwork.json); this document is the
human runbook derived from it.

Last verified: `2026-05-20T0752Z` UTC.

## Rule Zero

Do not confuse SSH login names with network hostnames.

- SSH users: `spark0`, `spark1`, `spark2`, `spark3`, `spark4`, `spark5`,
  `spark6`.
- Network hostnames are Bonjour/device names: `aitopatom-9ab9.local`,
  `edgexpert-d623.local`, `aitopatom-931a.local`, `aitopatom-a18f.local`,
  `aitopatom-c342.local`, `aitopatom-a36d.local`, `aitopatom-c637.local`.
- Do not use `sparkN.local` unless that alias is deliberately pinned in DNS or
  `/etc/hosts`.

## Current Physical Topology

The 200G fabric is currently an open line, not a closed ring:

```text
spark0 -> spark1 -> spark2 -> spark3 -> spark4 -> spark5 -> spark6
```

The intended `spark6 -> spark0` 200G return edge is missing because the cable is
too short. Spark6 has a temporary 10G copper direct link to Spark0 instead.

## Canonical Inventory

| Node | SSH alias | Network hostname | Current primary path from Mac |
|------|-----------|------------------|-------------------------------|
| Spark0 | `ssh spark0` | `aitopatom-9ab9.local` | Mac -> Spark3 -> Spark2 -> Spark1 -> Spark0 over 200G |
| Spark1 | `ssh spark1` | `edgexpert-d623.local` | Mac -> Spark3 -> Spark2 -> Spark1 over 200G |
| Spark2 | `ssh spark2` | `aitopatom-931a.local` | Mac -> Spark3 -> Spark2 over 200G |
| Spark3 | `ssh spark3` | `aitopatom-a18f.local` | Direct private 10G, `10.20.0.13` |
| Spark4 | `ssh spark4` | `aitopatom-c342.local` | Direct private 10G, `10.20.0.14` |
| Spark5 | `ssh spark5` | `aitopatom-a36d.local` | Direct private 10G, `10.20.0.15` |
| Spark6 | `ssh spark6` | `aitopatom-c637.local` | Mac -> Spark5 -> Spark6 over 200G |

The Mac Studio `~/.ssh/config` has a `DS4 SPARKNETWORK` block matching this
table. Verified commands:

```bash
ssh spark0 hostname
ssh spark1 hostname
ssh spark2 hostname
ssh spark3 hostname
ssh spark4 hostname
ssh spark5 hostname
ssh spark6 hostname
ssh spark0-10g hostname
ssh spark6-10g hostname
```

## 10G Control Plane

Mac Studio:

- `en0`: office/fiber path, `175.193.138.31/24`.
- `en0`: private Spark alias, `10.20.0.1/24`.

Private 10G assignments:

| Node | Interface | Address | State |
|------|-----------|---------|-------|
| Mac Studio | `en0` | `10.20.0.1/24` | switch/control alias |
| Spark0 | `enP7s7` | `10.20.0.10/24` | temporary direct link to Spark6 |
| Spark3 | `enP7s7` | `10.20.0.13/24` | switch control, plus DHCP `125.129.239.57/24` |
| Spark4 | `enP7s7` | `10.20.0.14/24` | switch control, plus DHCP `175.193.138.138/24` |
| Spark5 | `enP7s7` | `10.20.0.15/24` | switch control, plus DHCP `175.193.138.193/24` |
| Spark6 | `enP7s7` | `10.20.0.16/24` | temporary direct link to Spark0 |

Spark1 and Spark2 currently have `enP7s7` down; reach them through the 200G
line via `ssh spark1` and `ssh spark2`.

If Mac Studio ever loses the private alias, reinstall it as a `/24`:

```bash
sudo ifconfig en0 -alias 10.20.0.1
sudo ifconfig en0 inet 10.20.0.1 netmask 255.255.255.0 alias
```

## 200G Fabric

All live 200G links below report `200000Mb/s`. Normal ping, `8972` byte jumbo
ping, and TCP/22 succeeded on every live link.

| Edge | Link A | Link B |
|------|--------|--------|
| Spark0-Spark1 | Spark0 `enp1s0f1np1` `10.10.1.1/30` <-> Spark1 `enp1s0f1np1` `10.10.1.2/30` | Spark0 `enP2p1s0f1np1` `10.10.2.1/30` <-> Spark1 `enP2p1s0f1np1` `10.10.2.2/30` |
| Spark1-Spark2 | Spark1 `enp1s0f0np0` `10.10.3.1/30` <-> Spark2 `enp1s0f0np0` `10.10.3.2/30` | Spark1 `enP2p1s0f0np0` `10.10.4.1/30` <-> Spark2 `enP2p1s0f0np0` `10.10.4.2/30` |
| Spark2-Spark3 | Spark2 `enp1s0f1np1` `10.10.5.2/30` <-> Spark3 `enp1s0f1np1` `10.10.5.1/30` | Spark2 `enP2p1s0f1np1` `10.10.6.2/30` <-> Spark3 `enP2p1s0f1np1` `10.10.6.1/30` |
| Spark3-Spark4 | Spark3 `enp1s0f0np0` `10.10.7.1/30` <-> Spark4 `enp1s0f1np1` `10.10.7.2/30` | Spark3 `enP2p1s0f0np0` `10.10.8.1/30` <-> Spark4 `enP2p1s0f1np1` `10.10.8.2/30` |
| Spark4-Spark5 | Spark4 `enp1s0f0np0` `10.10.9.1/30` <-> Spark5 `enp1s0f1np1` `10.10.9.2/30` | Spark4 `enP2p1s0f0np0` `10.10.10.1/30` <-> Spark5 `enP2p1s0f1np1` `10.10.10.2/30` |
| Spark5-Spark6 | Spark5 `enp1s0f0np0` `10.10.11.1/30` <-> Spark6 `enp1s0f1np1` `10.10.11.2/30` | Spark5 `enP2p1s0f0np0` `10.10.12.1/30` <-> Spark6 `enP2p1s0f1np1` `10.10.12.2/30` |

Reserve `10.10.13.0/30` and `10.10.14.0/30` for the future Spark6-Spark0 200G
return edge when the longer cable or new switch is installed.

## Wi-Fi Fallbacks

Wi-Fi is not the primary operator plane.

| Node | Wi-Fi address | SSID/role |
|------|---------------|-----------|
| Spark0 | `192.168.0.155/24` | fallback on older TP-Link LAN |
| Spark1 | `192.168.0.146/24` | fallback on older TP-Link LAN |
| Spark2 | `192.168.0.116/24` | fallback on older TP-Link LAN |
| Spark3 | `192.168.1.110/24` | fallback on `TP-Link_D660_5G` |
| Spark4 | `192.168.1.137/24` | fallback on `TP-Link_D660_5G` |
| Spark5 | down | fallback only |
| Spark6 | `192.168.1.185/24` | fallback on `TP-Link_D660_5G`; also `ssh spark6-wifi` |

## Internet Status

Spark3, Spark4, and Spark5 have working wired internet through `enP7s7`; a
Cloudflare trace returned ICN for all three. Spark0, Spark1, Spark2, and Spark6
are reachable for control and ring traffic, but do not currently have a working
internet route. Spark0-Spark2 default to the older `192.168.0.0/24` Wi-Fi LAN,
and Spark6 defaults to `192.168.1.0/24`; those paths failed the trace check.

Do not use internet availability as a Spark health signal until every node is on
the new switch or a deliberate routed/NAT path is installed.

## Communication Contract

Use separate planes for separate jobs:

| Plane | Path | Purpose |
|-------|------|---------|
| Operator SSH | Mac SSH aliases above | Debug, config, service start/stop, emergency access |
| Centaur control | Spark0 controller on `8765`, agent on each Spark at `8766` | Health, low-bandwidth commands, node registration |
| Ring sync | Previous/next 200G neighbors only | Manifests, object sync, shard movement, high-volume transfers |
| Data plane | 200G fabric | Runtime/model traffic |

For bulk data, prefer [`docs/spark-ring-fast-transfer.md`](docs/spark-ring-fast-transfer.md)
and `scripts/spark_ring_fast_copy.py --engine native` for regular files. Use
the Python engine for directory trees. SSH-based rsync/scp is a control-plane
fallback, not the default for initial model/runtime payload movement.

The low-bandwidth control service should expose only allowlisted operations:

- `health`: hostname, user, uptime, interfaces, disk, service versions.
- `probe_links`: ping, jumbo ping, TCP/port checks for declared neighbors.
- `stage_manifest`: receive a manifest/checksum list, not bulk model payloads.
- `sync_pull` / `sync_push`: trigger bounded neighbor transfers over the 200G
  ring using the fast-transfer path, with rsync reserved for final metadata or
  delta validation.
- `service`: start/stop/status allowlisted Centaur services.

Do not send model payloads through the controller API. Use the ring sync plane.

## Writable Roots

Every Spark should have the same user-writable layout under the Spark login
user:

```text
~/centaur-smoke/v73/centaur_spec_impl_v73.zip
~/centaur-smoke/v73/run/centaur_spec_impl_v73/
~/centaur-smoke/v73/run/venv/
~/centaur-smoke/v73/run/hyor/controller/          # Spark0 controller
~/centaur-smoke/v73/ring_node/hyor/node_spark0/
~/centaur-smoke/v73/ring_node/hyor/node_spark1/
~/centaur-smoke/v73/ring_node/hyor/node_spark2/
~/centaur-smoke/v73/ring_node/hyor/node_spark3/
~/centaur-smoke/v73/ring_node/hyor/node_spark4/
~/centaur-smoke/v73/ring_node/hyor/node_spark5/
~/centaur-smoke/v73/ring_node/hyor/node_spark6/
~/centaur-smoke/v73/ring_node/effective_spark0/
~/centaur-smoke/v73/ring_node/effective_spark1/
~/centaur-smoke/v73/ring_node/effective_spark2/
~/centaur-smoke/v73/ring_node/effective_spark3/
~/centaur-smoke/v73/ring_node/effective_spark4/
~/centaur-smoke/v73/ring_node/effective_spark5/
~/centaur-smoke/v73/ring_node/effective_spark6/
/tmp/sparknetwork/                                # volatile probes/staging
```

Do not require root for Centaur staging. Use `/tmp` for transient probes and the
home-directory roots above for durable user-writable state.

## Existing Centaur HTTP Pieces

The repo already has smoke-grade wrappers:

- Controller HTTP on Spark0: `scripts/centaur_spark_hyor_controller_http_v73.sh`
- Node agent HTTP on each Spark: `scripts/centaur_spark_hyor_agent_http_v73.sh`
- Controller-side node discovery: `scripts/centaur_spark_hyor_node_discover_v73.sh`

Default ports:

| Service | Host | Port |
|---------|------|------|
| HyoR controller HTTP | Spark0 | `8765` |
| HyoR agent HTTP | Spark0-Spark6 | `8766` |

## Quick Verification

From Mac Studio:

```bash
for h in spark0 spark1 spark2 spark3 spark4 spark5 spark6; do ssh "$h" hostname; done
ssh spark3 'for ip in 10.10.5.2 10.10.6.2 10.10.7.2 10.10.8.2; do ping -c 1 "$ip"; done'
ssh spark5 'for ip in 10.10.9.1 10.10.10.1 10.10.11.2 10.10.12.2; do ping -c 1 "$ip"; done'
ssh spark0-10g hostname
ssh spark6-10g hostname
```
