# SPARKNETWORK

Load this file first for any Centaur/Spark networking work. It is the canonical
Spark ring inventory and communication contract for this repo.

Last verified: `2026-05-18T0008Z` UTC.

## Rule Zero

Do not confuse SSH login names with network hostnames.

- SSH users: `spark0`, `spark1`, `spark2`.
- Network hostnames: device/Bonjour names such as `aitopatom-9ab9.local`,
  `edgexpert-d623.local`, and `aitopatom-931a.local`.
- Do not use `spark1.local` or `spark2.local` unless those aliases are
  deliberately pinned in DNS or `/etc/hosts`.

## Canonical Ring Inventory

| Ring role | SSH target | Network hostname | Current state |
|-----------|------------|------------------|---------------|
| `spark0` | `spark0@aitopatom-9ab9.local` | `aitopatom-9ab9.local` | Verified reachable |
| `spark1` | `spark1@edgexpert-d623.local` | `edgexpert-d623.local` | Verified reachable |
| `spark2` | `spark2@aitopatom-931a.local` | `aitopatom-931a.local` | Verified from Spark0/Spark1 over ring; Mac direct SSH blocked |

The physical/logical Centaur ring order is:

```text
spark0 <-> spark1 <-> spark2 <-> spark0
```

Every Spark communicates with exactly two ring neighbors. For the current
three-node ring, each node's neighbors are the other two nodes. For larger rings,
the neighbors are the previous and next entries in the ordered inventory.

## Verified Reach Commands

Use per-host known-hosts files. This keeps probe state out of
`~/.ssh/known_hosts` and makes repeated runs easier to reason about.

```bash
ssh -o BatchMode=yes -o ConnectTimeout=10 -o StrictHostKeyChecking=accept-new -o UserKnownHostsFile=/private/tmp/ds4_spark_known_hosts.aitopatom-9ab9.local spark0@aitopatom-9ab9.local hostname
ssh -o BatchMode=yes -o ConnectTimeout=10 -o StrictHostKeyChecking=accept-new -o UserKnownHostsFile=/private/tmp/ds4_spark_known_hosts.edgexpert-d623.local spark1@edgexpert-d623.local hostname
```

Spark2 is not currently reachable directly from the Mac by hostname or Wi-Fi SSH.
Reach it through a verified ring neighbor:

```bash
ssh -o BatchMode=yes -o ConnectTimeout=10 -o StrictHostKeyChecking=accept-new -o UserKnownHostsFile=/private/tmp/ds4_spark_known_hosts.aitopatom-931a.via-spark0 -o ProxyCommand='ssh -o BatchMode=yes -o ConnectTimeout=10 -o StrictHostKeyChecking=accept-new -o UserKnownHostsFile=/private/tmp/ds4_spark_known_hosts.aitopatom-9ab9.local -W %h:%p spark0@aitopatom-9ab9.local' spark2@10.10.2.232 hostname
ssh -o BatchMode=yes -o ConnectTimeout=10 -o StrictHostKeyChecking=accept-new -o UserKnownHostsFile=/private/tmp/ds4_spark_known_hosts.aitopatom-931a.via-spark1 -o ProxyCommand='ssh -o BatchMode=yes -o ConnectTimeout=10 -o StrictHostKeyChecking=accept-new -o UserKnownHostsFile=/private/tmp/ds4_spark_known_hosts.edgexpert-d623.local -W %h:%p spark1@edgexpert-d623.local' spark2@10.10.5.2 hostname
```

The current Mac Studio has an installed `~/.ssh/config` block named
`DS4 SPARKNETWORK`, so these short aliases work from the Mac:

```bash
ssh spark0 hostname
ssh spark1 hostname
ssh spark2 hostname
```

From Spark0 itself, `aitopatom-931a.local` resolves to the Spark0-Spark2 ring
fabric. From Spark1 itself, the same hostname resolves to the Spark1-Spark2 ring
fabric. From the Mac, use the jump commands above until Spark2 control-plane SSH
is fixed.

## Current Probe Evidence

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

- `en1`: Wi-Fi/control network `172.16.11.244/24`.
- `en0`: direct wired path to Spark0, `192.168.100.1/16`.
- Direct Mac SSH works to Spark0/Spark1. Direct Mac SSH does not currently work
  to Spark2.

Spark0 (`aitopatom-9ab9`):

- `wlP9s9`: Wi-Fi/control `172.16.11.228/24`, MTU 1500.
- `enP7s7`: direct Mac wired `192.168.100.2/16` and `10.0.0.2/24`, 10G,
  MTU 9000.
- Spark0-Spark1 ring: `10.10.1.1/24` on the Spark0 side. Spark1 answers on
  `10.10.1.248` and `10.10.1.252`.
- Spark0-Spark2 ring: `10.10.2.1/24` on the Spark0 side. Spark2 answers on
  `10.10.2.232` and `10.10.2.2`.
- Additional up 200G interfaces currently configured as `10.10.3.1/24` and
  `10.10.4.1/24`; no active SSH peer was verified on those subnets.

Spark1 (`edgexpert-d623`):

- `enP7s7`: down.
- `wlP9s9`: Wi-Fi/control `172.16.11.225/24`, MTU 1500.
- Spark1-Spark0 ring: `10.10.1.248/24` and `10.10.1.252/24` on the Spark1
  side. Spark0 answers on `10.10.1.1`.
- Spark1-Spark2 ring: `10.10.5.1/24` and `10.10.6.1/24` on the Spark1 side.
  Spark2 answers on `10.10.5.2` and `10.10.6.2`.

Spark2 (`aitopatom-931a`):

- `enP7s7`: down.
- `wlP9s9`: Wi-Fi/control `172.16.11.208/24`, MTU 1500. Mac direct TCP/22
  timed out during verification, so do not depend on this as the current control
  path.
- Spark2-Spark0 ring: `10.10.2.232/24` and `10.10.2.2/24` on the Spark2 side.
  Spark0 answers on `10.10.2.1`.
- Spark2-Spark1 ring: `10.10.5.2/24` and `10.10.6.2/24` on the Spark2 side.
  Spark1 answers on `10.10.5.1` and `10.10.6.1`.

## Exact Communication Paths

| From | To | Preferred command/path |
|------|----|------------------------|
| Mac | Spark0 | `spark0@aitopatom-9ab9.local` or `spark0@192.168.100.2` |
| Mac | Spark1 | `spark1@edgexpert-d623.local` |
| Mac | Spark2 | SSH jump through Spark0 to `spark2@10.10.2.232` or through Spark1 to `spark2@10.10.5.2` |
| Spark0 | Spark1 | `spark1@edgexpert-d623.local`, resolves on Spark0 to ring address `10.10.1.248` |
| Spark0 | Spark2 | `spark2@aitopatom-931a.local`, resolves on Spark0 to ring address `10.10.2.232` |
| Spark1 | Spark0 | `spark0@aitopatom-9ab9.local`, resolves on Spark1 to ring address `10.10.1.1` |
| Spark1 | Spark2 | `spark2@aitopatom-931a.local`, resolves on Spark1 to ring address `10.10.5.2` |
| Spark2 | Spark0 | `spark0@aitopatom-9ab9.local`, resolves on Spark2 to ring address `10.10.2.1` |
| Spark2 | Spark1 | `spark1@edgexpert-d623.local`, resolves on Spark2 to ring address `10.10.5.1` |

Current Spark2 control-plane issue: Spark2's Wi-Fi address is present as
`172.16.11.208/24`, but Mac direct TCP/22 timed out. Until that is fixed, use
ring-neighbor jump SSH.

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
| HyoR agent HTTP | Spark2 | `8766` | Node API; reach through ring path until Wi-Fi SSH/control is fixed |

Start controller on Spark0:

```bash
ssh -o BatchMode=yes -o ConnectTimeout=10 -o StrictHostKeyChecking=accept-new -o UserKnownHostsFile=/private/tmp/ds4_spark_known_hosts.aitopatom-9ab9.local spark0@aitopatom-9ab9.local \
  'export CENTAUR_ROOT=~/centaur-smoke/v73/run/centaur_spec_impl_v73; export CENTAUR_VENV=~/centaur-smoke/v73/run/venv; sh -s -- ~/centaur-smoke/v73/run/hyor/controller 0.0.0.0 8765' \
  < ./scripts/centaur_spark_hyor_controller_http_v73.sh
```

Start agent on Spark1:

```bash
ssh -o BatchMode=yes -o ConnectTimeout=10 -o StrictHostKeyChecking=accept-new -o UserKnownHostsFile=/private/tmp/ds4_spark_known_hosts.edgexpert-d623.local spark1@edgexpert-d623.local \
  'export CENTAUR_ROOT=~/centaur-smoke/v73/run/centaur_spec_impl_v73; export CENTAUR_VENV=~/centaur-smoke/v73/run/venv; export CONTROLLER_URL=http://aitopatom-9ab9.local:8765; sh -s -- ~/centaur-smoke/v73/ring_node/hyor/node_spark1 spark1 "$CONTROLLER_URL" 0.0.0.0 8766' \
  < ./scripts/centaur_spark_hyor_agent_http_v73.sh
```

Use the same pattern for Spark2 through a jump host:

```bash
ssh -o BatchMode=yes -o ConnectTimeout=10 -o StrictHostKeyChecking=accept-new -o UserKnownHostsFile=/private/tmp/ds4_spark_known_hosts.aitopatom-931a.via-spark0 -o ProxyCommand='ssh -o BatchMode=yes -o ConnectTimeout=10 -o StrictHostKeyChecking=accept-new -o UserKnownHostsFile=/private/tmp/ds4_spark_known_hosts.aitopatom-9ab9.local -W %h:%p spark0@aitopatom-9ab9.local' spark2@10.10.2.232 \
  'export CENTAUR_ROOT=~/centaur-smoke/v73/run/centaur_spec_impl_v73; export CENTAUR_VENV=~/centaur-smoke/v73/run/venv; export CONTROLLER_URL=http://aitopatom-9ab9.local:8765; sh -s -- ~/centaur-smoke/v73/ring_node/hyor/node_spark2 spark2 "$CONTROLLER_URL" 0.0.0.0 8766' \
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
3. Verify Spark2 through a ring-neighbor jump.
4. Run the direct-reachability snapshot:

```bash
stamp="$(date -u +%Y-%m-%dT%H%MZ)"
REDACT=1 SPARK_NODE_FACTS=1 SPARK_KNOWN_HOSTS_PER_HOST=1 DS4_GIT_DIR=.codex_git DS4_GIT_WORK_TREE=. SKIP_BW=1 ./scripts/spark_ring_probe_snapshots.sh --stamp "$stamp" --topology ring spark0@aitopatom-9ab9.local spark1@edgexpert-d623.local
```

The existing snapshot helper does not yet support per-target jump hosts, so run
Spark2 facts through the explicit jump command until that helper is extended.

5. Stage Centaur v73 to each directly reachable Spark:

```bash
./scripts/centaur_spark_v73_stage.sh spark0@aitopatom-9ab9.local "~/centaur-smoke/v73"
./scripts/centaur_spark_v73_stage.sh spark1@edgexpert-d623.local "~/centaur-smoke/v73"
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

## Spark2 Control-Plane Repair

Spark2 is discovered as `aitopatom-931a.local` and verified over the ring. Its
Wi-Fi/control-plane SSH path is still broken from the Mac. From the Spark2
console:

```bash
hostname
hostname -f
ip -br addr
systemctl is-active ssh
systemctl is-active avahi-daemon
sudo systemctl enable --now ssh
sudo systemctl enable --now avahi-daemon
```

From the Mac, direct checks currently time out for `172.16.11.208:22`; after
repair, this should show SSH reachable:

```bash
REDACT=1 PING_CHECK=0 ./scripts/mac_spark_discovery.sh aitopatom-9ab9.local edgexpert-d623.local aitopatom-931a.local
```

If mDNS is unreliable, pin stable names with `/etc/hosts` on the Mac and on
every Spark, then update this file.
