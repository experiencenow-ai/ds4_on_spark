# RTX 5090 speculation node

`rtx5090` is an auxiliary GPU host attached to `sparkf`. It is not a Spark,
does not occupy a rank, and must not be added to collectives, Ceph, or the
`ds4ring0` fabric.

## Network contract

| Purpose | RTX 5090 | sparkf | Routing |
| --- | --- | --- | --- |
| Management | `eno2`, LAN DHCP, metric 100; Wi-Fi 7 `wlp133s0f0`, `ASUS_40`, DHCP, metric 300 | Wi-Fi 7, `192.168.50.143/24` | default route allowed |
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

Every Spark has a managed `rtx5090` host alias. `spark0` through `sparke`
resolve it to the router-facing `192.168.50.4`; `sparkf` resolves it to
`10.10.250.2`, keeping speculation traffic on the private 10 Gb/s cable.

The workstation has a boot-mounted ext4 LV at `/srv/drafters`, owned by
`spec:spec`. Drafter models are copied one at a time into
`/srv/drafters/.staging/<model>`, checksum-compared to the published source,
and renamed to `/srv/drafters/<model>` only after the comparison is clean.

The initial published set is:

- `deepseek-v4-flash-dflash-redhatai`
- `glm-5.3-flash-dflash2`
- `kimi-k3-dflash-modal`
- `kimi-k3-dflash2-lightseek`
- `qwen3.8-27b-dflash2-incoai`
- `qwen3.8-max-dflash-modal`

The target-side record is `/srv/drafters/TRANSFER-RECEIPT.json`. It records the
source RAID, relay route, destination filesystem UUID, all model names, and the
independently verified SHA-256 for every weight file.

## Initial GPU qualification

The 2026-09-03 onsite gate used NVIDIA open driver 595.84 and CUDA 13.3,
compiled for `sm_120`. It pattern-wrote and verified 30,064,771,072 bytes
(89.3% of VRAM), measured 762.87 GB/s device-to-device copy and 49.56/22.75
GB/s PCIe host-to-device/device-to-host copy, then ran 8192-square cuBLAS GEMM
for 60 seconds. The GEMM result was numerically correct and averaged 233.89
TFLOP/s. Telemetry recorded 100% SM use, 384 W peak power, 59 C peak GPU
temperature, no thermal or power throttling, no PCIe errors, and no kernel Xid
or AER errors.

The exact CUDA source, compile/run command, hardware metadata, and captured
results are retained on the node under `/srv/drafters/.qualification/`.

## Runtime boundary

This profile makes the host infrastructure-ready only. SparkPipe's current
speculator callback is process-local; the fleet does not yet have a remote
draft-token RPC protocol between sparkf and this workstation. Do not report
the node as serving speculation until that transport, model lifecycle, health
checks, and fallback semantics are implemented and measured.
