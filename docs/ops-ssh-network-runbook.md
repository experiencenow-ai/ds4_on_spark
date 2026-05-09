# Ops: SSH + Network Runbook (Spark0/Spark1)

This is a **human-run** checklist for keeping Spark connectivity stable.

## SSH Identity

From the Mac, prefer key auth and explicit known-hosts storage:

```bash
SSH_OPTS='-o BatchMode=yes -o ConnectTimeout=10 -o StrictHostKeyChecking=accept-new -o UserKnownHostsFile=/private/tmp/ds4_spark_known_hosts'
ssh $SSH_OPTS <user>@spark0.local hostname
```

`scripts/ops_stage_deploy_assets.sh` and `scripts/ops_spark01_mesh_check.sh` both respect `SSH_OPTS`.

If SSH breaks, use `docs/spark-access.md` to reset keys/passwords on the Spark
console.

## Mac-Side Mesh Check (Optional)

To quickly sanity-check both Sparks plus basic peer ping reachability:

```bash
SSH_OPTS='-o BatchMode=yes -o ConnectTimeout=10 -o StrictHostKeyChecking=accept-new -o UserKnownHostsFile=/private/tmp/ds4_spark_known_hosts' \
./scripts/ops_spark01_mesh_check.sh spark0@<spark0-host> spark1@<spark1-host>
```

## Peer SSH From DS4 Preflight (Optional)

`deploy/systemd/ds4-preflight@.service` runs `scripts/ops_tp2_readiness.sh` as the
`ds4` service user. That script can optionally attempt an SSH hop to the peer if
`DS4_PEER_SSH` is set in `/etc/ds4/ds4-<instance>.env`.

Notes:

- The `ds4` service user is commonly configured with `/usr/sbin/nologin`, so it is
  **not** a good SSH login target (avoid `ds4@peer`).
- If you want the SSH check, set `DS4_PEER_SSH` to a login-capable operator user
  (e.g. your distro’s default user) and set `SSH_OPTS` in the env file to point at
  an identity file and a dedicated known-hosts path (see the commented example in
  `deploy/config/ds4-spark*.env.example`). If `SSH_OPTS` is not set, `ops_tp2_readiness.sh`
  defaults to storing peer host keys under `/var/lib/ds4/ssh/known_hosts`.
- If you do not want SSH checks, leave `DS4_PEER_SSH` empty; the script will skip it.

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
