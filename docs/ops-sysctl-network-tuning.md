# Ops: Optional sysctl network tuning (Spark0/Spark1)

This repo does not apply sysctl changes automatically. Everything below is **human-run**.

Goal: keep a small, reversible checklist for host-wide networking defaults that can impact TP=2 traffic.

## When To Consider

- Sustained high throughput over a wired link with unexplained TCP drops/retransmits.
- NCCL/TP=2 looks “fine” at low load but becomes unstable at higher batch sizes.
- You want to standardize the kernel defaults across Spark0 and Spark1 for repeatable experiments.

## Inspect (Read-only)

On each Spark:

```bash
sysctl net.core.rmem_max net.core.wmem_max net.core.netdev_max_backlog net.core.somaxconn
ip -4 addr
ip -4 route
```

If you already have a failure case, capture a support bundle first (non-destructive):

```bash
/opt/ds4/scripts/ops_collect_support_bundle.sh --instance spark0 --since "2 hours ago" --env -/etc/ds4/ds4.env --env /etc/ds4/ds4-spark0.env
```

## Apply (Optional; Human-run)

This repo provides an example drop-in:

- `deploy/config/sysctl.ds4.conf.example`

On each Spark (after review):

```bash
sudo install -m 0644 /tmp/ds4-config/sysctl.ds4.conf.example /etc/sysctl.d/99-ds4.conf
sudo sysctl --system
```

## Roll Back (Human-run)

```bash
sudo rm -f /etc/sysctl.d/99-ds4.conf
sudo sysctl --system
```

## Risks

- sysctl changes are **host-wide** and can affect unrelated services.
- Some distros use different tooling (`sysctl --system` vs `sysctl -p`); confirm on target OS.
