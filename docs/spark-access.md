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
- When multiple targets are passed to `scripts/spark_probe.sh`, the probe prints `probe targets:` and one `known_hosts:` line per target so runs can be reproduced exactly.
- Use `REDACT=1` for any output you plan to commit.
- Both scripts print the current git short hash when run inside a git worktree, to make snapshots traceable to a specific script version.
- If the checkout's `.git` metadata is not usable (provenance/permission issues), set `DS4_GIT_DIR=/path/to/.git` so the scripts can still print the correct `git: <hash>` for the scripts you are running. If your `DS4_GIT_DIR` is not tied to the current working directory, also set `DS4_GIT_WORK_TREE=/path/to/worktree` (defaults to `$PWD`).
- `scripts/spark_probe.sh` optional toggles:
  - `NVIDIA_SMI_FULL=1` include full `nvidia-smi` output (verbose, process list)
  - `CUDA_RUNTIME_PROBE=0` skip the tiny `nvcc` compile+run probe
  - `PYTORCH_PROBE=1` attempt a `python3` torch probe (usually absent)
  - `NVCC_ARCH=sm_121` force the `nvcc` runtime probe to compile for a specific GPU arch (forwarded into the remote probe; defaults to deriving from the max `nvidia-smi` compute capability when available)
- `scripts/spark_probe.sh` includes cuDNN hints (header macros when present + `ldconfig` library hits) to confirm whether cuDNN is installed.
- `scripts/spark_probe.sh` also captures `nvidia-smi topo -m` (capped), PCIe link state (gen/width max/current), a power/clocks/utilization summary (via `nvidia-smi --query-gpu=...`), kernel module/version hints (`lsmod`, `modinfo nvidia`), CUDA header macros (`cuda.h`), a capped `dpkg-query` CUDA/NVIDIA package list, and a lightweight RDMA/ROCE summary (`/sys/class/infiniband` + `rdma link show`) to cross-check driver/toolkit/network facts. It emits a `warning:` when the parsed `nvcc release` disagrees with `cuda.h` `CUDA_VERSION`, and may emit a `note:` when `nvidia-smi`'s CUDA major differs from the `nvcc` toolkit major (driver vs toolkit). If the `nvcc -arch=...` runtime probe compile fails (unsupported arch), it retries once without `-arch` as a fallback.

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
REDACT=1 ./scripts/spark_probe.sh spark0@aitopatom-9ab9.local | tee /private/tmp/spark0-probe.txt
```

The probe is designed to capture non-secret OS/CPU/GPU/network/storage data without emitting host keys. Use `REDACT=1` when saving output for commit; the redacted snapshot is suitable to paste into `docs/spark0-*.md`.
If the driver-side `nvidia-smi` compute capability query is unavailable, the `nvcc` runtime probe is the fallback source for compute capability (`device0 cc:`).
When `REDACT=1`, the probe also scrubs GPU UUID tokens that can appear in `nvidia-smi -L` output.
The `nvidia-smi` inventory section includes per-GPU `index` and `pci.bus_id` to make multi-GPU hosts easier to compare across reboots.

## Spark1 Ready Checklist

When Spark1 exists (or a second Spark is provisioned), the same scripts should work with a new target:

```bash
REDACT=1 ./scripts/mac_spark_discovery.sh spark1.local
REDACT=1 ./scripts/spark_probe.sh spark0@spark1.local
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
