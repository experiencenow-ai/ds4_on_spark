# Spark Fleet Maintenance

The switched Spark fabric has one operational entry point for readiness:

```bash
python3 scripts/ds4_spark_fleet_preflight.py \
  --json-output /private/tmp/ds4_spark_fleet_preflight_latest.json
```

The command is read-only. It does not start, stop, restart, reboot, or
reconfigure a node. It checks the complete topology concurrently and exits
non-zero when a node is not safe to admit to the workload.

## Source Of Truth

`v2/profiles/transfer/spark_200g.json` owns node ids, ranks, management
addresses, fabric addresses, SSH options, and fabric host aliases. Operational
scripts must read this file rather than derive addresses from `sparkN` names.
The fleet proxy and preflight both use this manifest.

Do not put Tailscale addresses, login URLs, passwords, API keys, or private
machine credentials in the repository. The preflight records only Tailscale
backend state and whether a local Tailscale address exists.

## Readiness Contract

Each node must have:

- the expected `/etc/ds4-node-rank` value, with no legacy rank file present;
- its expected management and 100G fabric addresses;
- an operational, full-duplex 100G link;
- active `ds4-switched-fabric.service`,
  `centaur-sparkring-agent.service`, and `tailscaled.service`;
- a running Tailscale backend;
- a working NVIDIA query with no active compute workload;
- no stale `sparkpipe_model`, resident, or gateway process;
- matching hashes for the common Centaur source and network helper files.

Warnings do not silently become passes: historical Xid entries are reported
in the receipt, while the retired `/etc/ds4-ring-rank` name is a hard failure.

## Maintenance Sequence

1. Stop admission and verify that the workload is drained.
2. Run the preflight and keep its JSON receipt with the release record.
3. Resolve every `FAIL`; review every `WARN` before proceeding.
4. Update clean Spark checkouts with
   `scripts/ds4_update_spark_nodes.sh --code-only`.
5. Re-run preflight and verify common artifact hashes before any service
   restart.
6. Reboot or restart only the intended canary node, run preflight again, then
   roll through the remaining nodes in small batches.
7. Start the ring only after a final all-node preflight has exit code 0.
8. Keep the release receipt, preflight receipt, and benchmark receipt together.

For package convergence, use the bounded planner after the network baseline is
active:

```bash
python3 scripts/ds4_spark_package_align.py \
  --nodes spark1,spark2,spark3,spark4,spark5,spark6,spark7,spark8,spark9,\
sparka,sparkb,sparkc,sparkd,sparke,sparkf \
  --apply --wave-size 4
```

The planner compares installed names and versions against `spark0`, but only
the reference node's explicit manual package set is managed. The apply path
installs measured missing names in bounded waves, refuses an existing dpkg
lock or non-clean dpkg audit, uses `--no-remove`, and verifies that the
running kernel and NVIDIA driver are unchanged. Vendor, CUDA, RDMA, Ceph,
container, and external-storage packages remain role cohorts. A full installed
package-list copy is intentionally unsupported because it turns dependencies
into accidental manual packages and can enable unrelated services.

The preflight has an explicit `--allow-workload` escape hatch for observing a
running system. That mode is for post-start inspection, never for deciding
whether a new release is safe to start.

## Deep Drift Audit

The preflight answers admission readiness. For hardware and software
comparability, run the read-only deep audit while the fleet is idle:

```bash
python3 scripts/ds4_spark_fleet_audit.py \
  --json-output /private/tmp/ds4_spark_fleet_audit_latest.json
```

The audit reads the same topology and transport policy as the preflight and
collects identity, GPU/CUDA, 100G interface and RDMA state, queues/offloads,
routes, sysctls, filesystems, block/NVMe/PCI/USB inventory, package and systemd
state, firewall state, failed units, time sync, and workload processes. It
compares identity-bearing addresses and node-specific rank files separately so
they do not create false drift. Receipts belong under `/private/tmp` or another
private evidence directory; do not commit them because they contain private
fleet topology and host inventory.

Use the full-duplex fabric check separately for data-plane evidence:

```bash
python3 scripts/ds4_spark_full_duplex_matrix.py \
  --duration-s 10 --omit-s 2 --parallel-streams 16 \
  --output-dir /private/tmp/ds4_spark_fabric_audit_latest
```

An audit is not clean merely because every link negotiates at 100G. Before a
ring release, resolve unexpected within-cohort drift in the active port/RDMA
mapping, queue sizes and offloads, routes, sysctls, packages, enabled units,
firewall rules, and systemd configuration. Hardware and storage differences
must be explicitly assigned to a role; they must not be mistaken for code
parity.

## Route Policy

The fleet proxy supports:

```text
auto       100G fabric, then management, then Tailscale
fabric     100G fabric only
mgmt       management, then Tailscale
tailscale  Tailscale only
```

Use `--route fabric` for data-plane checks and `--route mgmt` or
`--route tailscale` for recovery. Management traffic must not be used as a
substitute for a failed 100G readiness check.

## Current Cleanup Items

- Keep `/etc/ds4-node-rank` as the only rank contract. A legacy
  `/etc/ds4-ring-rank` file is a hard failure and must be removed, not
  supported as a second configuration path.
- Normalize the 100G data-plane port and RDMA mapping before comparing ring
  behavior. The active port, queue sizes, and offload state are measured
  independently of management SSH connectivity; a management-route audit does
  not prove the data plane is equivalent.
- Resolve route and sysctl drift, especially `rp_filter`, before performance
  tests. Staging nodes may intentionally use a different management default,
  but that role split must be explicit in the release record.
- Establish one package, enabled-unit, firewall, and `/etc/systemd/system`
  baseline for the original 13. Package convergence uses the reference node's
  explicit `apt-mark showmanual` set and installs only measured missing names;
  it never installs the entire dependency closure or silently changes kernel,
  NVIDIA, RDMA, CUDA, Ceph, or container cohorts. Ceph and container tooling
  remain explicit storage/service roles and are audited separately.
- Keep the known kernel/driver split on d/e/f as an explicit warning until a
  canary upgrade is planned; do not blanket-upgrade the fleet from a preflight.
- Treat external NVMe filesystem and model-storage differences as role data.
  The root filesystem should be uniform; external storage should be inventoried
  and excluded from runtime parity only when the workload does not read it.
- Treat any new Xid warning as an investigation trigger, but distinguish
  historical boot-buffer entries from an active GPU fault before declaring a
  node bad.
- The six `/home/mac-volumes/*` CIFS mount units are optional external-storage
  roles. Their failure means the corresponding Mac SMB share or server is not
  currently available; it is not a reason to alter the 100G or compute baseline.
  The legacy `/mnt/mac/*` entries are retired by the switched-fabric apply
  script.
