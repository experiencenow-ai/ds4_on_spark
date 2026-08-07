# Spark Internet Uplink Priority

Every Spark uses the same ordered Internet policy:

1. 10GbE `enP7s7` through the ASUS router;
2. `ASUS_40` on `wlP9s9`;
3. the saved TP-Link D660 WiFi profile.

The wired connection retains the existing `10.20.0.N/24` management address
and adds a static ASUS address. No 200GbE interface, ring route, or `ds4ring0`
state is modified.

## Address Contract

The ASUS DHCP pool is `192.168.50.2-192.168.50.127`. Static infrastructure
uses the upper half of the `/24`.

- Spark rank `N`: `192.168.50.(128 + N)`
- Mac Studio 10GbE: `192.168.50.249`

Spark suffixes are hexadecimal, so `sparkf` is rank 15 and `spark10` is rank
16. The current 13 nodes, the next three, and another sixteen nodes occupy
`.128-.159`; no existing address changes when nodes are added. Spark addresses
may continue through `.248`; `.249` remains the Mac, and `.250-.254` remain
unassigned infrastructure addresses.

## Failure Behavior

NetworkManager route metrics are 10 for wired ASUS, 100 for ASUS WiFi, and
200 for TP-Link. A systemd timer checks actual Internet reachability every 15
seconds. When the ASUS wired path is present but its Internet path is dead, the
monitor removes only its runtime default route so TP-Link can carry traffic.
It restores the wired default as soon as the probe succeeds.

ASUS WiFi failures use a five-minute retry cooldown to avoid repeatedly
interrupting a working TP-Link fallback. Every transition and failed probe is
written to the system journal; if no path works the service exits nonzero.
There is no silent fallback.

Transient NetworkManager restarts are explicit recovery events. Every `nmcli`
operation retries only the D-Bus/unavailable errors that identify a restart,
prints `networkmanager=waiting`, and either prints `networkmanager=ready`
within 30 seconds or fails. The systemd monitor also retries a failed run after
five seconds.

## Installation

Install only from a clean checkout pulled from merged `main`. Put the ASUS PSK
in `/etc/ds4-uplink/asus.psk` with mode `0600`, then run:

```bash
sudo scripts/ds4_install_spark_uplink_local.sh spark0
```

The installer preserves all old NetworkManager profiles and captures the
pre-install state under `/var/lib/ds4-uplink/`. Profile activation is detached
by three seconds so an SSH session on `10.20.0.N` can close before `enP7s7` is
rebound.

## Validation

```bash
sudo /usr/local/sbin/ds4_spark_uplink.py audit
systemctl status ds4-uplink-monitor.timer
journalctl -u ds4-uplink-monitor.service -n 20
```

Acceptance requires both static wired addresses, the wired default at metric
10, all three canonical profiles, successful Internet traffic bound to
`enP7s7`, and unchanged `10.10.*`/`ds4ring0` state.

Run the destructive failover canary over the management address only:

```bash
sudo /usr/local/sbin/ds4_spark_uplink_canary.sh
```

The canary blocks traffic from the currently selected source addresses with
temporary policy rules. It does not modify SSIDs, credentials, connection
profiles, or ring interfaces. A cleanup trap removes both rules and restores
the ordered monitor even when a canary assertion fails.
