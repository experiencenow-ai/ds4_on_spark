# Spark Management Route Selection

The operator-facing `sparkN` SSH names select one management path per new
connection:

1. direct 10GbE management address;
2. the 200GbE ring through `spark8`, then `spark9`;
3. WiFi emergency SSH, either directly to that Spark or through a WiFi
   bastion to its ring address.

The route selector requires a valid SSH banner before accepting a path. If all
paths fail, it exits nonzero. It does not silently substitute another command,
transport implementation, or data-copy method.

## Install

Install only from a checkout pulled from merged `main`:

```bash
python3 scripts/ds4_install_spark_ssh_failover.py --dry-run
python3 scripts/ds4_install_spark_ssh_failover.py
```

The installer:

- copies the selector and profile to
  `~/.local/libexec/ds4-spark-management`;
- replaces the existing `DS4 SPARKNETWORK` block in `~/.ssh/config`;
- validates every generated SSH alias with `ssh -G`;
- saves the prior SSH config beside it with a UTC-stamped backup name;
- uses persistent, dedicated known-host files under `~/.ssh`.

No Spark service or network interface is restarted.

## Caller Contract

Use the canonical names for normal management work:

```bash
ssh spark2
scp artifact spark7:/tmp/
rsync -a source/ sparkc:/tmp/source/
```

These callers automatically use the selected channel because all three use
OpenSSH configuration.

`sparkf` is a special case: its former 10 GbE management port is now the
private RTX 5090 speculation link. Its profile has `direct_enabled: false`,
so both `ssh sparkf` and the compatibility alias `ssh sparkf-10g` skip the
dead `10.20.0.25` path. They try `10.10.100.25` through a ring bastion, then
the Wi-Fi 7 emergency tunnel. `sparkf-200g` and `sparkf-wifi` remain explicit
forced-route aliases.

Use explicit aliases only to diagnose a channel:

```bash
ssh spark2-10g
ssh spark2-200g
ssh spark2-wifi
ssh spark2-emergency
```

`sparkN-wifi` still authenticates as the normal `sparkN` account. The
restricted `sparkemerg` account is only the transport hop to port 22.
`sparkN-emergency` logs into that restricted account directly when the node
has an active WiFi interface.

The selected routes are appended to:

```text
~/.local/state/ds4/spark_ssh_routes.log
```

## DHCP Independence

WiFi-capable nodes list a scoped IPv6 link-local address first and an mDNS
name second. Link-local addressing does not depend on the WiFi DHCP lease.
The mDNS name remains a secondary path if an interface identifier changes.

`spark0` and `spark5` currently have no active WiFi interface. Their WiFi tier
uses `spark8` and then `spark9` as emergency bastions.

## Scope

This transparently covers SSH-based control traffic. A program opening a raw
HTTP or TCP URL such as `http://10.20.0.10:8700` does not consult SSH config.
Such services need a persistent local SSH tunnel through the canonical
`sparkN` alias if route transparency is required.
