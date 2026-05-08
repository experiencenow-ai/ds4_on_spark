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

## Diagnosis

`ssh spark0@aitopatom-9ab9.local` reaches the Spark SSH server.

Direct `ssh spark0@10.0.0.2` times out from the Mac because the Mac wired port
is not currently in `10.0.0.0/24`. The hostname works because macOS resolves a
reachable link-local address.

Account authentication is now fixed. The Mac public key is installed in
`~spark0/.ssh/authorized_keys`.

## Reproducible Probes (Spark0)

Run macOS-side discovery:

```bash
./scripts/mac_spark_discovery.sh aitopatom-9ab9.local 10.0.0.2
```

Run the Spark probe. For commits, use `REDACT=1` so the output does not contain
private LAN addresses or MACs.

```bash
REDACT=1 ./scripts/spark_probe.sh spark0@aitopatom-9ab9.local | tee /private/tmp/spark0-probe.txt
```

Notes:

- `scripts/spark_probe.sh` uses a temp `known_hosts` file under `/private/tmp`
  so it does not need to write to `~/.ssh/known_hosts`.
- Keep probe output small and copy/paste only the redacted summary into
  `docs/spark0-*.md` reports.

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

## Spark1-Ready Checklist

When Spark1 shows up on the same network:

1. Identify the mDNS name (for example `spark1-host.local`) and verify TCP/22:
   `./scripts/mac_spark_discovery.sh spark1-host.local`.
2. Confirm key auth works: `ssh spark1@spark1-host.local hostname`.
3. Run the same probe script (redacted for commits):
   `REDACT=1 ./scripts/spark_probe.sh spark1@spark1-host.local`.
4. Record only non-secret hardware/toolchain facts in a new `docs/spark0-*.md`
   or `docs/spark1-*.md` style report, and avoid committing raw IP/MAC output.
