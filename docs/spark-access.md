# Spark Access Notes

Current observed Spark identity:

- Hostname: `aitopatom-9ab9.local`
- SSH service: advertised via Bonjour as `aitopatom-9ab9 SSH`
- SSH port: reachable on port 22
- Link-local IPv6: reachable through the Mac wired interface
- Spark wired IPv4: configured by user as `<redacted-ipv4>`
- Mac wired IPv4 observed during bootstrap: `<redacted-ipv4>/16`
- Mac Wi-Fi IPv4 observed during bootstrap: `<redacted-ipv4>/24`
- Spark Wi-Fi IPv4 observed during probe: `<redacted-ipv4>/24`
- Spark wired interface: `enP7s7`, MTU 9000
- SSH key authentication from the Mac is now working for `spark0`.

## Reproducible Probes

From the Mac repo root, use the scripts in `scripts/` to keep probes consistent and safe-to-commit.

Notes:

- These scripts write SSH host key state to `SPARK_KNOWN_HOSTS` (default: `/private/tmp/ds4_spark_known_hosts`, not `~/.ssh/known_hosts`) to avoid macOS permission/provenance issues and to keep probe runs reproducible.
- When probing multiple Spark hosts (Spark0/Spark1), set `SPARK_KNOWN_HOSTS_PER_HOST=1` (or set `SPARK_KNOWN_HOSTS` explicitly) to keep host keys isolated per target.
- When multiple targets are passed to `scripts/spark_probe.sh`, the probe prints `probe args:` plus `resolved targets:` and one `known_hosts:` line per target so runs can be reproduced exactly.
- When multiple targets are passed to `scripts/spark_probe.sh`, the probe continues even if a target is unreachable; it prints `ssh: failed rc=...` plus a `== probe summary ==` with `ssh failures: N`. The script exits non-zero if any target fails, so append `|| true` when you want to save partial output (e.g. Spark0 ok, Spark1 offline).
- The Spark probe prints `ssh opts:` so SSH behavior is explicit in committed excerpts.
- Use `REDACT=1` for any output you plan to commit.
- `REDACT=1` redaction is delimiter-aware (it will redact actual IP addresses without clobbering non-secret version strings like `0ubuntu0.24.04.1`), and includes both expanded and compressed (`::`) IPv6 forms.
- Both scripts print the current git short hash when run inside a git worktree, to make snapshots traceable to a specific script version.
- `scripts/mac_spark_discovery.sh` prints `targets:` so default/explicit targets are visible in committed excerpts.
- If the checkout's `.git` metadata is not usable (provenance/permission issues), the scripts also check for a local shim gitdir at `.git-codex/` (used by some automation runners) and `.gitshim/repo/.git` (used by some probe automations). If either exists, set `DS4_GIT_DIR`/`DS4_GIT_WORK_TREE` explicitly so snapshots capture the correct `git: <hash>`. Otherwise, set `DS4_GIT_DIR=/path/to/.git` so the scripts can still print the correct `git: <hash>` for the scripts you are running. If your `DS4_GIT_DIR` is not tied to the current working directory, also set `DS4_GIT_WORK_TREE=/path/to/worktree` (defaults to `$PWD`).
- `scripts/spark_probe.sh` optional toggles:
  - `NVIDIA_SMI_FULL=1` include full `nvidia-smi` output (verbose, process list)
  - `CUDA_RUNTIME_PROBE=0` skip the tiny `nvcc` compile+run probe
  - `PYTORCH_PROBE=1` attempt a `python3` torch probe (usually absent)
  - `NVCC_ARCH=sm_121` force the `nvcc` runtime probe to compile for a specific GPU arch (forwarded into the remote probe; defaults to deriving from the max `nvidia-smi` compute capability when available)
- `scripts/spark_probe.sh` includes cuDNN hints (header macros when present + `ldconfig` library hits) to confirm whether cuDNN is installed.
- `scripts/spark_probe.sh` also captures `nvidia-smi --version` / `nvidia-smi -V` output (driver/NVML/CUDA banner), `lspci -vv` GPU link state (capped; `LnkCap/LnkSta` when available, otherwise it records that the fields appear restricted), `nvcc --list-gpu-arch` output (capped) to show supported SM targets, `nvidia-smi topo -m` (capped), PCIe link state (gen/width max/current) via `nvidia-smi --query-gpu=...` plus a sysfs cross-check (link state + PCI vendor/device IDs: `/sys/bus/pci/devices/*/{current,max}_link_{speed,width}` + `{vendor,device,subsystem_*}`), a power/clocks/utilization summary (via `nvidia-smi --query-gpu=...`), kernel module/version hints (`lsmod`, `modinfo nvidia`), CUDA header macros (`cuda.h`), a capped `dpkg-query` CUDA/NVIDIA package list, and a lightweight RDMA/ROCE summary (`/sys/class/infiniband` + `rdma link show`) to cross-check driver/toolkit/network facts. It also captures numeric PCI IDs via `lspci -nn` and attempts an `nvidia-smi --query-gpu=pci.device_id,...` snapshot when supported. After the CUDA runtime probe runs, it emits a second PCIe link snapshot labeled `post-load` to check whether link speed/width changes under GPU activity. When `nvidia-smi --query-gpu=pcie.link.*` appears to underreport `max` relative to `nvidia-smi -q` `GPU Link Info` (`Device Max`/`Host Max`), it emits a `warning:` to flag the mismatch. The runtime probe prints both the raw `cuda*GetVersion()` integers and a `major.minor` parse to avoid ambiguity. It emits a `warning:` when the parsed `nvcc release` disagrees with `cuda.h` `CUDA_VERSION`, and may emit a `note:` when `nvidia-smi`'s CUDA major differs from the `nvcc` toolkit major (driver vs toolkit). If the `nvcc -arch=...` runtime probe compile fails (unsupported arch), it retries once without `-arch` as a fallback.
- The sysfs PCIe cross-check includes the resolved sysfs path and a PCIe device path chain (e.g., root port -> endpoint). When the relevant `current_link_*` and `max_link_*` sysfs fields exist on upstream devices, those are printed as `path ...` lines to help diagnose link downtraining without `sudo`. When permitted, the probe also attempts to print `lspci -vv` link capability/state lines for each `path ...` chain element.
- The Spark probe also emits a capped `nvidia-smi -q` PCI section (`nvidia-smi -q pci link`) so the output includes `GPU Link Info` fields like `Device Max` / `Host Max` alongside the negotiated `Current` link state (useful when `nvidia-smi --query-gpu=pcie.link.*` reports surprising `max` values).
- The Spark probe prints both `selected compute_cap:` and `selected nvcc arch:` so `NVCC_ARCH` selection is explicit in committed excerpts.
- The Spark probe prints `columns:` header lines for `nvidia-smi --query-gpu` CSV output so pasted excerpts are self-describing.

### Mac-side Discovery (mDNS + reachability)

```bash
REDACT=1 ./scripts/mac_spark_discovery.sh
```

Default targets (when no args are provided): `aitopatom-9ab9.local` and `spark1.local`.
Pass additional hostnames/IPs explicitly if you need extra checks.
Targets may also be passed as `user@host`; the script strips the `user@` prefix for mDNS resolution and TCP reachability checks.

This prints:

- IPv4/IPv6 addresses for `en0`/`en1` (no MAC addresses)
- `_ssh._tcp` browse results (mDNS instance names)
- Quick SSH port checks against known targets
- Optional mDNS resolution output for `*.local` targets

### Spark Hardware + Toolchain Probe

```bash
SPARK_SSH_USER=spark0 REDACT=1 ./scripts/spark_probe.sh aitopatom-9ab9.local | tee /private/tmp/spark0-probe.txt
```

The probe is designed to capture non-secret OS/CPU/GPU/network/storage data without emitting host keys. Use `REDACT=1` when saving output for commit; the redacted snapshot is suitable to paste into `docs/spark0-*.md`.
If the driver-side `nvidia-smi` compute capability query is unavailable, the `nvcc` runtime probe is the fallback source for compute capability (`device0 cc:`).
When `REDACT=1`, the probe also scrubs GPU UUID tokens that can appear in `nvidia-smi -L` output.
The `nvidia-smi` inventory section includes per-GPU `index` and `pci.bus_id` to make multi-GPU hosts easier to compare across reboots.

## Spark1 Ready Checklist

When Spark1 exists (or a second Spark is provisioned), the same scripts should work with a new target:

```bash
REDACT=1 ./scripts/mac_spark_discovery.sh spark1.local
SPARK_SSH_USER=spark0 REDACT=1 ./scripts/spark_probe.sh spark1.local
```

If Spark1 uses a different login user or mDNS name, pass `user@host` explicitly.

## Diagnosis

`ssh spark0@aitopatom-9ab9.local` reaches the Spark SSH server.

Direct `ssh spark0@<spark-wired-ipv4>` times out from the Mac because the Mac wired port
is not currently in the Spark wired subnet. The hostname works because macOS resolves a
reachable link-local address.

Account authentication is now fixed. The Mac public key is installed in
`~spark0/.ssh/authorized_keys`.

## If Account Auth Needs Reset Again

On the Spark local console, reset the account password and reinstall the Mac key.

```bash
sudo passwd spark0
mkdir -p ~spark0/.ssh
sudo chown spark0:spark0 ~spark0/.ssh
sudo chmod 700 ~spark0/.ssh
```

Then from the Mac:

```bash
cat ~/.ssh/id_rsa.pub | ssh spark0@aitopatom-9ab9.local 'mkdir -p ~/.ssh && chmod 700 ~/.ssh && cat >> ~/.ssh/authorized_keys && chmod 600 ~/.ssh/authorized_keys'
ssh spark0@aitopatom-9ab9.local hostname
```

## Optional Wired IPv4 Alias On Mac

To make the Spark wired IPv4 reachable directly from the Mac wired port:

```bash
sudo ifconfig en0 inet <mac-wired-ipv4> netmask 255.255.255.0 alias
ping <spark-wired-ipv4>
ssh spark0@<spark-wired-ipv4> hostname
```

Use the hostname path until the alias is needed for scripts or benchmarking.
