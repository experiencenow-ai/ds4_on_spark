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

`ds4-preflight@.service` validates and reads optional peer settings from `/etc/ds4/ds4-%i.env`:

- `DS4_PEER_HOST` for ping/TCP checks
- `DS4_PEER_SSH` for an optional SSH hop (leave empty to skip)

Avoid setting `DS4_PEER_SSH` to `ds4@...` because the `ds4` service account is
typically configured with `/usr/sbin/nologin`.

For ad-hoc runs without systemd, the script supports parsing the env file:

```bash
sudo /opt/ds4/scripts/ops_tp2_readiness.sh --env -/etc/ds4/ds4.env --env /etc/ds4/ds4-spark0.env --self spark0 --peer spark1.local --peer-ssh <peer-user>@spark1.local
```

## Optional: Spark Standalone Sanity

If Spark is managed locally via systemd, you can also sanity check the Spark env (non-destructive):

```bash
/opt/ds4/scripts/ops_spark_standalone_check.sh --role worker --env /etc/ds4/spark-spark1.env --master-host spark0.local
```
