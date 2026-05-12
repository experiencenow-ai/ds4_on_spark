# Spark Ring Readiness Status (Spark0..Spark2)

Status as of `2026-05-12T1801Z` (UTC).

## Latest commit-safe snapshots

- Mac discovery (mDNS + reachability): `docs/spark-ring-mac-discovery-2026-05-12T1801Z.md`
- Ring probe (clock + network + GPU/storage facts): `docs/spark-ring-probe-2026-05-12T1801Z.md`
- Ring MTU probe (DF ping payloads): `docs/spark-ring-mtu-probe-2026-05-12T1801Z.md`
- Ring bandwidth probe (Mac<->host, best-effort): `docs/spark-ring-bw-probe-2026-05-12T1801Z.md`
- Spark0 facts-only probe (refreshed): `docs/spark0-probe-facts-2026-05-12T1801Z.md`
- Per-node facts-only probes:
  - `docs/spark-ring-node-facts-aitopatom-9ab9.local-2026-05-12T1801Z.md`
  - `docs/spark-ring-node-facts-spark1.local-2026-05-12T1801Z.md`
  - `docs/spark-ring-node-facts-spark2.local-2026-05-12T1801Z.md`

## Snapshot command (commit-safe)

```bash
stamp="2026-05-12T1801Z"
REDACT=1 SPARK_NODE_FACTS=1 SPARK_KNOWN_HOSTS_PER_HOST=1 DS4_GIT_DIR=.codex_git DS4_GIT_WORK_TREE=. ./scripts/spark_ring_probe_snapshots.sh --stamp "$stamp" --topology full spark0@aitopatom-9ab9.local spark1@spark1.local spark2@spark2.local
```

## Ring readiness matrix

| Item | Spark0 (`aitopatom-9ab9.local`) | Spark1 (`spark1.local`) | Spark2 (`spark2.local`) |
|------|----------------------------------|--------------------------|--------------------------|
| Name resolves from Mac | OK | blocked (DNS fail) | blocked (DNS fail) |
| SSH key auth from Mac | OK | blocked (unreachable) | blocked (unreachable) |
| Clock sane + NTP sync | OK (`NTPSynchronized=yes`) | unknown | unknown |
| Address matrix captured | OK (redacted) | missing | missing |
| MTU captured | OK (wired `9000`, wifi `1500`) | missing | missing |
| Mac ping RTT/loss (ICMP) | OK (0% loss in latest mac discovery snapshot) | blocked (DNS fail) | blocked (DNS fail) |
| Peer ping RTT/loss | partial (peers unresolved) | missing | missing |
| Bandwidth smoke test | OK (Mac<->Spark0) | missing | missing |
| GPU + CUDA facts captured | OK (GB10, `compute_cap=12.1`, `nvcc 13.0.88`, `cuda 13.0.3`; PCIe link fields show Gen1 x1 but `-q` shows Gen5 x16 max) | missing | missing |
| Storage facts captured | OK (redacted) | missing | missing |

## When Spark1/Spark2 appear (minimum next actions)

From the Mac repo root:

```bash
stamp="$(date -u +%Y-%m-%dT%H%MZ)"
REDACT=1 SPARK_KNOWN_HOSTS_PER_HOST=1 DS4_GIT_DIR=.codex_git DS4_GIT_WORK_TREE=. ./scripts/spark_ring_probe_snapshots.sh --stamp "$stamp" spark0@aitopatom-9ab9.local spark1@spark1.local spark2@spark2.local
```

Then refresh MTU + bandwidth snapshots if needed:

```bash
(SPARK_SSH_USER=spark0 REDACT=1 SPARK_KNOWN_HOSTS_PER_HOST=1 DS4_GIT_DIR=.codex_git DS4_GIT_WORK_TREE=. ./scripts/spark_ring_probe_mtu.sh --topology full aitopatom-9ab9.local spark1.local spark2.local || true) > "docs/spark-ring-mtu-probe-${stamp}.md"
(BW_MB=16 SPARK_SSH_USER=spark0 REDACT=1 SPARK_KNOWN_HOSTS_PER_HOST=1 DS4_GIT_DIR=.codex_git DS4_GIT_WORK_TREE=. ./scripts/spark_ring_probe_bw.sh aitopatom-9ab9.local spark1.local spark2.local || true) > "docs/spark-ring-bw-probe-${stamp}.md"
```

Always use `REDACT=1` for committed snapshots.
