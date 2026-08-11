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

The preflight has an explicit `--allow-workload` escape hatch for observing a
running system. That mode is for post-start inspection, never for deciding
whether a new release is safe to start.

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

- Migrate the original 13 nodes from `/etc/ds4-ring-rank` to
  `/etc/ds4-node-rank` under a separate guarded maintenance step, then remove
  the legacy file. Preflight remains red until this is complete.
- Keep the known kernel/driver split on d/e/f as an explicit warning until a
  canary upgrade is planned; do not blanket-upgrade the fleet from a preflight.
- Treat any new Xid warning as an investigation trigger, but distinguish
  historical boot-buffer entries from an active GPU fault before declaring a
  node bad.
