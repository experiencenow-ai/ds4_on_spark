# SPARKNETWORK

Load this file first for any Centaur/Spark networking work. The machine-readable
source of truth is [`sparknetwork.json`](sparknetwork.json); this document is the
human runbook derived from it.

Last verified: `2026-05-23T02:02Z` UTC.

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

Mac Studio `en1` is `192.168.1.128/24`. Mac Studio `en0` has an active 10G
link and `10.20.0.1/24` for direct Spark access. The Mac default route must
stay on Wi-Fi or another known-good internet path for remote desktop; do not
route broad internet traffic through Spark3 unless physically present.

The 200G fabric is now a closed routed ring:

```text
spark0 -> spark1 -> spark2 -> spark3 -> spark4 -> spark5 -> spark6 -> spark7 -> spark0
```

Spark7 now closes the return edge into Spark0. The 10G switch plane is not a
substitute for the 200G fabric; it remains the operator/control plane.

## Canonical Inventory

| Node | SSH alias | Network hostname | Current primary path from Mac | Direct Wi-Fi backup |
|------|-----------|------------------|-------------------------------|--------------------|
| Spark0 | `ssh spark0` | `aitopatom-9ab9.local` | Mac -> Spark3 Wi-Fi -> Spark2 200G -> Spark1 200G -> Spark0 200G | `ssh spark0-wifi`, `192.168.1.127` |
| Spark1 | `ssh spark1` | `edgexpert-d623.local` | Mac -> Spark3 Wi-Fi -> Spark2 200G -> Spark1 200G | `ssh spark1-wifi`, `192.168.1.226` |
| Spark2 | `ssh spark2` | `aitopatom-931a.local` | Mac -> Spark3 Wi-Fi -> Spark2 200G | `ssh spark2-wifi`, `192.168.1.166` |
| Spark3 | `ssh spark3` | `aitopatom-a18f.local` | Direct Wi-Fi, `192.168.1.110` | `ssh spark3-wifi`, `192.168.1.110` |
| Spark4 | `ssh spark4` | `aitopatom-c342.local` | Direct Wi-Fi, `192.168.1.137` | `ssh spark4-wifi`, `192.168.1.137` |
| Spark5 | `ssh spark5` | `aitopatom-a36d.local` | Mac -> Spark4 Wi-Fi -> Spark5 200G | `ssh spark5-wifi`, `192.168.1.245` |
| Spark6 | `ssh spark6` | `aitopatom-c637.local` | Direct Wi-Fi, `192.168.1.185` | `ssh spark6-wifi`, `192.168.1.185` |
| Spark7 | `ssh spark7` | `thinkstation-pgx.local` | Direct Wi-Fi, `192.168.1.236` | `ssh spark7`, `192.168.1.236` |

Current verified manual access paths:

```bash
ssh spark0-wifi hostname
ssh spark1-wifi hostname
ssh spark2-wifi hostname
ssh spark3@192.168.1.110 hostname
ssh spark4@192.168.1.137 hostname
ssh spark5-wifi hostname
ssh spark6@192.168.1.185 hostname
ssh spark7 hostname
ssh -o ProxyCommand='ssh spark3@192.168.1.110 nc 10.10.5.2 22' spark2@10.10.5.2 hostname
ssh -o ProxyCommand='ssh spark4@192.168.1.137 nc 10.10.9.2 22' spark5@10.10.9.2 hostname
```

Spark0 and Spark1 are alive after reboot, and every node from Spark0 through
Spark7 has a direct Wi-Fi SSH path. The Mac Studio `DS4 SPARKNETWORK` SSH block
was updated at `2026-05-22T00:00Z`; bare `ssh spark0` through `ssh spark7` and
`ssh spark0-wifi` through `ssh spark6-wifi` were verified again at
`2026-05-22T00:26Z`.

## 10G Control Plane

Mac Studio:

- `en1`: Wi-Fi path, `192.168.1.128/24`.
- `en0`: 10G link active, reserved private alias `10.20.0.1/24`; keep the Mac
  default route on Wi-Fi or another known-good internet path for remote desktop.

Private 10G assignments:

| Node | Interface | Address | State |
|------|-----------|---------|-------|
| Mac Studio | `en0` | `10.20.0.1/24` | 10G cluster access only; default route remains on Wi-Fi |
| Spark0 | `enP7s7` | `10.20.0.10/24` | 10G client; default route via Spark3 NAT |
| Spark1 | `enP7s7` | `10.20.0.11/24`, DHCP `125.129.239.251/24` | direct KT lease plus private 10G |
| Spark2 | `enP7s7` | `10.20.0.12/24` | 10G client; default route via Spark3 NAT |
| Spark3 | `enP7s7` | `10.20.0.13/24`, DHCP `125.129.239.57/24` | temporary 10G NAT gateway |
| Spark4 | `enP7s7` | `10.20.0.14/24` | switch control, plus DHCP `175.193.138.138/24` |
| Spark5 | `enP7s7` | `10.20.0.15/24` | switch control, plus DHCP `175.193.138.193/24` |
| Spark6 | `enP7s7` | `10.20.0.16/24` | 10G client; default route via Spark3 NAT |
| Spark7 | `enP7s7` | `10.20.0.17/24` | 10G client; default route via Spark3 NAT |

The `10.20.0.0/24` control plane is flat again across Spark0 through Spark7.
Spark3 is the temporary software gateway for nodes without a direct KT lease.

Temporary 10G internet-sharing services:

- Gateway node: Spark3, public source `125.129.239.57`, private gateway
  `10.20.0.13`.
- Gateway service: `ds4-10g-nat-gateway.service`, script
  `/usr/local/sbin/ds4-10g-nat-gateway-apply`.
- Client service: `ds4-10g-client-gateway.service`, script
  `/usr/local/sbin/ds4-10g-client-gateway-apply`.
- Installed clients: Spark0, Spark2, Spark6, and Spark7. Each has default route
  `10.20.0.13 dev enP7s7 metric 50`, with Wi-Fi default route still present at
  metric `600` as fallback.
- Checked-in source scripts:
  `scripts/ds4_10g_nat_gateway_apply.sh` and
  `scripts/ds4_10g_client_gateway_apply.sh`.

To give the Mac Studio direct 10G cluster access, run this on the Mac:

```bash
scripts/ds4_mac_10g_gateway_apply.sh
```

The script installs `10.20.0.1/24` on `en0` and removes any stale `/1` route
overrides through Spark3. It does **not** change the Mac's internet default
route unless `DS4_MAC_10G_DEFAULT_ROUTE=1` is explicitly set. This keeps Jump
Desktop and other remote-control software on the stable route.

Incident note: the original script behavior did install broad `/1` route
overrides and broke remote access on `2026-05-23`. Keep
[`docs/ops-macstudio-spark3-route-incident-2026-05-23.md`](docs/ops-macstudio-spark3-route-incident-2026-05-23.md)
loaded before changing Mac Studio default routes.

To remove a bad route override:

```bash
scripts/ds4_mac_10g_gateway_disable.sh
```

Manual bad-route rollback:

```bash
sudo route -n delete -net 0.0.0.0/1 10.20.0.13
sudo route -n delete -net 128.0.0.0/1 10.20.0.13
```

Manual cluster-access setup:

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

## Wi-Fi Fallbacks

Wi-Fi is not the primary operator plane.

| Node | Wi-Fi address | SSID/role |
|------|---------------|-----------|
| Spark0 | `192.168.1.127/24` | fallback on `TP-Link_D660_5G`; `ssh spark0-wifi` |
| Spark1 | `192.168.1.226/24` | fallback on `TP-Link_D660_5G`; `ssh spark1-wifi` |
| Spark2 | `192.168.1.166/24` | fallback on `TP-Link_D660_5G`; `ssh spark2-wifi` |
| Spark3 | `192.168.1.110/24` | fallback on `TP-Link_D660_5G`; `ssh spark3-wifi` |
| Spark4 | `192.168.1.137/24` | fallback on `TP-Link_D660_5G`; `ssh spark4-wifi` |
| Spark5 | `192.168.1.245/24` | fallback on `TP-Link_D660_5G`; `ssh spark5-wifi` |
| Spark6 | `192.168.1.185/24` | fallback on `TP-Link_D660_5G`; `ssh spark6-wifi` |
| Spark7 | `192.168.1.236/24` | fallback on `TP-Link_D660`; `ssh spark7` |

## Internet Status

As of `2026-05-22T11:15Z`, all eight Sparks have wired-side internet on
`enP7s7`.

| Node | Wired internet path | Verified public IP |
|------|---------------------|--------------------|
| Spark0 | Spark3 NAT via `10.20.0.13` | `125.129.239.57` |
| Spark1 | Direct KT DHCP on `enP7s7` | `125.129.239.251` |
| Spark2 | Spark3 NAT via `10.20.0.13` | `125.129.239.57` |
| Spark3 | Direct KT DHCP on `enP7s7` | `125.129.239.57` |
| Spark4 | Direct KT DHCP on `enP7s7` | `175.193.138.138` |
| Spark5 | Direct KT DHCP on `enP7s7` | `175.193.138.193` |
| Spark6 | Spark3 NAT via `10.20.0.13` | `125.129.239.57` |
| Spark7 | Spark3 NAT via `10.20.0.13` | `125.129.239.57` |

Mac Studio should keep using Wi-Fi `192.168.1.128/24` or another known-good
internet route for remote desktop. Use `en0`/`10.20.0.1/24` for direct Spark
cluster access only; do not install broad `/1` default-route overrides through
Spark3 on a remote-managed Studio.

Do not use internet availability as a 200G health signal. Use the 200G ring
ping/iperf checks for fabric health and this internet table only for WAN
reachability.

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
- Peer SSH health: `ds4-peer-ssh-heartbeat.timer` runs every minute as the
  Spark user. Each Spark tries the other seven Spark SSH paths and publishes a
  JSON observation into the target node's `~/.ds4-rescue/peer-heartbeats/`
  directory. A fresh record with `ssh_exec_ok=true` means externally healthy; a
  fresh record with `ssh_exec_ok=false` means the target is writable but SSH
  command execution is degraded; stale or missing records mean no peer has been
  able to update the target for the watchdog window.
- Peer SSH auth: deployment creates a per-node Ed25519 key if needed and
  installs the provided nodes' public keys into each other node's
  `authorized_keys`, preserving existing keys. The heartbeat uses concrete 10G
  control targets such as `spark6=spark6@10.20.0.16`, not Mac-only SSH aliases.
- Local self-heal: `ds4-sshd-watchdog.timer` runs every minute as root. If the
  local SSH banner probe fails, or if peer-written external health records are
  degraded/stale for more than `DS4_WATCHDOG_PEER_STALE_SECONDS` seconds
  (default `300`), it restarts SSH, then escalates to runtime and memory-hog
  cleanup.
- Allowlisted heavy-runtime kills: Docker containers named
  `vllm_deepseek_v4_flash`, `vllm_*`, `ds4_vllm_*`, or `centaur_vllm_*`, plus
  process command lines matching `vllm serve` / `VLLM::`. Ray kills are disabled
  unless `DS4_WATCHDOG_KILL_RAY=1` is set in the timer environment.
- Generic memory-hog fallback: after the allowlisted kills, the watchdog kills
  GPU compute processes and up to `16` largest RSS processes above `256 MiB`,
  while protecting only essential OS/network/SSH processes. Tunables:
  `DS4_WATCHDOG_KILL_TOP_MEM_COUNT`, `DS4_WATCHDOG_MIN_KILL_RSS_KB`, and
  `DS4_WATCHDOG_KILL_GPU_PROCS`.
- Reboot escalation is enabled as the last resort after `3` consecutive failed
  rescue attempts by default. Set `DS4_WATCHDOG_REBOOT_AFTER=N` to adjust it or
  `0` to disable it. Peer-health knobs are `DS4_WATCHDOG_PEER_MIN_FRESH`,
  `DS4_WATCHDOG_PEER_STALE_SECONDS`, and
  `DS4_WATCHDOG_PEER_BOOT_GRACE_SECONDS`.
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
through `spark7`. The 2026-05-23 memory-hog escalation is also deployed live to
`spark0` through `spark7`; live script hash:
`bb6e176cbb8506fa84d5ec542ba6f682fabe8737bac5af1dc17eee3c809e2240`.

Chaos verification: Spark7 passed the SSH-port wedge test at
`2026-05-22T20:24` KST. A synthetic allowlisted
`VLLM::watchdog-port-wedge` process stopped the SSH banner, the watchdog killed
the process, and SSH recovered without physical access. Evidence:
[`docs/ops-watchdog-wedge-test-2026-05-22.md`](docs/ops-watchdog-wedge-test-2026-05-22.md).

Repeat the test on a non-critical node with:

```bash
DS4_SUDO_PASSWORD=... scripts/ds4_watchdog_wedge_test.sh spark7
```

Chaos verification: Spark7 passed the generic memory-hog wedge test at
`2026-05-23T11:02` KST. The synthetic process was deliberately **not** named
`vllm` or `VLLM::`; the watchdog recovered SSH by killing the top memory-heavy
processes. Evidence:
[`docs/ops-watchdog-memory-hog-test-2026-05-23.md`](docs/ops-watchdog-memory-hog-test-2026-05-23.md).

Repeat the generic memory-hog test with:

```bash
DS4_SUDO_PASSWORD=... DS4_WATCHDOG_TEST_TAG='DS4MEMHOG::watchdog-port-wedge' DS4_WATCHDOG_TEST_MEM_MIB=768 scripts/ds4_watchdog_wedge_test.sh spark7
```

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
