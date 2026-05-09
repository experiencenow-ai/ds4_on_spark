# Ops: TP=2 Readiness Checks (Safe)

TP=2 here means dual-Spark distributed execution (Spark0 + Spark1).

These checks are designed to be **non-destructive** and safe to run repeatedly.
They do not change networking, system services, or GPU settings.

## Preflight Checklist

On both Sparks:

- Confirm OS + kernel + driver versions are known.
- Confirm CUDA toolkit presence (or record "missing").
- Confirm GPU visibility and health via `nvidia-smi`.
- Confirm the intended network path (wired vs Wi-Fi) and MTU.
- Confirm time sync is sane (large skew breaks tracing + some collectives).

## Commands (Spark Side)

```bash
hostname
uname -a
nvidia-smi || true
command -v nvcc >/dev/null 2>&1 && nvcc --version || true
ip addr
ip route
```

Time sanity:

```bash
timedatectl status || true
date -Is
```

## Inter-Spark Connectivity

From Spark0 to Spark1 (and reverse):

```bash
ping -c 3 <peer-host-or-ip>
ssh -o BatchMode=yes <peer-user>@<peer-host> hostname
```

Optional TCP reachability check (if `nc` is installed):

```bash
nc -z -w 2 <peer-host-or-ip> 29500
```

Optional bandwidth check (only if both ends have `iperf3` installed):

```bash
# On Spark1 (server):
iperf3 -s

# On Spark0 (client):
iperf3 -c <spark1-host-or-ip> -t 10 -P 1
```

## NCCL Smoke Test (Optional)

Only run if `nccl-tests` is installed and both GPUs are visible.

Example (adjust interface selection to match your wired NIC):

```bash
NCCL_DEBUG=INFO NCCL_SOCKET_IFNAME=enP7s7 all_reduce_perf -b 8M -e 256M -f 2 -g 1
```

Record:

- exact command line
- interface used
- measured bandwidth/latency
- driver + NCCL versions

## Automation Hook

Once Spark-side scripts are installed under `/opt/ds4/scripts/`, you can run the
repo-provided checks via the systemd oneshot:

```bash
sudo systemctl start ds4-preflight@spark0.service
```

To gate a TP=2 run on required inputs via systemd, use the strict variant:

```bash
sudo systemctl start ds4-preflight-strict@spark0.service
```

`ds4-preflight@.service` validates and reads optional peer settings from `/etc/ds4/ds4-%i.env`:

- `DS4_PEER_HOST` for ping/TCP checks
- `DS4_PEER_SSH` for an optional SSH hop (leave empty to skip)

Avoid setting `DS4_PEER_SSH` to `ds4@...` because the `ds4` service account is
typically configured with `/usr/sbin/nologin`.

When `DS4_PEER_SSH` is set and `DS4_MASTER_ADDR`/`DS4_MASTER_PORT` are present,
`ops_tp2_readiness.sh` also performs a **peer → master** backcheck via SSH
(peer-side ping/TCP and an optional metrics HTTP probe) to catch one-way
firewall/routing issues early.

For ad-hoc runs without systemd, the script supports parsing the env file:

```bash
sudo -u ds4 /opt/ds4/scripts/ops_tp2_readiness.sh --env -/etc/ds4/ds4.env --env /etc/ds4/ds4-spark0.env --self spark0 --peer spark1.local --peer-ssh <peer-user>@spark1.local
```

To gate a TP=2 run on required inputs, add `--strict` (fails non-zero if required
env/config is missing or invalid). In strict mode, the script also enforces:

- `DS4_MASTER_ADDR` is not loopback when `DS4_WORLD_SIZE > 1`
- `DS4_PEER_HOST` is set when `DS4_WORLD_SIZE > 1`

```bash
sudo -u ds4 /opt/ds4/scripts/ops_tp2_readiness.sh --strict --env -/etc/ds4/ds4.env --env /etc/ds4/ds4-spark0.env --self spark0
```

If `DS4_METRICS_PORT` is set and `curl` is available, `ops_tp2_readiness.sh` also
attempts a fast HTTP probe of `http://<metrics-host>:<port>/metrics` (best-effort,
non-fatal). When `DS4_METRICS_ADDR=0.0.0.0`, it probes `127.0.0.1`.

If `DS4_PEER_HOST` is set, it also attempts a best-effort peer probe of
`http://<peer-host>:<DS4_METRICS_PORT>/metrics` (useful for catching firewall/routing issues early).

## Optional: Periodic Preflight (Systemd Timer)

If you want readiness checks to run automatically on boot and periodically after,
install and enable the timer template (human-run):

```bash
sudo install -m 0644 /tmp/ds4-systemd/ds4-preflight@.timer /etc/systemd/system/
sudo systemctl daemon-reload
sudo systemctl enable --now ds4-preflight@spark0.timer
```

Strict variant (fails non-zero on missing/invalid TP=2 inputs; human-run):

```bash
sudo install -m 0644 /tmp/ds4-systemd/ds4-preflight-strict@.timer /etc/systemd/system/
sudo systemctl daemon-reload
sudo systemctl enable --now ds4-preflight-strict@spark0.timer
```

## Optional: Spark Standalone Sanity

If Spark is managed locally via systemd, you can also sanity check the Spark env (non-destructive):

```bash
/opt/ds4/scripts/ops_spark_standalone_check.sh --role worker --env /etc/ds4/spark-spark1.env --master-host spark0.local
```
