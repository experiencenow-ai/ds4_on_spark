# Ops: SSH + Network Runbook (Spark0/Spark1)

This is a **human-run** checklist for keeping Spark connectivity stable.

## SSH Identity

From the Mac, prefer key auth and explicit known-hosts storage:

```bash
SSH_OPTS='-o BatchMode=yes -o ConnectTimeout=10 -o StrictHostKeyChecking=accept-new -o UserKnownHostsFile=/private/tmp/ds4_spark_known_hosts'
ssh $SSH_OPTS <user>@spark0.local hostname
```

If SSH breaks, use `docs/spark-access.md` to reset keys/passwords on the Spark
console.

## Wired Reachability

Spark0 currently has wired IPv4 `10.0.0.2/24`. If the Mac is not on that subnet,
SSH by hostname may route over Wi-Fi or link-local.

Human-only optional Mac alias:

```bash
sudo ifconfig en0 inet 10.0.0.1 netmask 255.255.255.0 alias
ping 10.0.0.2
ssh spark0@10.0.0.2 hostname
```

## Name Resolution

When bringing up Spark1, decide how names will resolve:

- mDNS (`spark1.local`) for early bootstraps
- `/etc/hosts` entries for stability on an isolated wired subnet

Avoid mixing Wi-Fi and wired paths for TP=2 benchmarks; record which path is
active.

## Safe Checks (Spark Side)

```bash
ip addr
ip route
ping -c 2 <peer-ip-or-hostname>
ss -lntp | head
```

Do not change firewall rules or routing as part of automation loops; document
proposed changes for human approval.
