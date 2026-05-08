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
