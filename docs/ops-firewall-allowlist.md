# Ops: Firewall Allowlist Examples (Human-run)

This repo NEVER applies firewall changes automatically. This document is a **human-run**
reference for drafting a minimal allowlist for DS4 bring-up on an ordered Spark
inventory.

Firewall changes can lock you out. Only apply changes when you have console/OOB
access and can recover if SSH is interrupted.

## Goals

- Keep SSH available for operator access.
- Allow DS4 metrics scraping on each Spark.
- Allow DS4 distributed master traffic on the rank0/Spark0 host.
- Keep the scope narrow: allow from the inventory subnet or explicit peer IPs.

## Ports (Defaults)

These are conventions for the templates in this repo; adjust only with an explicit
note in your run log.

- SSH: `22/tcp`
- DS4 metrics: `${DS4_METRICS_PORT}` (default `9090/tcp`) on each Spark
- DS4 distributed master: `${DS4_MASTER_PORT}` (default `29500/tcp`) (usually Spark0 only)
- Spark standalone (optional): `7077/tcp`, `8080/tcp`, `8081/tcp` (only if you run Spark via systemd on that host)

## Read-only Inspection First

Before proposing any changes, capture the current state (some commands require `sudo`):

- `docs/ops-firewall-routing-inspection.md`

Also confirm what is actually listening:

```bash
ss -lntp | head
```

## Example: nftables Snippet (TP=3 / Spark0-Spark2)

This repo includes a starting point for a 3-node inventory subnet allowlist:

- `deploy/config/nftables.ds4.spark012.nft.example`

Notes:

- The snippet is designed to be jumped-to from your distro’s baseline `input` chain.
- It intentionally does NOT set a default `policy drop` or flush any existing ruleset.
- Uncomment the DS4 master-port allow rule only on rank0/Spark0.

Safe syntax check (does not apply):

```bash
sudo nft -c -f deploy/config/nftables.ds4.spark012.nft.example
```

If you choose to apply, follow your distro’s nftables include conventions (varies
by OS) and ensure you can recover via console if you lose SSH.

## Validation After Applying (Human-run)

Confirm SSH still works from the operator/Mac:

```bash
ssh -o BatchMode=yes -o ConnectTimeout=10 spark0@<spark0-host> hostname
```

Confirm DS4 metrics reachability (if DS4 is running and exports HTTP metrics):

```bash
curl -fsS "http://<spark2-host>:${DS4_METRICS_PORT}/metrics" | head
```

Confirm DS4 master port is reachable (only meaningful if something is listening):

```bash
nc -z -w 2 <spark0-host> ${DS4_MASTER_PORT}
```

## Don’t Automate It

Do not change Spark firewall rules, routing, or system networking as part of
automation loops; document proposed changes for human approval.

