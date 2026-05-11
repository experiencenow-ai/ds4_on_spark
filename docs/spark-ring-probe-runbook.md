# Spark Ring Probe Runbook (Spark0..Spark2)

This runbook produces **commit-safe** (redacted) snapshots for ring bring-up. It is designed to work even when some hosts are missing/unreachable.

## Pre-reqs (Mac)

- Use the repo root as the working directory.
- If the automation checkout `.git` is read-only, use the shim described in `docs/spark-access.md`:
  - `DS4_GIT_DIR=.codex_git DS4_GIT_WORK_TREE=.` (preferred)
- Do not write Spark host keys into `~/.ssh/known_hosts`:
  - Prefer `SPARK_KNOWN_HOSTS_PER_HOST=1` (per-target files under `/private/tmp`).

## 1) Mac-side discovery snapshot

```bash
stamp="$(date -u +%Y-%m-%dT%H%MZ)"
REDACT=1 DS4_GIT_DIR=.codex_git DS4_GIT_WORK_TREE=. ./scripts/mac_spark_discovery.sh aitopatom-9ab9.local spark1.local spark2.local > "docs/spark-ring-mac-discovery-${stamp}.md"
```

This captures:
- Mac interface IPv4/IPv6 (no MACs)
- mDNS `_ssh._tcp` browse
- per-target `dns-sd -G` resolution (best-effort)
- TCP/22 reachability checks

## 2) Ring probe snapshot (per-node identity + clock + network + GPU/storage facts)

```bash
stamp="$(date -u +%Y-%m-%dT%H%MZ)"
(SPARK_SSH_USER=spark0 REDACT=1 SPARK_KNOWN_HOSTS_PER_HOST=1 DS4_GIT_DIR=.codex_git DS4_GIT_WORK_TREE=. ./scripts/spark_ring_probe.sh aitopatom-9ab9.local spark1.local spark2.local || true) > "docs/spark-ring-probe-${stamp}.md"
```

If you want each host to ping **all** peers instead of only ring neighbors:

```bash
(SPARK_SSH_USER=spark0 REDACT=1 SPARK_KNOWN_HOSTS_PER_HOST=1 DS4_GIT_DIR=.codex_git DS4_GIT_WORK_TREE=. ./scripts/spark_ring_probe.sh --topology full aitopatom-9ab9.local spark1.local spark2.local || true) > "docs/spark-ring-probe-${stamp}.md"
```

Notes:
- The ring probe exits non-zero if any SSH target fails; keep `|| true` when capturing partial state.
- The output includes `known_hosts:` mapping for reproducibility.
- The `== peer ping ==` section includes packet loss and RTT summary when available.

## 2b) MTU probe snapshot (optional; DF jumbo payload test)

When you need a quick end-to-end MTU sanity check (without installing tools):

```bash
stamp="$(date -u +%Y-%m-%dT%H%MZ)"
(SPARK_SSH_USER=spark0 REDACT=1 SPARK_KNOWN_HOSTS_PER_HOST=1 DS4_GIT_DIR=.codex_git DS4_GIT_WORK_TREE=. ./scripts/spark_ring_probe_mtu.sh --topology full aitopatom-9ab9.local spark1.local spark2.local || true) > "docs/spark-ring-mtu-probe-${stamp}.md"
```

## 3) Deep single-node hardware/toolchain probe (optional; Spark0 recommended)

When you need CUDA compute capability cross-checks and PCIe link detail, record a full per-host probe:

```bash
stamp="$(date -u +%Y-%m-%dT%H%MZ)"
SPARK_SSH_USER=spark0 REDACT=1 SPARK_KNOWN_HOSTS_PER_HOST=1 DS4_GIT_DIR=.codex_git DS4_GIT_WORK_TREE=. ./scripts/spark_probe.sh aitopatom-9ab9.local > "docs/spark0-probe-${stamp}.md"
```

To keep output compact for a flaky new node:

```bash
SPARK_SSH_USER=spark0 REDACT=1 SPARK_PROBE_FACTS=1 SPARK_KNOWN_HOSTS_PER_HOST=1 DS4_GIT_DIR=.codex_git DS4_GIT_WORK_TREE=. ./scripts/spark_probe.sh spark1.local || true
```

## 4) Spark ring readiness status (what “good” looks like)

Minimum “ready for multi-node bring-up” bar:
- All intended hostnames resolve consistently from the Mac.
- SSH key auth works non-interactively for all nodes.
- Node clocks are sane (UTC close; `NTPSynchronized=yes` when available).
- MTU is consistent on the intended fabric (wired vs Wi‑Fi).
- Ping is successful for the intended topology (ring neighbors or full mesh).
- GPU inventory and CUDA toolkit facts are captured per node (commit-safe redacted output).
