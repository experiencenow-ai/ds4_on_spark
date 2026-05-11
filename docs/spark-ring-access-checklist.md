# Spark Ring Access Checklist (Spark0..Spark2)

This is a **human-run** access + probe checklist for a 3-node Spark ring. It is safe-by-default (no `sudo`, no service changes, no writes outside `/private/tmp` on the Mac).

If you have 4 nodes (Spark0..Spark3), use the same checklist but add Spark3 to every matrix and command line.

## 1) Hostnames + Resolution

- Decide stable identities for each node:
  - `spark0` => `aitopatom-9ab9.local` (observed)
  - `spark1` => `spark1.local` (placeholder until provisioned)
  - `spark2` => `spark2.local` (placeholder until provisioned)
- Confirm whether the environment relies on mDNS (`*.local`) or pinned `/etc/hosts`.
- From the Mac, confirm each target resolves and port 22 is reachable:
  - `REDACT=1 DS4_GIT_DIR=.codex_git DS4_GIT_WORK_TREE=. ./scripts/mac_spark_discovery.sh aitopatom-9ab9.local spark1.local spark2.local`

## 2) SSH Keys + Known Hosts Hygiene

- Prefer key auth (no interactive password prompts) for each host user.
- Keep host keys in a dedicated, probe-scoped file (not `~/.ssh/known_hosts`):
  - Set `SPARK_KNOWN_HOSTS_PER_HOST=1` (per-target files under `/private/tmp`) or set `SPARK_KNOWN_HOSTS=/private/tmp/...` explicitly.
- Confirm you can run a non-interactive command on each host:
  - `SPARK_SSH_USER=spark0 SPARK_KNOWN_HOSTS_PER_HOST=1 ssh -o BatchMode=yes -o ConnectTimeout=10 -o StrictHostKeyChecking=accept-new -o UserKnownHostsFile=/private/tmp/ds4_spark_known_hosts.aitopatom-9ab9.local spark0@aitopatom-9ab9.local 'hostname'`

## 3) Clock Sync (Skew + NTP State)

- Verify each node’s UTC time is sane and NTP is synchronized (or at least consistent):
  - Use `./scripts/spark_ring_probe.sh` output `== clock ==` (prints UTC + epoch + `timedatectl` fields when available).
- If skew is large, treat it as a blocker for distributed experiments (TP>1) until a human fixes time sync.

## 4) Address Matrix (Wired + Wi‑Fi + v4/v6)

Capture a non-secret identity snapshot suitable for commit:

- Mac-side interface + route snapshot:
  - `REDACT=1 DS4_GIT_DIR=.codex_git DS4_GIT_WORK_TREE=. ./scripts/mac_spark_discovery.sh aitopatom-9ab9.local spark1.local spark2.local`
- Per-node interface + address snapshot (redacted):
  - `SPARK_SSH_USER=spark0 REDACT=1 SPARK_KNOWN_HOSTS_PER_HOST=1 DS4_GIT_DIR=.codex_git DS4_GIT_WORK_TREE=. ./scripts/spark_ring_probe.sh aitopatom-9ab9.local spark1.local spark2.local || true`

Record (for each node):
- Primary SSH-reachable name (and whether it’s IPv4, IPv6 link-local, or routed v4).
- Wired interface name(s) and MTU (jumbo vs standard).
- Wi‑Fi interface name(s) and MTU.

Optional: write down the matrix (fill with redacted values as needed):

| Node | SSH target | SSH path | Wired ifname | Wired MTU | Wi‑Fi ifname | Wi‑Fi MTU | Notes |
|------|------------|----------|--------------|----------:|--------------|----------:|-------|
| spark0 | `aitopatom-9ab9.local` | `v6 link-local` / `v4` | `enP7s7` | `9000` | `wlP9s9` | `1500` | — |
| spark1 | `spark1.local` | `v6 link-local` / `v4` | — | — | — | — | not provisioned |
| spark2 | `spark2.local` | `v6 link-local` / `v4` | — | — | — | — | not provisioned |

## 5) MTU Consistency

- Ensure the intended fabric (wired vs Wi‑Fi) uses consistent MTU across nodes for tests that care about latency/bandwidth.
- The ring probe prints `ip -br link` which includes MTU; use it to spot mismatches quickly.
- Optional: validate MTU end-to-end with DF pings from each host to its peers:
  - `SPARK_SSH_USER=spark0 REDACT=1 SPARK_KNOWN_HOSTS_PER_HOST=1 DS4_GIT_DIR=.codex_git DS4_GIT_WORK_TREE=. ./scripts/spark_ring_probe_mtu.sh --topology full aitopatom-9ab9.local spark1.local spark2.local || true`
  - Override payload sizes (comma-separated, no spaces): `MTU_PAYLOADS=1472,8972`

## 6) Bandwidth/Latency (Safe, Non-Secret)

- Use ping RTT as the minimum viable latency check:
  - `./scripts/spark_ring_probe.sh` prints `== peer ping ==` results from each host to its neighbors (ring topology) or to all peers (`--topology full`), including packet loss and RTT summary when available.
- If you later add a bandwidth tool (e.g. `iperf3`) by human action, document it in a separate runbook; do not install packages from automation loops.

## 7) Safe GPU/Storage Metadata Capture

For each node, capture:
- GPU inventory (`nvidia-smi` CSV query output: GPU name, bus id, driver version, compute cap when available).
- Toolkit banner (`nvcc --version`) and `/usr/local/cuda/version.json` `cuda:` when present.
- Storage facts (`df -h` + `lsblk` model/size).

Use `REDACT=1` for any committed output.

## 8) Commit-Safe Redaction Rule

- Always generate snapshot docs with `REDACT=1`.
- Treat hostnames, OS/kernel/toolchain versions, GPU model names, disk model names, and interface names as non-secret.
- Treat IP addresses, MAC addresses, GPU UUID tokens, and any host keys as sensitive; the probe scripts redact them automatically when `REDACT=1`.
