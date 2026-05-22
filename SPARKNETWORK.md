# SPARKNETWORK

Load this file first for any Centaur/Spark networking work. The machine-readable
source of truth is [`sparknetwork.json`](sparknetwork.json); this document is the
human runbook derived from it.

Last verified: `2026-05-22T08:43Z` UTC.

## Rule Zero

Do not confuse SSH login names with network hostnames.

- SSH users: `spark0`, `spark1`, `spark2`, `spark3`, `spark4`, `spark5`,
  `spark6`, and `spark7`.
- Network hostnames are Bonjour/device names: `aitopatom-9ab9.local`,
  `edgexpert-d623.local`, `aitopatom-931a.local`, `aitopatom-a18f.local`,
  `aitopatom-c342.local`, `aitopatom-a36d.local`, `aitopatom-c637.local`, and
  `thinkstation-pgx.local` for Spark7. The Mac `ssh spark7` alias is pinned to
  `192.168.1.236` so access does not depend on mDNS settling.
- Do not use `sparkN.local` unless that alias is deliberately pinned in DNS or
  `/etc/hosts`.

## Current Physical Topology

The 10G control plane is being reworked. Operator report: the network now has
eight Spark nodes and all nodes should be reachable. Spark7 is reachable via
Wi-Fi from the Mac and now closes the 200G return edge into Spark0.
Fiber/wired internet is still not a 200G health signal.

```text
Mac Studio en0 -> TP-Link 5-port -> 8-port Spark switch -> spark0-spark7 10G
Mac Studio en1 Wi-Fi -> TP-Link_D660(_5G) -> spark0-spark7 Wi-Fi
```

Mac Studio `en1` is `192.168.1.128/24`. Mac Studio `en0` currently has no IPv4
address and no active `10.20.0.1/24` alias, so direct Mac-to-Spark TCP/22 on
`10.20.0.10-10.20.0.17` is not an operator path. Use direct Wi-Fi aliases for
break-glass access and Wi-Fi plus 200G proxy hops for canonical `ssh sparkN`
paths.

Mac Studio `ssh spark0` through `ssh spark7` were repaired and verified at
`2026-05-22T08:43Z`. The current exception is Spark0's direct Wi-Fi alias:
`ssh spark0-wifi` to `192.168.1.127` timed out during the same check, so the
canonical `ssh spark0` path enters through `spark1-wifi` and then the
Spark1-Spark0 200G rail at `10.10.1.1`.

The 200G fabric is now a closed routed ring:

```text
spark0 -> spark1 -> spark2 -> spark3 -> spark4 -> spark5 -> spark6 -> spark7 -> spark0
```

Spark7 now closes the return edge into Spark0. The 10G switch plane is not a
substitute for the 200G fabric; it remains the operator/control plane.

## Canonical Inventory

| Node | SSH alias | Network hostname | Current primary path from Mac | Direct Wi-Fi backup |
|------|-----------|------------------|-------------------------------|--------------------|
| Spark0 | `ssh spark0` | `aitopatom-9ab9.local` | Mac -> Spark1 Wi-Fi -> Spark0 200G `10.10.1.1` | `ssh spark0-wifi`, `192.168.1.127` currently times out |
| Spark1 | `ssh spark1` | `edgexpert-d623.local` | Direct Wi-Fi, `192.168.1.226` | `ssh spark1-wifi`, `192.168.1.226` |
| Spark2 | `ssh spark2` | `aitopatom-931a.local` | Direct Wi-Fi, `192.168.1.166` | `ssh spark2-wifi`, `192.168.1.166` |
| Spark3 | `ssh spark3` | `aitopatom-a18f.local` | Direct Wi-Fi, `192.168.1.110` | `ssh spark3-wifi`, `192.168.1.110` |
| Spark4 | `ssh spark4` | `aitopatom-c342.local` | Direct Wi-Fi, `192.168.1.137` | `ssh spark4-wifi`, `192.168.1.137` |
| Spark5 | `ssh spark5` | `aitopatom-a36d.local` | Direct Wi-Fi, `192.168.1.245` | `ssh spark5-wifi`, `192.168.1.245` |
| Spark6 | `ssh spark6` | `aitopatom-c637.local` | Direct Wi-Fi, `192.168.1.185` | `ssh spark6-wifi`, `192.168.1.185` |
| Spark7 | `ssh spark7` | `thinkstation-pgx.local` | Direct Wi-Fi, `192.168.1.236` | `ssh spark7`, `192.168.1.236` |

Current verified manual access paths (`2026-05-22T08:43Z`):

```bash
ssh spark0 hostname
ssh spark1 hostname
ssh spark2 hostname
ssh spark3 hostname
ssh spark4 hostname
ssh spark5 hostname
ssh spark6 hostname
ssh spark7 hostname
```

Spark0 and Spark1 are alive after reboot, and every node from Spark0 through
Spark7 is reachable from Mac Studio. The Mac Studio `DS4 SPARKNETWORK` SSH
block was updated at `2026-05-22T08:43Z`; bare `ssh spark0` through
`ssh spark7` were verified after the update. Direct Wi-Fi aliases
`spark1-wifi` through `spark6-wifi`, plus `spark7`, were also verified;
`spark0-wifi` timed out, so use bare `spark0` for Spark0 until its Wi-Fi SSH
path is repaired.

## 10G Control Plane

Mac Studio:

- `en1`: Wi-Fi path, `192.168.1.128/24`.
- `en0`: no active IPv4 address during the `2026-05-21T23:34Z` probe.

Private 10G assignments:

| Node | Interface | Address | State |
|------|-----------|---------|-------|
| Mac Studio | `en0` | no IPv4 | switch/control alias missing |
| Spark0 | `enP7s7` | `10.20.0.10/24` | 8-port switch control, private-only |
| Spark1 | `enP7s7` | no IPv4 during latest probe | interface up, 10G switch address missing |
| Spark2 | `enP7s7` | `10.20.0.12/24` | switch control address present, not reachable from Mac or Spark3 |
| Spark3 | `enP7s7` | `10.20.0.13/24` | switch control, plus DHCP `125.129.239.57/24` |
| Spark4 | `enP7s7` | `10.20.0.14/24` | switch control, plus DHCP `175.193.138.138/24` |
| Spark5 | `enP7s7` | `10.20.0.15/24` | switch control, plus DHCP `175.193.138.193/24` |
| Spark6 | `enP7s7` | `10.20.0.16/24` | 8-port switch control, private-only |
| Spark7 | `enP7s7` | `10.20.0.17/24` | static profile installed; physical link has no carrier |

The latest probe did **not** see a flat private `10.20.0.0/24` control plane.
From inside the cluster, Spark3 could reach only `10.20.0.13` and
`10.20.0.14`; Spark4 could reach `10.20.0.10` and itself; Spark5 and Spark6
could reach only their own `10.20.0.x` addresses. Treat the 10G plane as
fragmented until repaired.

If Mac Studio ever loses the private alias, reinstall it as a `/24`:

```bash
sudo ifconfig en0 -alias 10.20.0.1
sudo ifconfig en0 inet 10.20.0.1 netmask 255.255.255.0 alias
```

## 200G Fabric

Spark0 through Spark7 are reachable over the closed 200G fabric. The current
deployment uses point-to-point `/30` addresses on the physical links, plus one
per-node loopback for services that need stable all-to-all 200G addressing.

Persistent repair is installed on every Spark:

- Unit: `ds4-ring-200g.service`
- Script: `/usr/local/sbin/ds4-ring-200g-apply`
- Boot behavior: reapplies MTU `9000`, `/30` link addresses, `sparkN-ring`
  loopbacks, shortest-path static routes, IPv4 forwarding, rp-filter disable,
  and a narrow Docker/FORWARD allow rule for `10.10.0.0/16`.
- Hostnames on every Spark: `spark0-ring` through `spark7-ring`.

| Edge | Link A | Link B |
|------|--------|--------|
| Spark0-Spark1 | Spark0 `enp1s0f1np1` `10.10.1.1/30` <-> Spark1 `enp1s0f0np0` `10.10.1.2/30` | Spark0 `enP2p1s0f1np1` `10.10.2.1/30` <-> Spark1 `enP2p1s0f0np0` `10.10.2.2/30` |
| Spark1-Spark2 | Spark1 `enp1s0f1np1` `10.10.3.1/30` <-> Spark2 `enp1s0f0np0` `10.10.3.2/30` | Spark1 `enP2p1s0f1np1` `10.10.4.1/30` <-> Spark2 `enP2p1s0f0np0` `10.10.4.2/30` |
| Spark2-Spark3 | Spark2 `enp1s0f1np1` `10.10.5.1/30` <-> Spark3 `enp1s0f0np0` `10.10.5.2/30` | Spark2 `enP2p1s0f1np1` `10.10.6.1/30` <-> Spark3 `enP2p1s0f0np0` `10.10.6.2/30` |
| Spark3-Spark4 | Spark3 `enp1s0f1np1` `10.10.7.1/30` <-> Spark4 `enp1s0f0np0` `10.10.7.2/30` | Spark3 `enP2p1s0f1np1` `10.10.8.1/30` <-> Spark4 `enP2p1s0f0np0` `10.10.8.2/30` |
| Spark4-Spark5 | Spark4 `enp1s0f1np1` `10.10.9.1/30` <-> Spark5 `enp1s0f0np0` `10.10.9.2/30` | Spark4 `enP2p1s0f1np1` `10.10.10.1/30` <-> Spark5 `enP2p1s0f0np0` `10.10.10.2/30` |
| Spark5-Spark6 | Spark5 `enp1s0f1np1` `10.10.11.1/30` <-> Spark6 `enp1s0f0np0` `10.10.11.2/30` | Spark5 `enP2p1s0f1np1` `10.10.12.1/30` <-> Spark6 `enP2p1s0f0np0` `10.10.12.2/30` |
| Spark6-Spark7 | Spark6 `enp1s0f1np1` `10.10.13.1/30` <-> Spark7 `enp1s0f0np0` `10.10.13.2/30` | Spark6 `enP2p1s0f1np1` `10.10.14.1/30` <-> Spark7 `enP2p1s0f0np0` `10.10.14.2/30` |
| Spark7-Spark0 | Spark7 `enp1s0f1np1` `10.10.15.1/30` <-> Spark0 `enp1s0f0np0` `10.10.15.2/30` | Spark7 `enP2p1s0f1np1` `10.10.16.1/30` <-> Spark0 `enP2p1s0f0np0` `10.10.16.2/30` |

Stable routed 200G service addresses:

| Node | 200G loopback | Local name |
|------|---------------|------------|
| Spark0 | `10.10.100.10/32` | `spark0-ring` |
| Spark1 | `10.10.100.11/32` | `spark1-ring` |
| Spark2 | `10.10.100.12/32` | `spark2-ring` |
| Spark3 | `10.10.100.13/32` | `spark3-ring` |
| Spark4 | `10.10.100.14/32` | `spark4-ring` |
| Spark5 | `10.10.100.15/32` | `spark5-ring` |
| Spark6 | `10.10.100.16/32` | `spark6-ring` |
| Spark7 | `10.10.100.17/32` | `spark7-ring` |

Use the loopback names for non-adjacent 200G traffic. Use the raw `/30`
addresses only when testing a specific physical edge/rail.

For bulk adjacent-node transfer at full aggregate speed, run one worker on each
rail of the edge. Example for Spark0 -> Spark1: send one stream to
`10.10.1.2` and one stream to `10.10.2.2`. The stable `sparkN-ring` loopbacks
are for routed all-to-all correctness; dual-rail bulk tools should pin workers
to the two raw rail addresses.

Verification at `2026-05-22T07:54Z`:

- All 16 adjacent `/30` links passed normal and 8972-byte DF jumbo ping.
- All 56 directed `sparkN-ring` all-to-all paths passed 8972-byte DF jumbo ping.
- Spark0 -> Spark2 routed loopback `iperf3 -P 8` measured about `100 Gbit/s`
  through a single server process.
- Spark0 -> Spark1 dual-rail direct `iperf3` measured `197.3 Gbit/s`
  aggregate: `98.1 Gbit/s` on `10.10.1.0/30` plus `99.2 Gbit/s` on
  `10.10.2.0/30`.
- Spark7 -> Spark0 and Spark0 -> Spark7 return-edge pings on `10.10.15.0/30`
  and `10.10.16.0/30` were rechecked at `2026-05-22T08:43Z`.

## Wi-Fi Fallbacks

Wi-Fi is not the primary operator plane.

| Node | Wi-Fi address | SSID/role |
|------|---------------|-----------|
| Spark0 | `192.168.1.127/24` | fallback on `TP-Link_D660_5G`; `ssh spark0-wifi` currently times out |
| Spark1 | `192.168.1.226/24` | fallback on `TP-Link_D660_5G`; `ssh spark1-wifi` |
| Spark2 | `192.168.1.166/24` | fallback on `TP-Link_D660_5G`; `ssh spark2-wifi` |
| Spark3 | `192.168.1.110/24` | fallback on `TP-Link_D660_5G`; `ssh spark3-wifi` |
| Spark4 | `192.168.1.137/24` | fallback on `TP-Link_D660_5G`; `ssh spark4-wifi` |
| Spark5 | `192.168.1.245/24` | fallback on `TP-Link_D660_5G`; `ssh spark5-wifi` |
| Spark6 | `192.168.1.185/24` | fallback on `TP-Link_D660_5G`; `ssh spark6-wifi` |
| Spark7 | `192.168.1.236/24` | fallback on `TP-Link_D660`; `ssh spark7` |

## Internet Status

Operator report for this rewire: wired/fiber internet is not connected and
current internet is offline. Mac Studio currently uses Wi-Fi
`192.168.1.128/24`. Spark0 through Spark7 all default to `192.168.1.1` via
`wlP9s9`, but internet reachability should not be assumed until reverified.

Do not use internet availability as a 200G or 10G health signal. Until the 10G
plane is flat again, use verified SSH reachability over the Wi-Fi/200G proxy
paths as the operator health signal.

## Communication Contract

Use separate planes for separate jobs:

| Plane | Path | Purpose |
|-------|------|---------|
| Operator SSH | Mac SSH aliases above | Debug, config, service start/stop, emergency access |
| Centaur control | Spark0 controller on `8765`, agent on each Spark at `8766` | Health, low-bandwidth commands, node registration |
| Ring sync | Previous/next 200G neighbors only | Manifests, object sync, shard movement, high-volume transfers |
| Data plane | 200G fabric | Runtime/model traffic |

## Rescue Control Plane

Spark0 through Spark7 now run a first-pass software rescue layer on the 10G
control plane:

- Service: `ds4-rescue-agent.service`, user systemd unit.
- Port: `25100/tcp` on each deployed node.
- Token: per-cluster secret file, installed on each node at
  `~/.ds4-rescue/token`; do not commit or print it.
- Persistence: `loginctl enable-linger` is enabled for `spark0` through
  `spark7`, so the user service can start at boot without an active SSH login.
- Local self-heal: `ds4-sshd-watchdog.timer` runs every minute as root. If the
  local SSH banner probe fails, it restarts SSH, then kills allowlisted heavy
  runtimes if SSH still does not recover.
- Allowlisted heavy-runtime kills: Docker containers named
  `vllm_deepseek_v4_flash`, `vllm_*`, `ds4_vllm_*`, or `centaur_vllm_*`, plus
  process command lines matching `vllm serve` / `VLLM::`. Ray kills are disabled
  unless `DS4_WATCHDOG_KILL_RAY=1` is set in the timer environment.
- Reboot escalation is available but disabled by default. Set
  `DS4_WATCHDOG_REBOOT_AFTER=N` to reboot after `N` consecutive failed rescue
  attempts.
- Narrow sudo: `/etc/sudoers.d/ds4-sshd-rescue` allows only `systemctl restart
  ssh`, `systemctl restart sshd`, and `/usr/local/sbin/ds4-sshd-watchdog`.

Use the checked-in client from Mac Studio:

```bash
python3 scripts/ds4_rescue_client.py 10.20.0.12 health
python3 scripts/ds4_rescue_client.py 10.20.0.12 ssh-probe
python3 scripts/ds4_rescue_client.py 10.20.0.12 restart-ssh
python3 scripts/ds4_rescue_client.py 10.20.0.12 self-rescue
```

Replace the last octet for the target node when the 10G plane is healthy.
`spark0` and `spark1` were upgraded at `2026-05-21T23:47Z`; `spark7` was
upgraded at `2026-05-21T23:56Z`. Forced watchdog self-rescue returned OK on
`spark0` through `spark7` after deployment.

For spark4-style wedges where TCP accepts but SSH and HTTP do not answer, the
remote client will not help because the agent cannot respond. The local root
timer is the intended recovery path: it must be deployed before the node wedges.
The 2026-05-21 heavy-runtime kill escalation is deployed live to `spark0`
through `spark7`.

Deploy or refresh it on reachable nodes with:

```bash
DS4_RESCUE_ROOT=1 scripts/ds4_deploy_rescue_agent.sh spark0 spark1 spark2 spark3 spark4 spark5 spark6 spark7
```

For bulk data, prefer [`docs/spark-ring-fast-transfer.md`](docs/spark-ring-fast-transfer.md)
and `scripts/spark_ring_fast_copy.py --engine native` for regular files. Use
the Python engine for directory trees. SSH-based rsync/scp is a control-plane
fallback, not the default for initial model/runtime payload movement.

For model placement, load [`sparkmodels.json`](sparkmodels.json) and
[`docs/spark-model-cache.md`](docs/spark-model-cache.md). The canonical cache is
`/home/sparkN/models` on every Spark, mirrored hop-by-hop over the 200G ring.

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
~/centaur-smoke/v73/ring_node/hyor/node_spark7/
~/centaur-smoke/v73/ring_node/effective_spark0/
~/centaur-smoke/v73/ring_node/effective_spark1/
~/centaur-smoke/v73/ring_node/effective_spark2/
~/centaur-smoke/v73/ring_node/effective_spark3/
~/centaur-smoke/v73/ring_node/effective_spark4/
~/centaur-smoke/v73/ring_node/effective_spark5/
~/centaur-smoke/v73/ring_node/effective_spark6/
~/centaur-smoke/v73/ring_node/effective_spark7/
~/models/
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
| HyoR agent HTTP | Spark0-Spark7 | `8766` |

## Quick Verification

From Mac Studio:

```bash
ssh spark3@192.168.1.110 hostname
ssh spark4@192.168.1.137 hostname
ssh spark6@192.168.1.185 hostname
for h in spark0-wifi spark1-wifi spark2-wifi spark3-wifi spark4-wifi spark5-wifi spark6-wifi; do ssh "$h" hostname; done
for h in spark0 spark1 spark2 spark3 spark4 spark5 spark6 spark7; do ssh "$h" hostname; done
ssh -o ProxyCommand='ssh spark3@192.168.1.110 nc 10.10.5.2 22' spark2@10.10.5.2 hostname
ssh -o ProxyCommand='ssh spark4@192.168.1.137 nc 10.10.9.2 22' spark5@10.10.9.2 hostname
ssh spark3@192.168.1.110 'for ip in 10.10.5.2 10.10.6.2 10.10.7.2 10.10.8.2; do ping -c 1 "$ip"; done'
ssh spark4@192.168.1.137 'for ip in 10.10.9.2 10.10.10.2; do ping -c 1 "$ip"; done'
ssh spark7 'for ip in 10.10.13.1 10.10.14.1; do ping -c 1 "$ip"; done'
for h in spark0-wifi spark1-wifi spark2-wifi spark3-wifi spark4-wifi spark5-wifi spark6-wifi spark7; do ssh "$h" 'for ip in 10.10.100.10 10.10.100.11 10.10.100.12 10.10.100.13 10.10.100.14 10.10.100.15 10.10.100.16 10.10.100.17; do ping -c 1 -W 1 -M do -s 8972 "$ip" >/dev/null 2>&1 && echo "$ip jumbo"; done'; done
```
