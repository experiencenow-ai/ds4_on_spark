# Spark Ring Access Checklist (Spark0–Spark3)

This checklist defines the minimum “ring-ready” state for a four-node Spark ring (Spark0/Spark1/Spark2/Spark3) from a Mac control plane.

Goals:

- Reproducible, non-destructive validation steps.
- Non-secret metadata capture suitable for commit (use `REDACT=1`).
- A clear path to expand from Spark0-only to Spark0–Spark3.

## Definitions

- **Mac control plane**: the laptop/workstation used to reach the Spark hosts over SSH.
- **Ring**: four Spark hosts reachable by stable hostnames (mDNS `*.local` or static DNS) with working SSH key auth.
- **Non-secret**: hardware/toolchain identity facts, interface names, MTU, disk model + size, GPU name + compute capability, driver/toolkit versions. Avoid serial numbers, raw MAC/IPs, and private keys.

## 1) Hostnames + identity

- Decide canonical names for the four nodes (example):
  - Spark0: `aitopatom-9ab9.local`
  - Spark1: `spark1.local`
  - Spark2: `spark2.local`
  - Spark3: `spark3.local`
- From the Mac, validate name resolution and TCP/22 reachability:

```bash
REDACT=1 DS4_GIT_DIR=.codex_git DS4_GIT_WORK_TREE=. ./scripts/mac_spark_discovery.sh aitopatom-9ab9.local spark1.local spark2.local spark3.local
```

## 2) SSH keys + host key hygiene

- Ensure Mac→each Spark host SSH key auth works (no password prompts).
- Keep reproducible known_hosts state by using per-host known_hosts files:

```bash
SPARK_KNOWN_HOSTS_PER_HOST=1 SPARK_SSH_USER=spark0 ssh spark0@aitopatom-9ab9.local hostname
```

Notes:

- Prefer `SPARK_KNOWN_HOSTS_PER_HOST=1` to avoid cross-host key collisions when new nodes appear/reimage.
- Do not commit private keys or unredacted `known_hosts` contents.

## 3) Clock sync (ring-wide)

Minimum requirement:

- Each host reports NTP synchronized (`timedatectl status`) and has bounded drift vs. the others.

Record:

- `timedatectl status` (selected lines)
- `chronyc tracking` when present
- `date +%s` epoch per host (for a quick skew estimate)

The ring probe script records these fields for each host.

## 4) Ethernet/Wi‑Fi address matrix (redacted for commits)

For each host, capture:

- Interface names (`ip -br link`)
- Address families present (`ip -br addr`)
- MTU per interface

Commit policy:

- For repo artifacts, use `REDACT=1` so raw IP/MAC tokens are replaced with `<redacted-ipv4>`, `<redacted-ipv6>`, `<redacted-mac>`.
- Maintain the full, unredacted address matrix out-of-repo (private doc) if needed.

## 5) MTU consistency

Minimum requirement:

- The intended “fast path” interconnect (typically wired Ethernet) uses a consistent MTU across the ring (often `9000`).

Record:

- `ip -o link` MTU summary per host
- Any downed links or mismatched MTUs

## 6) Latency/bandwidth sanity

Latency (safe default):

- From each host, `ping` the other hostnames. Failures are acceptable during bring-up but must be tracked.

Bandwidth (optional, only if preinstalled and approved):

- Use `iperf3` for a short run (5–10s) on a non-privileged port, and stop cleanly.
- Avoid installing packages during the automation loop unless explicitly requested.

## 7) Safe GPU + storage metadata capture

Minimum ring-ready inventory (per host):

- GPU: name, compute capability, PCI bus id, driver version
- CUDA toolkit: `nvcc --version` and runtime probe facts (via `scripts/spark_probe.sh`)
- Storage: `lsblk` model + size (no serials)

## 8) Canonical probe commands (commit-safe)

Ring-wide compact probe:

```bash
(SPARK_SSH_USER=spark0 REDACT=1 SPARK_KNOWN_HOSTS_PER_HOST=1 ./scripts/spark_ring_probe.sh aitopatom-9ab9.local spark1.local spark2.local spark3.local || true) | tee /private/tmp/ds4_spark_ring_probe_redacted.txt
```

Per-host deep probe (CUDA/toolchain/storage/network):

```bash
SPARK_SSH_USER=spark0 REDACT=1 SPARK_KNOWN_HOSTS_PER_HOST=1 ./scripts/spark_probe.sh aitopatom-9ab9.local | tee /private/tmp/ds4_spark0_probe_redacted.txt
```

## 9) Ring readiness status template

Track ring readiness as:

- Spark0: reachable? keys ok? clock ok? MTU ok? GPU/toolchain recorded?
- Spark1: reachable? keys ok? clock ok? MTU ok? GPU/toolchain recorded?
- Spark2: reachable? keys ok? clock ok? MTU ok? GPU/toolchain recorded?
- Spark3: reachable? keys ok? clock ok? MTU ok? GPU/toolchain recorded?

