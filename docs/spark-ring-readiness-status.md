# Spark Ring Readiness Status (Spark0..Spark2)

Status as of `2026-05-11T2024Z` (UTC).

## Latest commit-safe snapshots

- Mac discovery (mDNS + reachability): `docs/spark-ring-mac-discovery-2026-05-11T2024Z.md`
- Ring probe (clock + network + GPU/storage facts): `docs/spark-ring-probe-2026-05-11T2024Z.md`
- Ring MTU probe (DF ping payloads): `docs/spark-ring-mtu-probe-2026-05-11T2024Z.md`
- Ring bandwidth probe (Mac<->host, best-effort): `docs/spark-ring-bw-probe-2026-05-11T2024Z.md`
- Spark0 facts-only probe: `docs/spark0-probe-facts-2026-05-11T2024Z.md`

## Ring readiness matrix

| Item | Spark0 (`aitopatom-9ab9.local`) | Spark1 (`spark1.local`) | Spark2 (`spark2.local`) |
|------|----------------------------------|--------------------------|--------------------------|
| Name resolves from Mac | OK | blocked (DNS fail) | blocked (DNS fail) |
| SSH key auth from Mac | OK | blocked (unreachable) | blocked (unreachable) |
| Clock sane + NTP sync | OK (`NTPSynchronized=yes`) | unknown | unknown |
| Address matrix captured | OK (redacted) | missing | missing |
| MTU captured | OK (wired `9000`, wifi `1500`) | missing | missing |
| Peer ping RTT/loss | partial (peers unresolved) | missing | missing |
| Bandwidth smoke test | OK (Mac<->Spark0) | missing | missing |
| GPU + CUDA facts captured | OK (GB10, `compute_cap=12.1`) | missing | missing |
| Storage facts captured | OK (redacted) | missing | missing |

## When Spark1/Spark2 appear (minimum next actions)

From the Mac repo root:

```bash
stamp="$(date -u +%Y-%m-%dT%H%MZ)"
REDACT=1 DS4_GIT_DIR=.codex_git DS4_GIT_WORK_TREE=. ./scripts/mac_spark_discovery.sh aitopatom-9ab9.local spark1.local spark2.local > "docs/spark-ring-mac-discovery-${stamp}.md"
(SPARK_SSH_USER=spark0 REDACT=1 SPARK_KNOWN_HOSTS_PER_HOST=1 DS4_GIT_DIR=.codex_git DS4_GIT_WORK_TREE=. ./scripts/spark_ring_probe.sh aitopatom-9ab9.local spark1.local spark2.local || true) > "docs/spark-ring-probe-${stamp}.md"
(SPARK_SSH_USER=spark0 REDACT=1 SPARK_PROBE_FACTS=1 SPARK_KNOWN_HOSTS_PER_HOST=1 DS4_GIT_DIR=.codex_git DS4_GIT_WORK_TREE=. ./scripts/spark_probe.sh spark1.local || true) > "docs/spark-ring-spark1-probe-facts-${stamp}.md"
(SPARK_SSH_USER=spark0 REDACT=1 SPARK_PROBE_FACTS=1 SPARK_KNOWN_HOSTS_PER_HOST=1 DS4_GIT_DIR=.codex_git DS4_GIT_WORK_TREE=. ./scripts/spark_probe.sh spark2.local || true) > "docs/spark-ring-spark2-probe-facts-${stamp}.md"
```

Then refresh MTU + bandwidth snapshots if needed:

```bash
(SPARK_SSH_USER=spark0 REDACT=1 SPARK_KNOWN_HOSTS_PER_HOST=1 DS4_GIT_DIR=.codex_git DS4_GIT_WORK_TREE=. ./scripts/spark_ring_probe_mtu.sh --topology full aitopatom-9ab9.local spark1.local spark2.local || true) > "docs/spark-ring-mtu-probe-${stamp}.md"
(BW_MB=16 SPARK_SSH_USER=spark0 REDACT=1 SPARK_KNOWN_HOSTS_PER_HOST=1 DS4_GIT_DIR=.codex_git DS4_GIT_WORK_TREE=. ./scripts/spark_ring_probe_bw.sh aitopatom-9ab9.local spark1.local spark2.local || true) > "docs/spark-ring-bw-probe-${stamp}.md"
```

Always use `REDACT=1` for committed snapshots.
