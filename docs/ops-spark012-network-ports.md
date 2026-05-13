# Ops: Spark0/Spark1/Spark2 Network + Ports (TP=3 Prep)

This is a **human-run** reference for the expected network shape and the ports DS4 will use during future TP=3 bring-up.

Do not change Spark firewall rules, routing, or system networking as part of automation loops; document proposed changes for human approval.

If you need a starting point for drafting an allowlist (human-run), see:

- `docs/ops-firewall-allowlist.md`
- `deploy/config/nftables.ds4.spark012.nft.example`

## Hostnames + Paths

Decide which path is authoritative for distributed runs:

- Wired IPv4 on the dedicated subnet (preferred once stabilized)
- mDNS hostnames (`*.local`) for early bring-up

Avoid mixing Wi‑Fi + wired paths in the same benchmark run.

If you pin `/etc/hosts` (recommended once stable), see:

- `deploy/config/hosts.ds4.spark012.example`

If you want stable Mac-side SSH options (identity + dedicated known-hosts file), see:

- `deploy/config/ssh_config.ds4.spark012.example`

## Ports (Defaults)

These are conventions for the templates in this repo; adjust only with an explicit note in your run log.

- SSH: `22/tcp`
- Spark standalone master: `7077/tcp`
- Spark standalone master web UI: `8080/tcp`
- Spark standalone worker web UI: `8081/tcp`
- DS4 metrics: `${DS4_METRICS_PORT}` (default `9090/tcp`) on each Spark
- DS4 distributed master: `${DS4_MASTER_PORT}` (default `29500/tcp`) (usually on Spark0)

## Safe Checks (Spark Side)

Listening ports:

```bash
ss -lntp | head
```

Metrics endpoint (if DS4 is running and exposes HTTP metrics):

```bash
curl -fsS "http://127.0.0.1:${DS4_METRICS_PORT}/metrics" | head
```

## Firewall + Routing Inspection (Read-only)

For read-only routing + firewall inspection commands (some require `sudo`), see:

- `docs/ops-firewall-routing-inspection.md`
