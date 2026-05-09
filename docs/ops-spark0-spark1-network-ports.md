# Ops: Spark0/Spark1 Network + Ports (TP=2 Prep)

This is a **human-run** reference for the expected network shape and the ports DS4 will use during TP=2 bring-up.

Do not change Spark firewall rules, routing, or system networking as part of automation loops; document proposed changes for human approval.

## Hostnames + Paths

Decide which path is authoritative for TP=2 runs:

- Wired IPv4 on the dedicated subnet (preferred once stabilized)
- mDNS hostnames (`*.local`) for early bring-up

Avoid mixing Wi‑Fi + wired paths in the same benchmark run.

## Ports (Defaults)

These are conventions for the templates in this repo; adjust only with an explicit note in your run log.

- SSH: `22/tcp`
- Spark standalone master: `7077/tcp`
- Spark standalone master web UI: `8080/tcp`
- Spark standalone worker web UI: `8081/tcp`
- DS4 metrics: `${DS4_METRICS_PORT}` (default `9090/tcp`)
- DS4 distributed master: `${DS4_MASTER_PORT}` (default `29500/tcp`)

## Safe Checks (Spark Side)

Listening ports:

```bash
ss -lntp | head
```

Metrics endpoint (if DS4 is running and exposes HTTP metrics):

```bash
curl -fsS "http://127.0.0.1:${DS4_METRICS_PORT}/metrics" | head
```

Peer reachability (no changes made):

```bash
ping -c 3 <peer-host-or-ip>
ssh -o BatchMode=yes <peer-user>@<peer-host> hostname
```

## Firewall + Routing Inspection (Read-only)

For read-only routing + firewall inspection commands (some require `sudo`), see:

- `docs/ops-firewall-routing-inspection.md`

## Safe Checks (Mac Side)

Use explicit SSH options and keep known-hosts isolated:

```bash
SSH_OPTS='-o BatchMode=yes -o ConnectTimeout=10 -o StrictHostKeyChecking=accept-new -o UserKnownHostsFile=/private/tmp/ds4_spark_known_hosts'
ssh $SSH_OPTS spark0@<spark0-host> hostname
```
