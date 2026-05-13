# Ops: Firewall + Routing Inspection (Read-only)

This is a **human-run** reference for inspecting routing and firewall state on an
ordered Spark inventory (Spark0/Spark1[/Spark2...]).

Do not change firewall rules, routing tables, or system networking as part of automation loops; document proposed changes for human approval.

If you need a starting point for drafting an allowlist (human-run), see:

- `docs/ops-firewall-allowlist.md`

## Routing + Interface (Spark Side)

```bash
ip addr
ip route
ip rule 2>/dev/null || true
ip -s link 2>/dev/null || true
```

Confirm the OS would route to a specific target (does not modify state):

```bash
ip -4 route get <peer-ip-or-host> 2>/dev/null || true
```

Listen sockets:

```bash
ss -lntp | head
```

## Name Resolution (Spark Side)

```bash
getent hosts spark0 spark1 2>/dev/null || true
getent ahostsv4 spark0 spark1 2>/dev/null || true
```

If `systemd-resolved` is present:

```bash
resolvectl status 2>/dev/null || true
```

## Firewall State (Spark Side, Read-only)

Different distros use different firewalls. These commands are **read-only**, but many require `sudo`.

### nftables

```bash
sudo nft list ruleset 2>/dev/null | head -n 200
```

### iptables

```bash
sudo iptables -S 2>/dev/null || true
sudo iptables -L -n -v 2>/dev/null || true
```

### firewalld

```bash
sudo firewall-cmd --state 2>/dev/null || true
sudo firewall-cmd --list-all 2>/dev/null || true
sudo firewall-cmd --list-ports 2>/dev/null || true
```

### ufw

```bash
sudo ufw status verbose 2>/dev/null || true
```

## What To Record

When debugging TP=2 reachability, record:

- the exact DS4 env values (`DS4_MASTER_ADDR`, `DS4_MASTER_PORT`, `DS4_METRICS_PORT`, `DS4_PEER_HOST`)
- `ip route` and `ip -4 route get <peer/master>`
- firewall tool + high-level state (enabled/disabled) and any obvious port blocks

If you want a one-shot snapshot (systemd + journald + routing + selected DS4 env keys), use:

- `docs/ops-support-bundle.md`
