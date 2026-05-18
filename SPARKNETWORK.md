# SPARKNETWORK

Load this file first for any Centaur/Spark networking work. It is the canonical
Spark ring inventory and communication contract for this repo.

Last verified: `2026-05-19T0834Z` UTC.

## Rule Zero

Do not confuse SSH login names with network hostnames.

- SSH users: `spark0`, `spark1`, `spark2`.
- Network hostnames: device/Bonjour names such as `aitopatom-9ab9.local`,
  `edgexpert-d623.local`, and `aitopatom-931a.local`.
- Do not use `spark1.local` or `spark2.local` unless those aliases are
  deliberately pinned in DNS or `/etc/hosts`.

## Current Office Topology

The cluster is now in the office on a 5-port 10G switch shared by Mac Studio,
Spark0, Spark1, Spark2, and the fiber modem. The sane control/sync layout is:

| Node | Normal SSH | Hostname | 10G DHCP/control | 10G private sync |
|------|------------|----------|------------------|------------------|
| Mac Studio | local operator | `Mac-Studio.local` | `175.193.138.31/24` on `en0` | `10.20.0.1/24` alias on `en0` |
| Spark0 | `ssh spark0` | `aitopatom-9ab9` | `175.193.138.80/24` on `enP7s7` | `10.20.0.10/24` on `enP7s7` |
| Spark1 | `ssh spark1` | `edgexpert-d623` | `125.129.239.251/24` on `enP7s7` | `10.20.0.11/24` on `enP7s7` |
| Spark2 | `ssh spark2` | `aitopatom-931a` | `175.193.138.108/24` on `enP7s7` | `10.20.0.12/24` on `enP7s7` |

The Mac SSH config block maps `spark0`, `spark1`, and `spark2` to the current
10G DHCP/control addresses. It also defines `spark0-10g`, `spark1-10g`, and
`spark2-10g` for the private switch-local subnet. The Mac Studio alias should be
installed as a `/24`; if it was installed as a broad `10/8`, replace it:

```bash
sudo ifconfig en0 -alias 10.20.0.1
sudo ifconfig en0 inet 10.20.0.1 netmask 255.255.255.0 alias
```

The Sparks already verify each other on the private 10G switch subnet:

```text
spark0 -> 10.20.0.11, 10.20.0.12 OK
spark1 -> 10.20.0.10, 10.20.0.12 OK
spark2 -> 10.20.0.10, 10.20.0.11 OK
```

Keep the network planes separate:

- `enP7s7` + DHCP: office/fiber control and internet.
- `enP7s7` + `10.20.0.0/24`: private 10G switch-local Spark sync.
- `wlP9s9` + `192.168.0.0/24`: Wi-Fi fallback only.
- `10.10.x.x`: 200G Spark ring fabric; do not use this as the Mac control
  plane.

The wired/fiber path provides internet from all three Sparks. A quick Cloudflare
download probe measured about `1.46 Gbit/s` from Spark0, `1.01 Gbit/s` from
Spark1, and `1.15 Gbit/s` from Spark2. The TP-Link Wi-Fi LAN is connected but
does not currently provide internet; the Spark defaults prefer `enP7s7`.

## 200G Ring Fabric

The 200G ring is fixed as six `/30` point-to-point links, two parallel links per
ring edge. Every interface below reports `200000Mb/s`, jumbo MTU ping with
`8972` bytes succeeds, and TCP/22 is reachable over each link.

| Edge | Link | Spark A | Spark B |
|------|------|---------|---------|
| Spark0-Spark1 | A | Spark0 `enp1s0f1np1` `10.10.1.1/30` | Spark1 `enp1s0f1np1` `10.10.1.2/30` |
| Spark0-Spark1 | B | Spark0 `enP2p1s0f1np1` `10.10.2.1/30` | Spark1 `enP2p1s0f1np1` `10.10.2.2/30` |
| Spark1-Spark2 | A | Spark1 `enp1s0f0np0` `10.10.3.1/30` | Spark2 `enp1s0f0np0` `10.10.3.2/30` |
| Spark1-Spark2 | B | Spark1 `enP2p1s0f0np0` `10.10.4.1/30` | Spark2 `enP2p1s0f0np0` `10.10.4.2/30` |
| Spark2-Spark0 | A | Spark2 `enp1s0f1np1` `10.10.5.2/30` | Spark0 `enp1s0f0np0` `10.10.5.1/30` |
| Spark2-Spark0 | B | Spark2 `enP2p1s0f1np1` `10.10.6.2/30` | Spark0 `enP2p1s0f0np0` `10.10.6.1/30` |

`iperf3` sanity tests on one link per edge measured about `111 Gbit/s` TCP with
four streams: Spark0 to Spark1 on `10.10.1.x`, Spark1 to Spark2 on `10.10.3.x`,
and Spark2 to Spark0 on `10.10.5.x`.

## Canonical Ring Inventory

| Ring role | SSH target | Network hostname | Current state |
|-----------|------------|------------------|---------------|
| `spark0` | `spark0@175.193.138.80` | `aitopatom-9ab9.local` | Verified reachable over office 10G control |
| `spark1` | `spark1@125.129.239.251` | `edgexpert-d623.local` | Verified reachable over office 10G control |
| `spark2` | `spark2@175.193.138.108` | `aitopatom-931a.local` | Verified reachable over office 10G control |

The physical/logical Centaur ring order is:

```text
spark0 <-> spark1 <-> spark2 <-> spark0
```

Every Spark communicates with exactly two ring neighbors. For the current
three-node ring, each node's neighbors are the other two nodes. For larger rings,
the neighbors are the previous and next entries in the ordered inventory.

## Verified Reach Commands

The Mac SSH config has a `DS4 SPARKNETWORK` block for the current office
topology. These are the normal operator commands:

```bash
ssh spark0 hostname
ssh spark1 hostname
ssh spark2 hostname
```

After Mac Studio has the `10.20.0.1/24` alias on `en0`, these private 10G
switch-local commands should also work:

```bash
ssh spark0-10g hostname
ssh spark1-10g hostname
ssh spark2-10g hostname
```

Inside the Spark cluster, `/etc/hosts` pins `spark0-10g`, `spark1-10g`, and
`spark2-10g` to `10.20.0.10`, `10.20.0.11`, and `10.20.0.12`.

## Historical Probe Evidence

The following probe evidence is from the pre-office topology and is kept for
traceability. Prefer the current office topology above for live operations.

Latest redacted snapshot set for Spark0/Spark1:

- `docs/spark-ring-mac-discovery-2026-05-17T2355Z.md`
- `docs/spark-ring-probe-2026-05-17T2355Z.md`
- `docs/spark-ring-latency-probe-2026-05-17T2355Z.md`
- `docs/spark-ring-mtu-probe-2026-05-17T2355Z.md`
- `docs/spark-ring-node-facts-aitopatom-9ab9.local-2026-05-17T2355Z.md`
- `docs/spark-ring-node-facts-edgexpert-d623.local-2026-05-17T2355Z.md`
- `docs/spark0-probe-facts-2026-05-17T2355Z.md`

Snapshot command:

```bash
REDACT=1 SPARK_NODE_FACTS=1 SPARK_KNOWN_HOSTS_PER_HOST=1 DS4_GIT_DIR=.codex_git DS4_GIT_WORK_TREE=. SKIP_BW=1 ./scripts/spark_ring_probe_snapshots.sh --stamp 2026-05-17T2355Z --topology ring spark0@aitopatom-9ab9.local spark1@edgexpert-d623.local
```

Current facts:

| Check | Spark0 | Spark1 | Spark2 |
|-------|--------|--------|--------|
| mDNS from Mac | OK | OK | Not visible from Mac |
| TCP/22 from Mac | OK | OK | Blocked/direct timeout |
| SSH key auth from Mac | OK | OK | OK through Spark0/Spark1 jump |
| Mac ping | OK, 0% loss | OK, 0% loss | Blocked/direct timeout |
| SSH latency p50 | about 320 ms | about 320 ms | Not measured through jump |
| Clock/NTP | OK, skew 0s | OK, skew 0s | OK, `NTPSynchronized=yes` through jump |
| Peer ping | OK to Spark1 | OK to Spark0 | Ring SSH verified to both neighbors |
| 8972-byte MTU payload | OK to Spark1, best effort | OK to Spark0, best effort | Not snapshotted yet |

The latest mDNS browse saw `aitopatom-9ab9 SSH` and `edgexpert-d623 SSH`. It did
not see `aitopatom-931a SSH` from the Mac. Spark0 and Spark1 both see
`aitopatom-931a.local` over their 200G ring interfaces.

## Interface Map

Mac Studio:

- `en0`: office 10G switch and fiber path, `175.193.138.31/24`.
- `en0`: private Spark switch alias, `10.20.0.1/24`. Verify this is not a
  broad `10/8` route before long-running work.
- Direct Mac SSH works to Spark0, Spark1, and Spark2 through `~/.ssh/config`.

Spark0 (`aitopatom-9ab9`):

- `enP7s7`: office 10G control `175.193.138.80/24` and private sync
  `10.20.0.10/24`.
- `wlP9s9`: Wi-Fi fallback `192.168.0.155/24`, no internet when forced.
- 200G to Spark1: `enp1s0f1np1` `10.10.1.1/30`,
  `enP2p1s0f1np1` `10.10.2.1/30`.
- 200G to Spark2: `enp1s0f0np0` `10.10.5.1/30`,
  `enP2p1s0f0np0` `10.10.6.1/30`.

Spark1 (`edgexpert-d623`):

- `enP7s7`: office 10G control `125.129.239.251/24` and private sync
  `10.20.0.11/24`.
- `wlP9s9`: Wi-Fi fallback `192.168.0.146/24`, no internet when forced.
- 200G to Spark0: `enp1s0f1np1` `10.10.1.2/30`,
  `enP2p1s0f1np1` `10.10.2.2/30`.
- 200G to Spark2: `enp1s0f0np0` `10.10.3.1/30`,
  `enP2p1s0f0np0` `10.10.4.1/30`.

Spark2 (`aitopatom-931a`):

- `enP7s7`: office 10G control `175.193.138.108/24` and private sync
  `10.20.0.12/24`.
- `wlP9s9`: Wi-Fi fallback `192.168.0.116/24`, no internet when forced.
- 200G to Spark1: `enp1s0f0np0` `10.10.3.2/30`,
  `enP2p1s0f0np0` `10.10.4.2/30`.
- 200G to Spark0: `enp1s0f1np1` `10.10.5.2/30`,
  `enP2p1s0f1np1` `10.10.6.2/30`.

## Exact Communication Paths

| From | To | Preferred command/path |
|------|----|------------------------|
| Mac | Spark0 | `ssh spark0` or `ssh spark0-10g` |
| Mac | Spark1 | `ssh spark1` or `ssh spark1-10g` |
| Mac | Spark2 | `ssh spark2` or `ssh spark2-10g` |
| Spark0 | Spark1 | `spark1-10g` for control/sync; `10.10.1.2` or `10.10.2.2` for ring traffic |
| Spark0 | Spark2 | `spark2-10g` for control/sync; `10.10.5.2` or `10.10.6.2` for ring traffic |
| Spark1 | Spark0 | `spark0-10g` for control/sync; `10.10.1.1` or `10.10.2.1` for ring traffic |
| Spark1 | Spark2 | `spark2-10g` for control/sync; `10.10.3.2` or `10.10.4.2` for ring traffic |
| Spark2 | Spark0 | `spark0-10g` for control/sync; `10.10.5.1` or `10.10.6.1` for ring traffic |
| Spark2 | Spark1 | `spark1-10g` for control/sync; `10.10.3.1` or `10.10.4.1` for ring traffic |

## Planes

Keep these planes separate.

| Plane | Path | Purpose | Rules |
|-------|------|---------|-------|
| Operator control | Mac Studio to Spark hostnames over Wi-Fi/mDNS or pinned names | SSH, small config pushes, status, service start/stop | Must work even when ring fabric is down |
| Centaur control | HTTP JSON, controller on Spark0 and agent on each Spark | Node registration, health, lightweight commands, agent steps | Small payloads only; do not ship model data here |
| Ring sync | Spark neighbor to Spark neighbor over 200G fabric | Centaur root/object sync, manifests, effective views | Previous/next neighbors only |
| Data plane | 200G fabric | Model/runtime traffic | Never depend on Mac reachability |
| Escape hatch | SSH | Debug, support bundles, manual recovery | Allowlisted service APIs should cover normal ops |

## Writable Roots

Every Spark should have the same directory layout under the Spark login user:

```text
~/centaur-smoke/v73/centaur_spec_impl_v73.zip
~/centaur-smoke/v73/run/centaur_spec_impl_v73/
~/centaur-smoke/v73/run/venv/
~/centaur-smoke/v73/run/hyor/controller/          # Spark0 only by default
~/centaur-smoke/v73/ring_node/hyor/node_spark0/
~/centaur-smoke/v73/ring_node/hyor/node_spark1/
~/centaur-smoke/v73/ring_node/hyor/node_spark2/
~/centaur-smoke/v73/ring_node/effective_spark0/
~/centaur-smoke/v73/ring_node/effective_spark1/
~/centaur-smoke/v73/ring_node/effective_spark2/
/tmp/sparknetwork/                                # volatile staging and probes
```

Do not require root for Centaur staging. Use `/tmp` for transient probes and the
home-directory roots above for durable user-writable state.

## Existing Centaur HTTP Pieces

The repo already has smoke-grade wrappers:

- Controller HTTP on Spark0: `scripts/centaur_spark_hyor_controller_http_v73.sh`
- Node agent HTTP on each Spark: `scripts/centaur_spark_hyor_agent_http_v73.sh`
- Controller-side node discovery: `scripts/centaur_spark_hyor_node_discover_v73.sh`

Default ports:

| Service | Host | Port | Notes |
|---------|------|------|-------|
| HyoR controller HTTP | Spark0 | `8765` | Controller API |
| HyoR agent HTTP | Spark0 | `8766` | Optional local agent |
| HyoR agent HTTP | Spark1 | `8766` | Node API |
| HyoR agent HTTP | Spark2 | `8766` | Node API; prefer `spark2-10g`/`10.20.0.12` |

Start controller on Spark0:

```bash
ssh spark0 \
  'export CENTAUR_ROOT=~/centaur-smoke/v73/run/centaur_spec_impl_v73; export CENTAUR_VENV=~/centaur-smoke/v73/run/venv; sh -s -- ~/centaur-smoke/v73/run/hyor/controller 0.0.0.0 8765' \
  < ./scripts/centaur_spark_hyor_controller_http_v73.sh
```

Start agent on Spark1:

```bash
ssh spark1 \
  'export CENTAUR_ROOT=~/centaur-smoke/v73/run/centaur_spec_impl_v73; export CENTAUR_VENV=~/centaur-smoke/v73/run/venv; export CONTROLLER_URL=http://spark0-10g:8765; sh -s -- ~/centaur-smoke/v73/ring_node/hyor/node_spark1 spark1 "$CONTROLLER_URL" 0.0.0.0 8766' \
  < ./scripts/centaur_spark_hyor_agent_http_v73.sh
```

Use the same pattern for Spark2:

```bash
ssh spark2 \
  'export CENTAUR_ROOT=~/centaur-smoke/v73/run/centaur_spec_impl_v73; export CENTAUR_VENV=~/centaur-smoke/v73/run/venv; export CONTROLLER_URL=http://spark0-10g:8765; sh -s -- ~/centaur-smoke/v73/ring_node/hyor/node_spark2 spark2 "$CONTROLLER_URL" 0.0.0.0 8766' \
  < ./scripts/centaur_spark_hyor_agent_http_v73.sh
```

## Sparknetwork Service Contract

Build one small service that runs on every Spark. Name it `sparknetworkd` unless
we pick a better name later.

The service should not be a general shell over HTTP. It should expose a small,
allowlisted API for the repeated operations we need:

| Endpoint | Method | Purpose |
|----------|--------|---------|
| `/v1/node` | GET | Node id, hostname, roles, interface summary, writable root paths |
| `/v1/peers` | GET | Previous/next ring neighbors from this file's inventory |
| `/v1/health` | GET | Clock, disk, Centaur venv, CUDA summary, agent/controller state |
| `/v1/ping-peer` | POST | Probe one declared neighbor over control or ring path |
| `/v1/sync/status` | GET | Content hashes/manifests for the local Centaur node root |
| `/v1/sync/pull` | POST | Pull changed root/object data from a declared neighbor |
| `/v1/sync/push` | POST | Push changed root/object data to a declared neighbor |
| `/v1/centaur/agent-step` | POST | Run one HyoR agent step from the local node root |
| `/v1/centaur/apply-effective` | POST | Materialize effective view into the local effective dir |
| `/v1/logs/tail` | GET | Return bounded logs for diagnosis |

Security rules:

- Bind to the control interface by default, not public internet.
- Require an auth token once we move beyond smoke testing.
- Accept only inventory-declared peers.
- Refuse arbitrary command strings; every action is a typed operation.
- Keep large model files out of the HTTP control API.

## Efficient Ring Sync Design

The fastest sane design is two-level sync:

1. Control plane decides what to sync and records manifests.
2. Ring data plane moves bytes directly between neighbor Sparks over the 200G
   fabric.

Use content-addressed manifests so unchanged files are never recopied:

```text
manifest.json:
  node_id
  root_epoch
  files[]:
    path
    size
    mtime_ns
    sha256 or fast hash
```

Initial implementation:

- Use `rsync --delete --partial` over SSH between declared ring neighbors.
- Use the 200G fabric hostname/IP once known; use Wi-Fi only for bootstrap.
- Keep node roots local and writable on each Spark.
- Sync only neighbor roots, never full mesh.

Better implementation:

- `sparknetworkd` compares manifests with neighbors.
- Large file transfers use a streaming endpoint or `rsync` subprocess pinned to
  the ring interface.
- Small JSON control messages stay on HTTP.
- Each sync has an idempotent `sync_id` so retries are safe.

Centaur-specific rule:

- `hyor-ring-step` currently expects local writable peer roots.
- Until the service owns distributed peer-root sync, use
  `scripts/centaur_spark_ring_rsync_v73.sh` as the staging workaround.
- Long term, `sparknetworkd` should maintain the local mirror of each neighbor
  root, then run Centaur steps against those local mirrors.

## Bootstrap Sequence

1. Load `SPARKNETWORK.md`.
2. Verify SSH to all known targets.
3. Verify `spark0-10g`, `spark1-10g`, and `spark2-10g`.
4. Run the direct-reachability snapshot:

```bash
stamp="$(date -u +%Y-%m-%dT%H%MZ)"
REDACT=1 SPARK_NODE_FACTS=1 SPARK_KNOWN_HOSTS_PER_HOST=1 DS4_GIT_DIR=.codex_git DS4_GIT_WORK_TREE=. SKIP_BW=1 ./scripts/spark_ring_probe_snapshots.sh --stamp "$stamp" --topology ring spark0 spark1 spark2
```

5. Stage Centaur v73 to each directly reachable Spark:

```bash
./scripts/centaur_spark_v73_stage.sh spark0 "~/centaur-smoke/v73"
./scripts/centaur_spark_v73_stage.sh spark1 "~/centaur-smoke/v73"
./scripts/centaur_spark_v73_stage.sh spark2 "~/centaur-smoke/v73"
```

For Spark2, stream or rsync through Spark0/Spark1 until direct control-plane SSH
is fixed.

6. Run node setup on each directly reachable Spark:

```bash
./scripts/centaur_spark_v73_node_setup_run.sh spark0@aitopatom-9ab9.local "~/centaur-smoke/v73"
./scripts/centaur_spark_v73_node_setup_run.sh spark1@edgexpert-d623.local "~/centaur-smoke/v73"
```

7. Start the controller on Spark0 and agents on every Spark.
8. Use ring-neighbor sync for root/object updates.
9. Use SSH only as the debug escape hatch once `sparknetworkd` exists.

## Wi-Fi Fallback

The TP-Link Wi-Fi LAN is visible and all three Sparks are associated:

| Node | Active Wi-Fi SSID | Wi-Fi address | Internet when forced through Wi-Fi |
|------|-------------------|---------------|------------------------------------|
| Spark0 | `TP-Link_01A6` | `192.168.0.155/24` | no |
| Spark1 | `TP-Link_01A6_5G` | `192.168.0.146/24` | no |
| Spark2 | `TP-Link_01A6` | `192.168.0.116/24` | no |

Do not use Wi-Fi as the internet/control primary while the router has no WAN
connectivity. Keep the wired `enP7s7` default route preferred. If a Spark loses
wired control, Wi-Fi can still be used as a same-LAN fallback from another node
on `192.168.0.0/24`.

Useful checks:

```bash
nmcli -t -f ACTIVE,SSID,BSSID,DEVICE,SIGNAL dev wifi | grep '^yes'
ip route get 1.1.1.1
curl -4 --interface wlP9s9 --max-time 8 https://ifconfig.me
```

`curl --interface wlP9s9` should fail until the TP-Link router has WAN internet.
