# Spark Ring Node Bring-up (Spark1/Spark2 Ready)

This is a **human-run** checklist to add a new Spark node to the ring in a probe-friendly way (safe, commit-safe snapshots; no `sudo`; no package installs).

Use `REDACT=1` for any output you plan to commit.

## 0) Decide identity + SSH user

- Pick the node’s stable name:
  - Preferred: `sparkN.local` via mDNS (`avahi`/Bonjour) or pinned `/etc/hosts` (human-run).
- Decide the SSH user per node:
  - If users differ across nodes, always use explicit `user@host` targets in probe scripts.

Example target set:

```bash
spark0@aitopatom-9ab9.local spark1@spark1.local spark2@spark2.local
```

## 1) Mac-side preflight (resolution + port 22 + ping)

From repo root on the Mac:

```bash
REDACT=1 DS4_GIT_DIR=.codex_git DS4_GIT_WORK_TREE=. ./scripts/mac_spark_discovery.sh spark1.local
```

Bring-up blockers:
- `dns-sd` cannot resolve the name.
- TCP/22 is unreachable.

## 2) SSH key auth (non-interactive) + probe-scoped known_hosts

Do not store host keys in `~/.ssh/known_hosts`. Prefer probe-scoped files under `/private/tmp`.

```bash
SPARK_KNOWN_HOSTS_PER_HOST=1 ssh -o BatchMode=yes -o ConnectTimeout=10 -o StrictHostKeyChecking=accept-new -o UserKnownHostsFile=/private/tmp/ds4_spark_known_hosts.spark1.local spark1@spark1.local 'hostname'
```

Bring-up blockers:
- `BatchMode=yes` fails (password prompt / missing key).
- `auth_failed` in probe output.

## 3) Clock sanity (UTC + skew + NTP state)

Once SSH works, capture the clock section using the ring probe (commit-safe when `REDACT=1`):

```bash
(REDACT=1 SPARK_KNOWN_HOSTS_PER_HOST=1 DS4_GIT_DIR=.codex_git DS4_GIT_WORK_TREE=. ./scripts/spark_ring_probe.sh spark1@spark1.local || true) | sed -n '1,120p'
```

Bring-up blocker:
- `skew_s (remote-local)` outside roughly `±1s` for multi-node experiments.

## 4) Capture a per-node facts snapshot (GPU/CUDA/toolchain/storage)

Facts-only is the most stable output for a fresh node:

```bash
stamp="$(date -u +%Y-%m-%dT%H%MZ)"
REDACT=1 SPARK_KNOWN_HOSTS_PER_HOST=1 DS4_GIT_DIR=.codex_git DS4_GIT_WORK_TREE=. ./scripts/spark_ring_probe_facts.sh --stamp "$stamp" spark1@spark1.local
```

This writes:
- `docs/spark-ring-node-facts-spark1.local-<stamp>.md`

Notes:
- If you re-run with the same `--stamp`, the scripts now fail fast unless `ALLOW_OVERWRITE=1`.
- Prefer using a fresh stamp per run instead of overwriting.

## 4b) Capture address matrix + MTU + latency/bandwidth (commit-safe)

Once SSH works, use the ring probe output as the “address matrix” record for the node (wired + Wi‑Fi, v4/v6, MTU, negotiated link speed):

- `docs/spark-ring-probe-<stamp>.md`: `== network (iface matrix, compact) ==` and `== network (mtu, compact) ==`
- `docs/spark-ring-probe-<stamp>.md`: `== peer ping (best effort, rtt) ==` (node→peers, when peers resolve)
- `docs/spark-ring-mac-discovery-<stamp>.md`: `== ping (mac->targets, compact) ==` (Mac→node RTT/loss)

Optional (best-effort) Mac↔node throughput smoke test (no installs; keep `BW_MB` small):

```bash
stamp="$(date -u +%Y-%m-%dT%H%MZ)"
(BW_MB=16 SPARK_KNOWN_HOSTS_PER_HOST=1 REDACT=1 DS4_GIT_DIR=.codex_git DS4_GIT_WORK_TREE=. ./scripts/spark_ring_probe_bw.sh spark1@spark1.local || true) > "docs/spark-ring-bw-probe-${stamp}.md"
```

## 5) When Spark1 + Spark2 are both reachable: one-shot ring snapshot set

From repo root on the Mac:

```bash
stamp="$(date -u +%Y-%m-%dT%H%MZ)"
REDACT=1 SPARK_NODE_FACTS=1 SPARK_KNOWN_HOSTS_PER_HOST=1 DS4_GIT_DIR=.codex_git DS4_GIT_WORK_TREE=. ./scripts/spark_ring_probe_snapshots.sh --stamp "$stamp" spark0@aitopatom-9ab9.local spark1@spark1.local spark2@spark2.local
```

This produces a full commit-safe snapshot set plus per-node facts, which is the easiest way to update:
- `docs/spark-ring-readiness-status.md`
- `docs/spark-ring-access-checklist.md`

## 6) What to record (non-secret)

- Hostname + kernel/OS + CPU summary.
- Interface names + MTU + negotiated link speed (wired + Wi‑Fi).
- Ping RTT/loss (Mac→node and node→peers).
- GPU inventory + CUDA driver/toolkit versions + compute capability.
- Storage model/size + free space (`lsblk`, `df -h`).
