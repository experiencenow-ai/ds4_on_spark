# Mac Studio Spark3 Route Incident - 2026-05-23

## Summary

Running `scripts/ds4_mac_10g_gateway_apply.sh` with its original behavior added
two broad `/1` routes on the Mac Studio:

```text
0/1     -> 10.20.0.13 on en0
128/1   -> 10.20.0.13 on en0
```

Those routes moved essentially all internet-bound Mac traffic from the normal
Wi-Fi path onto Spark3's temporary NAT gateway. That stranded remote-desktop
access when the Mac was being managed remotely.

## Recovery

Remove the broad route override:

```bash
cd "/Users/mac/Documents/New project 4"
sudo scripts/ds4_mac_10g_gateway_disable.sh
```

Manual equivalent:

```bash
sudo route -n delete -net 0.0.0.0/1 10.20.0.13
sudo route -n delete -net 128.0.0.0/1 10.20.0.13
```

Expected route state after recovery:

```text
default  -> 192.168.1.1 on en1
10.20/24 -> link on en0
```

## Fix

`scripts/ds4_mac_10g_gateway_apply.sh` now defaults to cluster-access-only:

- install `10.20.0.1/24` on `en0`;
- remove any stale `/1` routes through Spark3;
- leave the Mac's internet default route unchanged.

The risky default-route override now requires explicit opt-in:

```bash
DS4_MAC_10G_DEFAULT_ROUTE=1 scripts/ds4_mac_10g_gateway_apply.sh
```

Only use that opt-in while physically at the Mac or while a second independent
remote-control path is already verified.

## Jump Desktop

After route recovery, `JumpConnect` was relaunched. Logs showed successful HTTPS
traffic over Wi-Fi `en1`, including a `200` response, so Jump Desktop networking
was healthy again at the Mac side.
