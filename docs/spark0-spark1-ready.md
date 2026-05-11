# Spark0/Spark1 Probe Runbook

This is a lightweight, reproducible probe flow for Spark hosts.

## Current Status (2026-05-11)

- `aitopatom-9ab9.local` (Spark0) is reachable over SSH from the Mac.
- `spark1.local` and `spark2.local` are not reachable yet (as of the `2026-05-11T2326Z` refresh, both failed DNS resolution from the Mac probe environment; likely not provisioned / not on the same mDNS domain).
- Latest redacted Spark0 facts-only snapshot: `docs/spark0-probe-facts-2026-05-11T2326Z.md`.
- Latest ring snapshots: `docs/spark-ring-mac-discovery-2026-05-11T2326Z.md`, `docs/spark-ring-probe-2026-05-11T2326Z.md`.
- Latest ring bandwidth snapshot (Mac<->host, best-effort): `docs/spark-ring-bw-probe-2026-05-11T2326Z.md`.
- Latest ring MTU snapshot: `docs/spark-ring-mtu-probe-2026-05-11T2326Z.md`.
- Ring readiness tracker: `docs/spark-ring-readiness-status.md`.

## Goals

- Capture non-secret hardware + toolchain facts (CPU/RAM/storage/GPU/CUDA toolchain).
- Verify CUDA compute capability via multiple sources (`nvidia-smi` query + a tiny `nvcc` runtime probe).
- Keep committed artifacts safe: redact IP/MAC tokens.
- Preserve non-secret package/version facts while redacting network identifiers (the probe redaction avoids clobbering version strings like `0ubuntu0.24.04.1`).

## Spark2 / Ring Next Steps

When Spark2 exists (or you want to stage ring readiness), use:

- `docs/spark-ring-access-checklist.md`
- `docs/spark-ring-probe-runbook.md`

The compact ring probe (`scripts/spark_ring_probe.sh`) is meant to be commit-safe and tolerant of missing nodes (`|| true`).
For one-command, reproducible snapshot sets, use `scripts/spark_ring_probe_snapshots.sh`.

## Mac-Side Discovery

Use discovery first to confirm which `*.local` targets resolve and whether TCP/22 is reachable.

```bash
REDACT=1 DS4_GIT_DIR=.codex_git DS4_GIT_WORK_TREE=. ./scripts/mac_spark_discovery.sh aitopatom-9ab9.local spark1.local spark2.local
```

Omit args to use the default targets (Spark0 + Spark1/Spark2 placeholders).
The discovery output prints `targets:` so the exact target list is visible in committed excerpts.
The discovery output also attempts `route -n get <target>` per host, but in locked-down macOS probe environments this may print `route: socket: Operation not permitted`; treat it as best-effort.

If `spark1.local` does not resolve from the Mac yet, keep the probe flow the same but pass whatever Spark1 identifier you do have (a different mDNS name, a wired IPv4, or an IPv6 link-local) and let the scripts record the exact `resolved targets:` and reachability state in the redacted output.

## Spark Probe (Redacted)

Always use `REDACT=1` when saving output for commit.

```bash
SPARK_SSH_USER=spark0 REDACT=1 SPARK_KNOWN_HOSTS_PER_HOST=1 DS4_GIT_DIR=.codex_git DS4_GIT_WORK_TREE=. ./scripts/spark_probe.sh aitopatom-9ab9.local | tee /private/tmp/spark0-probe.txt
SPARK_SSH_USER=spark0 REDACT=1 SPARK_KNOWN_HOSTS_PER_HOST=1 DS4_GIT_DIR=.codex_git DS4_GIT_WORK_TREE=. ./scripts/spark_probe.sh spark1.local | tee /private/tmp/spark1-probe.txt
(SPARK_SSH_USER=spark0 REDACT=1 SPARK_PROBE_SUMMARY=1 SPARK_KNOWN_HOSTS_PER_HOST=1 DS4_GIT_DIR=.codex_git DS4_GIT_WORK_TREE=. ./scripts/spark_probe.sh aitopatom-9ab9.local spark1.local || true) | tee /private/tmp/spark01-probe-summary.txt
```

Optional toggles:

- Facts-only mode (smallest/stablest output; good for Spark1 bring-up checks):

```bash
SPARK_SSH_USER=spark0 REDACT=1 SPARK_PROBE_FACTS=1 SPARK_KNOWN_HOSTS_PER_HOST=1 DS4_GIT_DIR=.codex_git DS4_GIT_WORK_TREE=. ./scripts/spark_probe.sh spark1.local || true
```

Facts-only mode implies summary mode and trims variable runtime sections (GPU temperature/pstate, power draw/utilization, IP addr/routes, and disk usage) while keeping stable identity + CUDA/toolchain + GPU inventory + disk model/size facts.

- Summary mode (smaller output; useful for Spark1 smoke checks when it may be unreachable):

```bash
SPARK_SSH_USER=spark0 REDACT=1 SPARK_PROBE_SUMMARY=1 ./scripts/spark_probe.sh spark1.local || true
```

- Include full `nvidia-smi` output (verbose; includes process list + timestamps):

```bash
SPARK_SSH_USER=spark0 REDACT=1 NVIDIA_SMI_FULL=1 ./scripts/spark_probe.sh aitopatom-9ab9.local | tee /private/tmp/spark0-probe-verbose.txt
```

- Skip the `nvcc` runtime probe compile/run (when you only need the driver-side query):

```bash
SPARK_SSH_USER=spark0 REDACT=1 CUDA_RUNTIME_PROBE=0 ./scripts/spark_probe.sh aitopatom-9ab9.local
```

- Force the `nvcc` runtime probe compile arch (defaults to deriving from the max `nvidia-smi` compute capability when available):

```bash
SPARK_SSH_USER=spark0 REDACT=1 NVCC_ARCH=sm_121 ./scripts/spark_probe.sh aitopatom-9ab9.local
```

Notes:

- The probe writes SSH host keys to `SPARK_KNOWN_HOSTS` (default: `/private/tmp/ds4_spark_known_hosts`).
- When probing multiple Spark hosts, consider `SPARK_KNOWN_HOSTS_PER_HOST=1` so Spark0 and Spark1 keep separate known_hosts files.
- When multiple targets are provided, the probe prints `probe args:` plus `resolved targets:` and one `known_hosts:` line per target to make runs copy/paste reproducible.
- When multiple targets are provided, the probe continues even if a target is unreachable; it prints `ssh: failed rc=...` plus a `== probe summary ==` with `ssh failures: N`. The script exits non-zero if any target fails, so append `|| true` when you want to save partial output (e.g. Spark0 ok, Spark1 offline).
- When `SPARK_SSH_USER` is set, host-only args (like `spark1.local`) are rewritten into `user@host` targets and printed in `resolved targets:` so the actual SSH targets are visible in committed excerpts.
- The probe prints `ssh opts:` so SSH behavior is explicit in committed excerpts.
- The probe prints `selected compute_cap:` and `selected nvcc arch:` before the CUDA runtime probe section so the derived `-arch` choice is visible in committed excerpts.
- The probe prints `== cuda/toolchain facts (summary) ==` to consolidate the key version/arch facts into a single paste-friendly stanza.
- The probe prints `columns:` header lines for `nvidia-smi --query-gpu` CSV output so pasted excerpts are self-describing.
- The probe includes a small `nvcc` compile + run under `/tmp` and then deletes the temporary files.
- After the CUDA runtime probe runs, the probe prints a `post-load` PCIe link snapshot (both `nvidia-smi` query + sysfs cross-check) so we can see whether link speed/width changes under GPU activity.
- If the `nvcc -arch=...` runtime probe compile fails (unsupported arch), the probe retries once without `-arch` so the runtime can still report `device0 cc: ...`.
- The CUDA runtime probe prints both the raw `cuda*GetVersion()` integers and a `major.minor` parse to avoid ambiguity (e.g. `13000 (13.0)`).
- When `REDACT=1`, the probe scrubs GPU UUID tokens that can appear in `nvidia-smi -L` output.
- `NVCC_ARCH` is forwarded into the remote probe so overrides work when connecting over SSH.
- If the checkout `.git` metadata is unusable (macOS provenance/permission), the scripts also check for a local shim gitdir at `.codex_git/` or `.git-codex/` (bare gitdir) or `.codex_git/.git` / `.git-codex/.git` (non-bare `git init <dir>` layout), plus `.gitshim/repo/.git` (used by some probe automations). Otherwise, set `DS4_GIT_DIR=/path/to/.git` so probe artifacts include `git: <hash>`. If your `DS4_GIT_DIR` is not tied to the current working directory, also set `DS4_GIT_WORK_TREE=/path/to/worktree` (defaults to `$PWD`).
- For a copy/paste shim setup recipe, see `docs/spark-access.md` under “Git Shim For Read-Only Checkouts”.

## What To Record In `docs/spark0-*.md`

- `nvidia-smi` driver + CUDA version.
- `nvidia-smi` version banner (`nvidia-smi --version` / `nvidia-smi -V`) for NVML/driver/CUDA summary.
- `nvidia-smi` inventory line(s) (includes GPU `index` + `pci.bus_id`).
- `nvidia-smi -q` fabric/c2c hints when present (`Peer Type`, `GPU C2C Mode`), since these help interpret the GB10 "Gen1 x1" PCIe link fields.
- `nvidia-smi` PCIe link state (gen/width max/current) and power/clocks/utilization summary (when supported); capture both the initial and `post-load` link snapshots when diagnosing lane/speed issues.
- When available, also capture the optional `nvidia-smi --query-gpu=pcie.link.gen.gpucurrent,pcie.link.gen.gpumax,pcie.link.gen.hostmax,...` output printed by the probe; these fields tend to line up with `nvidia-smi -q` `GPU Link Info` (`Device Max`/`Host Max`) and help interpret surprising `pcie.link.gen.max` values.
- PCIe link state cross-check via sysfs (`/sys/bus/pci/devices/*/{current,max}_link_{speed,width}` + PCI IDs via `{vendor,device,subsystem_*}`), since `lspci -vv` capability fields can be restricted without root on some hosts; capture both the initial and `post-load` sysfs snapshots when present.
- CUDA compute capability (from `nvidia-smi` query and the `nvcc` runtime probe; plus `deviceQuery` when available). The runtime probe also prints `runtime max cc: ...` as a quick cross-check on multi-GPU hosts.
- `nvcc` path and version (toolkit version).
- `/usr/local/cuda/version.json` (when present) to capture toolkit component versions.
- `nvcc --list-gpu-arch` output (capped) to confirm supported SM targets (useful when `NVCC_ARCH=...` overrides fail).
- `nvcc --list-gpu-code` output (capped) to confirm supported `sm_###` code targets (useful when mapping `compute_cap` -> `NVCC_ARCH=sm_...`).
- `cuda.h` macros (`CUDA_VERSION` / `CUDART_VERSION`) to cross-check toolkit headers.
- Any `warning:` line emitted by the probe when `nvcc release` and `cuda.h` disagree.
- Any `note:` line emitted by the probe when `nvidia-smi` CUDA major differs from the `nvcc` toolkit major (driver vs toolkit).
- cuDNN presence/version when available (probe prints header macros + `ldconfig` hits).
- `nvidia-smi topo -m` (capped) + `modinfo nvidia` summary to capture GPU/driver topology and module version metadata.
- Numeric PCI IDs (`lspci -nn` + optional `nvidia-smi --query-gpu=pci.device_id,...`) to cross-check GPU/bridge identity without root.
- Storage summary (`df -h` + filesystem type/opts + `lsblk` disk model/size).
- Wired link status + speed when available (`ip link` + optional `ethtool` + `ethtool -i` driver/firmware).
- Capped CUDA/NVIDIA package inventory (`dpkg-query`), when available.
- RDMA/ROCE presence + port state summary (`/sys/class/infiniband` + optional `rdma link show`).
