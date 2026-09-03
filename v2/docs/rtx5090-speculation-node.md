# RTX 5090 speculation node

`rtx5090` is an auxiliary GPU host attached to `sparkf`. It is not a Spark,
does not occupy a rank, and must not be added to collectives, Ceph, or the
`ds4ring0` fabric.

## Network contract

| Purpose | RTX 5090 | sparkf | Routing |
| --- | --- | --- | --- |
| Management | `eno2`, LAN DHCP | Wi-Fi 7, `192.168.50.143/24` | default route allowed |
| Recovery | Tailscale and root key-only SSH on port 2222 | existing fleet recovery paths | management only |
| Speculation data | `eno1`, `10.10.250.2/30` | `enP7s7`, `10.10.250.1/30` | no gateway; MTU 9000 |

The direct `/30` prevents this cable from impersonating the former sparkf 10
GbE management uplink. The Spark 100/200 GbE interfaces, routes, Ceph bindings,
and ranks are unchanged.

The canonical machine-readable record is
`v2/profiles/auxiliary/rtx5090_speculation.json`. Render the intended local
configuration without changing either host:

```bash
python3 scripts/ds4_rtx5090_spec_node.py plan
```

After provisioning or reboot, run the end-to-end gate from the Mac controller:

```bash
python3 scripts/ds4_rtx5090_spec_node.py verify
```

The gate requires the open NVIDIA driver, a 10 Gb/s link in both directions,
jumbo pings across the private cable, active and enabled Tailscale, and an
actual key-only recovery SSH login.

## Runtime boundary

This profile makes the host infrastructure-ready only. SparkPipe's current
speculator callback is process-local; the fleet does not yet have a remote
draft-token RPC protocol between sparkf and this workstation. Do not report
the node as serving speculation until that transport, model lifecycle, health
checks, and fallback semantics are implemented and measured.
