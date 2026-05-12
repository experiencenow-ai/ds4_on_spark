# Spark Ring Access Checklist (Ordered Spark Inventory)

This is a **human-run** access + probe checklist for the current Spark ring. It is safe-by-default (no `sudo`, no service changes, no writes outside `/private/tmp` on the Mac). Treat the ordered host list as the inventory; when a Spark is added, append it to the list used by the probe commands.

## 1) Hostnames + Resolution

- Decide stable identities for each node:
  - `spark0` => `aitopatom-9ab9.local` (observed)
  - `spark1` => `spark1.local` (placeholder until provisioned)
  - `spark2` => `spark2.local` (placeholder until provisioned)
- Confirm whether the environment relies on mDNS (`*.local`) or pinned `/etc/hosts`.
- From the Mac, confirm each target resolves and port 22 is reachable:
  - `REDACT=1 DS4_GIT_DIR=.codex_git DS4_GIT_WORK_TREE=. ./scripts/mac_spark_discovery.sh aitopatom-9ab9.local spark1.local spark2.local`
- From Spark nodes, confirm the same peer names resolve inside the ring environment:
  - `./scripts/spark_ring_probe.sh` prints `== peer ping ==` and reports `ping_resolve_failed` when a node cannot resolve a peer hostname; treat this as a bring-up blocker for any multi-node runbook until name resolution is fixed (either mDNS domain consistency or `/etc/hosts` pinning by a human).

## 2) SSH Keys + Known Hosts Hygiene

- Prefer key auth (no interactive password prompts) for each host user.
- Keep host keys in a dedicated, probe-scoped file (not `~/.ssh/known_hosts`):
  - Set `SPARK_KNOWN_HOSTS_PER_HOST=1` (per-target files under `/private/tmp`) or set `SPARK_KNOWN_HOSTS=/private/tmp/...` explicitly.
- Confirm you can run a non-interactive command on each host:
  - `SPARK_SSH_USER=spark0 SPARK_KNOWN_HOSTS_PER_HOST=1 ssh -o BatchMode=yes -o ConnectTimeout=10 -o StrictHostKeyChecking=accept-new -o UserKnownHostsFile=/private/tmp/ds4_spark_known_hosts.aitopatom-9ab9.local spark0@aitopatom-9ab9.local 'hostname'`

## 3) Clock Sync (Skew + NTP State)

- Verify each node’s UTC time is sane and NTP is synchronized (or at least consistent):
  - Use `./scripts/spark_ring_probe.sh` output `== clock ==` (prints UTC + epoch + `timedatectl` fields when available).
- Rule of thumb: if `skew_s (remote-local)` exceeds about `±1s`, treat it as a blocker for distributed experiments (TP>1) until a human fixes time sync.

## 4) Address Matrix (Wired + Wi‑Fi + v4/v6)

Capture a non-secret identity snapshot suitable for commit:

- One-shot (recommended): produce a full snapshot set (mac discovery + ring probe + MTU + BW + Spark0 facts):
  - `REDACT=1 SPARK_KNOWN_HOSTS_PER_HOST=1 DS4_GIT_DIR=.codex_git DS4_GIT_WORK_TREE=. ./scripts/spark_ring_probe_snapshots.sh aitopatom-9ab9.local spark1.local spark2.local`
- When Spark1/Spark2 become reachable, also capture per-node facts-only snapshots (toolchain/GPU/storage facts; stable bring-up data):
  - `REDACT=1 SPARK_NODE_FACTS=1 SPARK_KNOWN_HOSTS_PER_HOST=1 DS4_GIT_DIR=.codex_git DS4_GIT_WORK_TREE=. ./scripts/spark_ring_probe_snapshots.sh aitopatom-9ab9.local spark1.local spark2.local`
- Facts-only per-node snapshots without the full ring set:
  - `REDACT=1 SPARK_KNOWN_HOSTS_PER_HOST=1 DS4_GIT_DIR=.codex_git DS4_GIT_WORK_TREE=. ./scripts/spark_ring_probe_facts.sh aitopatom-9ab9.local spark1.local spark2.local`
- Mac-side interface + route snapshot:
  - `REDACT=1 DS4_GIT_DIR=.codex_git DS4_GIT_WORK_TREE=. ./scripts/mac_spark_discovery.sh aitopatom-9ab9.local spark1.local spark2.local`
- Per-node interface + address snapshot (redacted):
  - `SPARK_SSH_USER=spark0 REDACT=1 SPARK_KNOWN_HOSTS_PER_HOST=1 DS4_GIT_DIR=.codex_git DS4_GIT_WORK_TREE=. ./scripts/spark_ring_probe.sh aitopatom-9ab9.local spark1.local spark2.local || true`

Record (for each node):
- Primary SSH-reachable name (and whether it’s IPv4, IPv6 link-local, or routed v4).
- Wired interface name(s) and MTU (jumbo vs standard).
- Wi‑Fi interface name(s) and MTU.
- Use the ring probe `== network (iface matrix, compact) ==` section to join interface `state`/`mtu`/`speed` with per-interface v4/v6 addresses (already redacted).

Optional: write down the matrix (fill with redacted values as needed):

| Node | SSH target | SSH path | Wired ifname | Wired MTU | Wi‑Fi ifname | Wi‑Fi MTU | Notes |
|------|------------|----------|--------------|----------:|--------------|----------:|-------|
| spark0 | `aitopatom-9ab9.local` | `v6 link-local` / `v4` | `enP7s7` | `9000` | `wlP9s9` | `1500` | 10GbE link expected |
| spark1 | `spark1.local` | `v6 link-local` / `v4` | — | — | — | — | not provisioned |
| spark2 | `spark2.local` | `v6 link-local` / `v4` | — | — | — | — | not provisioned |

## 5) MTU Consistency

- Ensure the intended fabric (wired vs Wi‑Fi) uses consistent MTU across nodes for tests that care about latency/bandwidth.
- Use the ring probe `== network (mtu, compact) ==` section (from `ip -br link`) to spot mismatches quickly.
- The Mac discovery snapshot also records `mtu` for `en0`/`en1` via `ifconfig` for context.
- Optional: validate MTU end-to-end with DF pings from each host to its peers:
  - `SPARK_SSH_USER=spark0 REDACT=1 SPARK_KNOWN_HOSTS_PER_HOST=1 DS4_GIT_DIR=.codex_git DS4_GIT_WORK_TREE=. ./scripts/spark_ring_probe_mtu.sh --topology full aitopatom-9ab9.local spark1.local spark2.local || true`
  - Override payload sizes (comma-separated, no spaces): `MTU_PAYLOADS=1472,8972`

## 6) Bandwidth/Latency (Safe, Non-Secret)

- Use ping RTT as the minimum viable latency check:
  - `./scripts/mac_spark_discovery.sh` prints `== ping (mac->targets, compact) ==` (Mac→target RTT/loss; no SSH required).
  - `./scripts/spark_ring_probe.sh` prints `== peer ping ==` results from each host to its neighbors (ring topology) or to all peers (`--topology full`), including packet loss and RTT summary when available.
- The ring probe also prints `== network (link speed, compact) ==` (sysfs `speed`/`duplex`) so you can sanity-check whether links negotiated at the expected rate without running active traffic.
- Optional (no installs): quick Mac<->Spark single-stream throughput smoke test (writes nothing; consumes CPU/network briefly):
  - `BW_MB=16 SPARK_SSH_USER=spark0 REDACT=1 SPARK_KNOWN_HOSTS_PER_HOST=1 DS4_GIT_DIR=.codex_git DS4_GIT_WORK_TREE=. ./scripts/spark_ring_probe_bw.sh aitopatom-9ab9.local spark1.local spark2.local || true`
  - The probe reports one-way best-effort throughput for `down` (remote→mac) and `up` (mac→remote). Keep `BW_MB` small (e.g. `8` or `16`) and do not run this in tight loops.
  - When SSH cannot connect (DNS, routing, auth), the probe prints `ssh status: ...` (`resolve_failed`, `no_route`, `timeout`, `auth_failed`) to make bring-up blockers obvious in commit-safe snapshots.
- If you later add a bandwidth tool (e.g. `iperf3`) by human action, document it in a separate runbook; do not install packages from automation loops.
- If `iperf3` is already present on all nodes, you can do a quick throughput check (do not commit raw IPs; summarize results or redact manually):
  - On receiver: `iperf3 -s`
  - On sender: `iperf3 -c <receiver-ip> -t 10 -P 4`
- If `ib_write_bw` / `ib_write_lat` (perftest) is already installed, you can validate RDMA/RoCE fabric performance similarly; this is higher risk (active traffic), so keep it human-run and outside automation loops.

## 7) Safe GPU/Storage Metadata Capture

For each node, capture:
- GPU inventory (`nvidia-smi` CSV query output: GPU name, bus id, driver version, compute cap when available).
- Toolkit banner (`nvcc --version`) and `/usr/local/cuda/version.json` (toolkit version) when present.
- Storage facts (`df -h` + `lsblk` model/size).

Use `REDACT=1` for any committed output.

## 8) Commit-Safe Redaction Rule

- Always generate snapshot docs with `REDACT=1`.
- Treat hostnames, OS/kernel/toolchain versions, GPU model names, disk model names, and interface names as non-secret.
- Treat IP addresses (including CIDR), MAC addresses, GPU UUID tokens, and any host keys as sensitive; the probe scripts redact them automatically when `REDACT=1`.
