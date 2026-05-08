# Spark Access Notes

Current observed Spark identity:

- Hostname: `aitopatom-9ab9.local`
- SSH service: advertised via Bonjour as `aitopatom-9ab9 SSH`
- SSH port: reachable on port 22
- Link-local IPv6: reachable through the Mac wired interface
- Spark wired IPv4: configured by user as `10.0.0.2`
- Mac wired IPv4 observed during bootstrap: `192.168.100.1/16`
- Mac Wi-Fi IPv4 observed during bootstrap: `172.16.11.245/24`
- Spark Wi-Fi IPv4 observed during probe: `172.16.11.228/24`
- Spark wired interface: `enP7s7`, MTU 9000
- SSH key authentication from the Mac is now working for `spark0`.

## Reproducible Probes

From the Mac repo root, use the scripts in `scripts/` to keep probes consistent and safe-to-commit.

### Mac-side Discovery (mDNS + reachability)

```bash
./scripts/mac_spark_discovery.sh
```

This prints:

- IPv4/IPv6 addresses for `en0`/`en1` (no MAC addresses)
- `_ssh._tcp` browse results (mDNS instance names)
- Quick SSH port checks against known targets

### Spark Hardware + Toolchain Probe

```bash
./scripts/spark_probe.sh spark0@aitopatom-9ab9.local
```

The probe is designed to capture non-secret OS/CPU/GPU/network/storage data without emitting MAC addresses or host keys. For a snapshot you can commit, redirect output and summarize the key facts in `docs/spark0-*.md`.

## Spark1 Ready Checklist

When Spark1 exists (or a second Spark is provisioned), the same scripts should work with a new target:

```bash
./scripts/spark_probe.sh spark0@spark1.local
```

If Spark1 uses a different login user or mDNS name, pass `user@host` explicitly.

## Diagnosis

`ssh spark0@aitopatom-9ab9.local` reaches the Spark SSH server.

Direct `ssh spark0@10.0.0.2` times out from the Mac because the Mac wired port
is not currently in `10.0.0.0/24`. The hostname works because macOS resolves a
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

To make `10.0.0.2` reachable directly from the Mac wired port:

```bash
sudo ifconfig en0 inet 10.0.0.1 netmask 255.255.255.0 alias
ping 10.0.0.2
ssh spark0@10.0.0.2 hostname
```

Use the hostname path until the alias is needed for scripts or benchmarking.
