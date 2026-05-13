# Ops: Centaur Operational Hooks (Deployment/Runbook Only)

This document is **runbook material** for operators who need to stage Centaur
artifacts onto Spark nodes during DS4 bring-up.

This ops loop does **not** define Centaur feature smoke tests or evidence loops.
If you need Centaur correctness validation, use the Centaur Spark automation
loop and its dedicated smoke/evidence scripts.

Everything below is **human-run** (no sudo; no system service changes).

## What’s In This Repo

Centaur v73 helpers live under `scripts/centaur_*.sh`. The primary entrypoints:

- `scripts/centaur_spark_v73_stage.sh` (Mac-side): rsync the Centaur v73 zip (and optional tiny catalog fixture) to a Spark user directory.
- `scripts/centaur_spark_v73_node_setup_run.sh` (Mac-side): stage (optional) + stream-run the Spark-side setup script.
- `scripts/centaur_spark_v73_node_setup.sh` (Spark-side): unzip + create venv + install deps + run a small Centaur selftest (JSON).
- `scripts/centaur_spark_ring_rsync_v73.sh` (Spark0-side/orchestrator): optional ring-step coordinator that rsyncs node roots for workflows that require local writable peer roots.
- Ops preflights (Mac-side):
  - `scripts/ops_spark_ring_mesh_check.sh` (SSH mesh + peer reachability)
  - `scripts/ops_spark_rsync_check.sh` (rsync availability; required for ring-rsync)

## Safety / Expectations

- No `sudo` is used.
- Artifacts and venvs live under a user-writable directory (default `~/centaur-smoke/v73`).
- Do not commit Centaur zips, extracted trees, venvs, or logs into this repo.
- If you plan to share logs externally, review/redact hostnames, usernames, IPs, and any fixture contents.

## Inputs

These scripts expect you have the Centaur spec-impl v73 zip locally on your Mac.

Default local path (override as needed):

```bash
export CENTAUR_ZIP=/Users/mac/Downloads/centaur_spec_impl_v73.zip
```

Optional: stage a tiny catalog fixture JSON alongside the zip:

```bash
export CENTAUR_CATALOG_FIXTURE=fixtures/centaur-smoke/spark0-v73/unit_model_catalog.json
```

## Stage To A Spark (Mac Side)

Pick a per-user remote directory (default is `~/centaur-smoke/v73`):

```bash
./scripts/centaur_spark_v73_stage.sh spark1@<spark1-host> "~/centaur-smoke/v73"
./scripts/centaur_spark_v73_stage.sh spark2@<spark2-host> "~/centaur-smoke/v73"
```

Notes:

- The stage script uses `rsync` over SSH and writes:
  - `<remote_dir>/centaur_spec_impl_v73.zip`
  - `<remote_dir>/unit_model_catalog.json` (optional; if fixture exists)

## Setup On A Spark (Mac Wrapper)

Run the streamed setup (creates/refreshes an extracted Centaur tree + venv under
`<remote_dir>/run/` and writes a remote log):

```bash
./scripts/centaur_spark_v73_node_setup_run.sh spark1@<spark1-host> "~/centaur-smoke/v73"
./scripts/centaur_spark_v73_node_setup_run.sh spark2@<spark2-host> "~/centaur-smoke/v73"
```

To keep a local capture too:

```bash
./scripts/centaur_spark_v73_node_setup_run.sh spark2@<spark2-host> "~/centaur-smoke/v73" "" /private/tmp/centaur_node_setup_spark2.log
```

Optional env knobs (see `scripts/centaur_spark_v73_node_setup_run.sh`):

- `CENTAUR_PIP_ARGS="--no-index --find-links=/path/to/wheels"` for offline installs
- `CENTAUR_SKIP_PIP=1` to skip pip install (assumes deps already present)
- `CENTAUR_CLEAR_VENV=1` to recreate the venv from scratch
- `CENTAUR_TRACE=1` to print exact remote commands

## Where Logs/Artifacts Land (Remote)

With the defaults above, each Spark writes:

- Centaur root: `~/centaur-smoke/v73/run/centaur_spec_impl_v73/`
- venv: `~/centaur-smoke/v73/run/venv/`
- setup logs: `~/centaur-smoke/v73/run/node_setup/<run_id>/node_setup.log`

## Optional: Ring-Step Coordinator (Orchestrator Host)

Some Centaur workflows require **local writable peer roots**. The helper
`scripts/centaur_spark_ring_rsync_v73.sh` coordinates by:

1) maintaining local working copies of node roots
2) running the Centaur ring-step locally across those roots
3) rsync’ing the mutated node roots back to the remote Sparks

Run it from Spark0 (or any host that can SSH to the other Sparks) after Centaur
is already extracted + has a venv on the orchestrator:

```bash
./scripts/centaur_spark_ring_rsync_v73.sh spark1@<spark1-host> spark2@<spark2-host>
```

Preflight (recommended): ring-rsync requires `rsync` installed on the orchestrator and every ring node:

```bash
./scripts/ops_spark_rsync_check.sh spark0@<spark0-host> spark1@<spark1-host> spark2@<spark2-host>
```

See the script header for environment options like `RING_WORKDIR`, `RING_RUN_ID`,
`RING_LOG`, and `RING_APPLY`.

## Troubleshooting

- If `python3 -m venv` fails on the Spark, install the platform’s `python3-venv`
  package (human-run, per host policy).
- If pip installs are slow/unreliable, prefer cached wheels and set
  `CENTAUR_PIP_ARGS` to avoid repeated downloads.
- For SSH reliability, set `SSH_OPTS` explicitly (for example, using a dedicated
  `UserKnownHostsFile` path as described in `docs/ops-ssh-network-runbook.md`).
