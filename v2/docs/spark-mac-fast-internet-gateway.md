# Spark Mac Fast Internet Gateway

Known-good state from the 2026-06-09 repair:

- Mac Studio `en0` carries both the Spark LAN address `10.20.0.1/24` and the
  fiber WAN address.
- The Mac gets fiber egress by adding split defaults through the fiber gateway:
  `0.0.0.0/1` and `128.0.0.0/1`.
- The Sparks get fast IPv4 internet by preferring the Mac gateway
  `10.20.0.1` on `enP7s7` with metric `50`.
- `10.20.0.13` remains a lower-priority fallback gateway at metric `100` for
  every Spark except `spark3`, which is the `10.20.0.13` host.
- Wi-Fi DHCP defaults stay present as last-resort fallbacks.

## Host Map

The Spark control-plane map is strict and one-to-one:

| Node | Control IP |
| --- | --- |
| `spark0` | `10.20.0.10` |
| `spark1` | `10.20.0.11` |
| `spark2` | `10.20.0.12` |
| `spark3` | `10.20.0.13` |
| `spark4` | `10.20.0.14` |
| `spark5` | `10.20.0.15` |
| `spark6` | `10.20.0.16` |
| `spark7` | `10.20.0.17` |
| `spark8` | `10.20.0.18` |
| `spark9` | `10.20.0.19` |
| `sparka` | `10.20.0.20` |
| `sparkb` | `10.20.0.21` |
| `sparkc` | `10.20.0.22` |

`/etc/hosts` is not enough for new Spark names. SSH also needs `User sparkN`
for each host. Otherwise `ssh sparkc` can silently try the local Mac username
against `10.20.0.22`.

## PF Shape

Use per-host NAT, not a broad `10.20.0.0/24` rule. The LAN exclusion is the
piece that kept Mac-to-Spark SSH working:

```pf
nat on en0 inet from 10.20.0.10 to ! 10.20.0.0/24 -> $fiber_ip
pass in quick on en0 inet from 10.20.0.10 to ! 10.20.0.0/24 keep state
```

Repeat those two rules for every Spark host IP and keep a single egress rule:

```pf
pass out quick on en0 inet from $fiber_ip to any keep state
```

Avoid these shapes:

- NAT on the Spark route interface instead of the fiber egress interface.
- Route-to rules that create PF state but do not NAT/egress.
- Broad `/24` NAT/filter rules that also catch Spark LAN/control traffic.
- Removing the `10.20.0.13` fallback just because it is slower.

## Validation

Read-only audit:

```bash
scripts/ds4_spark_fast_internet_audit.sh
```

Generate the Mac/PF/Spark command shape without applying it:

```bash
scripts/ds4_print_mac_fast_internet_gateway.sh
```

Run a 13-node parallel internet sample:

```bash
BYTES=75000000 scripts/ds4_parallel_internet_download.sh
```

The 2026-06-09 sample downloaded `975000000` bytes from all 13 Sparks in
parallel. Wall-clock aggregate was `5.036 Gbit/s`; sum of per-node curl speeds
was `10.386 Gbit/s`. Every Spark reported the Mac fiber public IP.

## Reboot Note

The Mac may rediscover the fiber path correctly after a reboot, but treat that
as a lab-side test. A Mac route through a Spark that then routes through the Mac
is intentionally not part of this design.

The macOS Network Settings UI can report an Ethernet service as disconnected
even when the underlying interface still has link, addresses, and working
routes. Trust `route -n get 1.1.1.1`, `ifconfig en0`, and a public speed test
more than the UI label when diagnosing this path.
