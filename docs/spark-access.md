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

### Mac-side Discovery (mDNS + reachability)

```bash
REDACT=1 ./scripts/mac_spark_discovery.sh
```

This prints:

- IPv4/IPv6 addresses for `en0`/`en1` (no MAC addresses)
- `_ssh._tcp` browse results (mDNS instance names)
- Quick SSH port checks against known targets
- Optional mDNS resolution output for `*.local` targets

### Spark Hardware + Toolchain Probe

```bash
REDACT=1 ./scripts/spark_probe.sh spark0@aitopatom-9ab9.local | tee /private/tmp/spark0-probe.txt
```

The probe is designed to capture non-secret OS/CPU/GPU/network/storage data without emitting MAC addresses or host keys. Use `REDACT=1` when saving output for commit; the redacted snapshot is suitable to paste into `docs/spark0-*.md`.

## Spark1 Ready Checklist

When Spark1 exists (or a second Spark is provisioned), the same scripts should work with a new target:

```bash
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
