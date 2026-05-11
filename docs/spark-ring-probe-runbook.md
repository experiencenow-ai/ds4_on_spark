# Spark Ring Probe Runbook (Spark0–Spark3)

This runbook extends the Spark0/Spark1 probe flow to a four-node ring. It is designed to be reproducible and safe-to-commit (use `REDACT=1`).

## 1) Mac-side discovery first

```bash
REDACT=1 DS4_GIT_DIR=.codex_git DS4_GIT_WORK_TREE=. ./scripts/mac_spark_discovery.sh aitopatom-9ab9.local spark1.local spark2.local spark3.local
```

If a target does not resolve (common during bring-up), replace it with the identifier you do have (wired IPv4, IPv6 link-local, or a different mDNS name). Keep the exact identifiers in the command line so committed excerpts remain reproducible.

## 2) Ring-wide compact probe

This collects ring-focused facts: identity, clock sync hints, interface/MTU summaries, disk model+size, and GPU name/compute capability.

```bash
(SPARK_SSH_USER=spark0 REDACT=1 SPARK_KNOWN_HOSTS_PER_HOST=1 ./scripts/spark_ring_probe.sh aitopatom-9ab9.local spark1.local spark2.local spark3.local || true) | tee /private/tmp/ds4_spark_ring_probe_redacted.txt
```

Optional: enable a best-effort ICMP matrix from each host to every other host (useful to confirm intra-ring name resolution and basic connectivity):

```bash
(SPARK_SSH_USER=spark0 REDACT=1 SPARK_KNOWN_HOSTS_PER_HOST=1 SPARK_RING_PING_MATRIX=1 ./scripts/spark_ring_probe.sh aitopatom-9ab9.local spark1.local spark2.local spark3.local || true) | tee /private/tmp/ds4_spark_ring_probe_ping_redacted.txt
```

## 3) Per-host deep probe (CUDA/toolchain)

Use `scripts/spark_probe.sh` per host once SSH is working. This captures CUDA compute capability and toolchain facts via multiple sources (`nvidia-smi` query + a tiny `nvcc` runtime probe), plus storage and network metadata.

```bash
SPARK_SSH_USER=spark0 REDACT=1 SPARK_KNOWN_HOSTS_PER_HOST=1 ./scripts/spark_probe.sh aitopatom-9ab9.local | tee /private/tmp/ds4_spark0_probe_redacted.txt
SPARK_SSH_USER=spark0 REDACT=1 SPARK_KNOWN_HOSTS_PER_HOST=1 ./scripts/spark_probe.sh spark1.local || true
SPARK_SSH_USER=spark0 REDACT=1 SPARK_KNOWN_HOSTS_PER_HOST=1 ./scripts/spark_probe.sh spark2.local || true
SPARK_SSH_USER=spark0 REDACT=1 SPARK_KNOWN_HOSTS_PER_HOST=1 ./scripts/spark_probe.sh spark3.local || true
```

For bring-up (when nodes are flaky/unreachable), prefer facts-only mode:

```bash
SPARK_SSH_USER=spark0 REDACT=1 SPARK_PROBE_FACTS=1 SPARK_KNOWN_HOSTS_PER_HOST=1 ./scripts/spark_probe.sh spark1.local || true
```

## 4) What to commit

Commit only redacted excerpts:

- `docs/spark0-*.md` / `docs/spark1-*.md` / `docs/spark2-*.md` / `docs/spark3-*.md` snapshots (use `REDACT=1` outputs).
- Ring readiness notes (this file + `docs/spark-ring-access-checklist.md`).

Do not commit:

- Private keys.
- Unredacted IP/MAC matrices.
- Raw `known_hosts` contents.

