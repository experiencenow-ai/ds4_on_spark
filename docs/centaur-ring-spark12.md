# Centaur HyoR ring rehearsal: Spark1/Spark2 (3-node ring prep + runbook)

Goal: prepare repeatable Spark1/Spark2 ring steps **without needing a shared filesystem yet**, then provide a first “real ring” path once Spark1/2 exist.

Important limitation: `centaur.py hyor-ring-step` and `hyor-broadcast-step` require the peer roots to be **local writable paths** (they copy manifests/objects directly between roots). Until we have a shared filesystem between Sparks (or a wrapper that stages peer roots via rsync), the ring work is rehearsed as a **multi-root simulation on Spark0**.

## Quickstart (recommended order)

From your Mac (repo root), in order:

0) Preflight: confirm each Spark hostname resolves and SSH is reachable.
Both `scripts/centaur_spark12_v73_stage.sh` and `scripts/centaur_spark12_v73_ring_rsync_run.sh` run SSH preflight checks by default (set `STAGE_SKIP_PREFLIGHT=1` / `RING_SKIP_PREFLIGHT=1` to bypass).
When a hostname does not resolve (common before Spark1/2 exist), use an explicit `user@ip` target instead of `spark1.local`/`spark2.local`.

```bash
REDACT=1 ./scripts/mac_spark_discovery.sh <spark0-host> <spark1-host> <spark2-host>
```

1) Run the Spark0 v73 smoke (stages zip + fixture, runs smoke, writes a remote log):

```bash
export SSH_OPTS="-o BatchMode=yes -o ConnectTimeout=10 -o StrictHostKeyChecking=accept-new -o UserKnownHostsFile=/private/tmp/ds4_spark_known_hosts"
export CENTAUR_RUN_ID="$(date -u +%Y%m%dT%H%M%SZ)"
sh ./scripts/centaur_spark0_v73_evidence_run.sh spark0@<spark0-host>
```

If you want a known-good reference bundle for what “PASS” looks like, see:

- `fixtures/centaur-smoke/spark0-v73/20260512T030829Z/`

2) Run the Spark0-local ring sim rehearsal (does not require Spark1/2 hardware):

	Recommended: one-command evidence loop (run → validate → fetch):

	```bash
	export RING_RUN_ID="$(date -u +%Y%m%dT%H%M%SZ)"
	sh ./scripts/centaur_spark12_v73_ring_sim_evidence_run.sh spark0@<spark0-host>
	```

	If you prefer running the pieces manually:

	```bash
	export RING_RUN_ID="$(date -u +%Y%m%dT%H%M%SZ)"
	sh ./scripts/centaur_spark12_v73_ring_sim_run.sh spark0@<spark0-host>
	ssh $SSH_OPTS spark0@<spark0-host> "export RING_RUN_ID=\"$RING_RUN_ID\"; sh -s -- --mode sim" < ./scripts/centaur_spark12_v73_validate_ring_artifacts.sh
	sh ./scripts/centaur_spark12_v73_ring_sim_fetch_artifacts.sh spark0@<spark0-host> "$RING_RUN_ID"
	```

	To promote a fetched ring-sim bundle into a commit-ready fixtures directory (after review/redaction):

	```bash
	sh ./scripts/centaur_spark12_v73_ring_sim_fixture_pack.sh "$RING_RUN_ID"
	```

	Note: `scripts/centaur_spark12_v73_ring_sim_run.sh` accepts an optional `remote_ring_workdir` argument; `~/...` and `$HOME/...` are fine (the wrapper resolves to an absolute path to avoid creating literal `~` directories on Spark0).

3) When Spark1/2 hardware exists: stage the Centaur v73 zip to Spark1/2 and run per-node setup (creates `~/centaur-smoke/v73/run/` with extracted Centaur + venv):

```bash
export NODE_SETUP_RUN_ID="$(date -u +%Y%m%dT%H%M%SZ)"
sh ./scripts/centaur_spark12_v73_node_setup_run.sh spark1@<spark1-host> spark2@<spark2-host> "~/centaur-smoke/v73" "$NODE_SETUP_RUN_ID"
sh ./scripts/centaur_spark12_v73_node_setup_fetch_logs.sh spark1@<spark1-host> spark2@<spark2-host> "$NODE_SETUP_RUN_ID" "~/centaur-smoke/v73"
```

4) Run the “real ring” rsync-staged ring-step (orchestrated from Spark0; no shared filesystem required):

	Recommended: one-command evidence loop (node setup → ring rsync → validate → fetch):

	```bash
	export RING_RUN_ID="$(date -u +%Y%m%dT%H%M%SZ)"
	sh ./scripts/centaur_spark12_v73_ring_rsync_evidence_run.sh spark0@<spark0-host> spark1@<spark1-host> spark2@<spark2-host>
	```

	To also verify that Spark1/2 can run `hyor-sync-status` locally against the pushed node roots (recommended), set:

	```bash
	export RING_REMOTE_VERIFY=1
	```

	If you already ran node setup and want to skip it:

	```bash
	export RING_SKIP_NODE_SETUP=1
	```

	If you prefer to run the steps manually:

	```bash
	export RING_RUN_ID="$(date -u +%Y%m%dT%H%M%SZ)"
	sh ./scripts/centaur_spark12_v73_ring_rsync_run.sh spark0@<spark0-host> spark1@<spark1-host> spark2@<spark2-host>
	ssh $SSH_OPTS spark0@<spark0-host> "export RING_RUN_ID=\"$RING_RUN_ID\"; sh -s -- --mode rsync" < ./scripts/centaur_spark12_v73_validate_ring_artifacts.sh
	sh ./scripts/centaur_spark12_v73_ring_rsync_fetch_artifacts.sh spark0@<spark0-host> "$RING_RUN_ID"
	```

	To promote a fetched ring-rsync bundle into a commit-ready fixtures directory (after review/redaction):

	```bash
	sh ./scripts/centaur_spark12_v73_ring_rsync_fixture_pack.sh "$RING_RUN_ID"
	```

	Optional next step: enable HTTP transport and run `hyor-agent-step` on Spark1/2 (see “Optional: HTTP transport for agents” below).

## Spark1/Spark2 bring-up checklist (when hardware exists)

Before attempting a real ring on Spark1/2, ensure each node has a local Centaur v73 install footprint (no sudo required):

- `python3` + `python3 -m venv` available
- `unzip` available
- A Centaur v73 extraction + venv under a user-writable dir (recommended: `~/centaur-smoke/v73/run/`)

From your Mac repo root, you can stage the zip (and optional tiny catalog fixture) to both nodes:

```bash
sh ./scripts/centaur_spark12_v73_stage.sh spark1@<spark1-host> spark2@<spark2-host> "~/centaur-smoke/v73"
```

Recommended per-node setup (run on Spark{1,2}) using the reproducible setup script:

```bash
export SSH_OPTS="-o BatchMode=yes -o ConnectTimeout=10 -o StrictHostKeyChecking=accept-new -o UserKnownHostsFile=/private/tmp/ds4_spark_known_hosts"
export NODE_SETUP_RUN_ID="$(date -u +%Y%m%dT%H%M%SZ)"
sh ./scripts/centaur_spark12_v73_node_setup_run.sh spark1@<spark1-host> spark2@<spark2-host> "~/centaur-smoke/v73" "$NODE_SETUP_RUN_ID"
sh ./scripts/centaur_spark12_v73_node_setup_fetch_logs.sh spark1@<spark1-host> spark2@<spark2-host> "$NODE_SETUP_RUN_ID" "~/centaur-smoke/v73"
```

Optional: faster/offline dependency install on Spark1/2 (wheelhouse/cached wheels):

- `CENTAUR_PIP_ARGS="--no-index --find-links=/path/to/wheels"`
- `CENTAUR_SKIP_PIP=1` when re-running in the same venv

Example (Spark1):

```bash
export NODE_SETUP_RUN_ID="$(date -u +%Y%m%dT%H%M%SZ)"
CENTAUR_PIP_ARGS="--no-index --find-links=/path/to/wheels" \
  sh ./scripts/centaur_spark_v73_node_setup_run.sh spark1@<spark1-host> "~/centaur-smoke/v73" "$NODE_SETUP_RUN_ID"
```

Minimal per-node setup (run on Spark{1,2}) if you prefer doing it manually:

```bash
mkdir -p ~/centaur-smoke/v73/run
cd ~/centaur-smoke/v73/run
unzip -q ~/centaur-smoke/v73/centaur_spec_impl_v73.zip
python3 -m venv ./venv
./venv/bin/python3 -m pip install -r ./centaur_spec_impl_v73/requirements.txt
./venv/bin/python3 -u ./centaur_spec_impl_v73/centaur.py selftest --json
```

Do **not** commit zips or venvs into this repo.

## Prereqs (run once on Spark0)

Run the Spark0 v73 smoke first so you have an extracted Centaur tree + venv:

- `docs/centaur-spark0-v73-smoke.md`

After the smoke, you should have:

- `~/centaur-smoke/v73/run/centaur_spec_impl_v73/centaur.py`
- `~/centaur-smoke/v73/run/venv/bin/python3`

## Run the Spark0-local ring sim (example: Spark0/1/2)

On Spark0:

```bash
export CENTAUR_ROOT=~/centaur-smoke/v73/run/centaur_spec_impl_v73
export CENTAUR_VENV=~/centaur-smoke/v73/run/venv

# Recommended: isolate outputs per-run and capture a log
export RING_RUN_ID="$(date -u +%Y%m%dT%H%M%SZ)"
export RING_LOG=~/centaur-smoke/v73/ring_sim_spark12/run/"$RING_RUN_ID"/ring_sim.log
SPARK_NODE_COUNT=3 RING_WORKDIR=~/centaur-smoke/v73/ring_sim_spark12 \
  sh ./scripts/centaur_spark_ring_sim_v73.sh

# Alternative: pipe to tee (no RING_RUN_ID isolation)
# SPARK_NODE_COUNT=3 RING_WORKDIR=~/centaur-smoke/v73/ring_sim_spark12 \
#   sh ./scripts/centaur_spark_ring_sim_v73.sh | tee ~/centaur-smoke/v73/ring_sim_spark12/ring_sim.log
```

For exact command capture in the log, add `export RING_TRACE=1` before running.

This creates three Centaur roots under `.../`:

- `.../controller`
- `.../spark0`
- `.../spark1`
- `.../spark2`

And then exercises, for Spark1/Spark2:

- `hyor-sync-init` with left/right peer roots
- `hyor-ring-step --scope metadata`
- `hyor-ring-step --scope effective`
- `hyor-sync-effective` manifests to `.../effective_manifests/hyor_effective_manifest_spark{1,2}.json`
- `hyor-sync-apply` materialization to `.../effective/spark{1,2}`

If `RING_RUN_ID` is set, the `...` prefix above is:

- `~/centaur-smoke/v73/ring_sim_spark12/run/<run_id>/`

Otherwise it is:

- `~/centaur-smoke/v73/ring_sim_spark12/`

## What to record for “ring readiness”

Capture these outputs (sanitized) after the sim:

- The ring scripts print `hyor-sync-status` for each root post-init and post-ring-step; if you set `RING_LOG`, the log is usually sufficient evidence.
- `ls -la ~/centaur-smoke/v73/ring_sim_spark12/effective/spark1`
- `ls -la ~/centaur-smoke/v73/ring_sim_spark12/effective/spark2`
- `ls -la ~/centaur-smoke/v73/ring_sim_spark12/effective_manifests`
- `python3 -u centaur.py hyor-sync-status` for each root (controller + spark0 + spark1 + spark2)

To validate expected ring artifacts exist (run on the orchestrator host; Spark0 in the sim case):

```bash
export RING_RUN_ID="<run_id>"
sh ./scripts/centaur_spark12_v73_validate_ring_artifacts.sh --mode sim
```

To fetch a small sanitized ring-sim bundle (log + effective manifests + effective view) back to your Mac:

```bash
sh ./scripts/centaur_spark12_v73_ring_sim_fetch_artifacts.sh spark0@<spark0-host> "$RING_RUN_ID"
```

## Next step (when Spark1/2 hardware exists)

Decide one of:

- shared filesystem for Centaur roots (so peer roots are real paths), or
- a wrapper that stages peer roots via `rsync` into a local temp dir, runs `hyor-ring-step`, then rsyncs the mutated peer root back (needs careful conflict handling because ring-step writes both sides).

Until one of those exists, treat the ring sim as “API/format readiness”, not as a networked deployment.

## “Real ring” option A (recommended for now): rsync-staged ring-step from Spark0

If Spark1/Spark2 hardware exists but there is still **no shared filesystem**, use:

- `scripts/centaur_spark_ring_rsync_v73.sh`

This script runs on Spark0 (or any orchestrator with SSH reachability to Spark1/2) and:

1. Pulls `hyor/node_spark{1,2}` roots from the remote Sparks into a local workdir
2. Runs `hyor-sync-init` + `hyor-sync-publish` + `hyor-ring-step` (metadata + effective) locally across those roots
3. Captures `hyor-sync-effective` manifests under `RING_WORKDIR/effective_manifests/`
4. Pushes the mutated node roots back to the remote Sparks (and optionally effective dirs when `RING_APPLY=1`)

From your Mac repo root (runs on Spark0 over SSH, passing Spark1/2 SSH targets as args):

```bash
export SSH_OPTS="-o BatchMode=yes -o ConnectTimeout=10 -o StrictHostKeyChecking=accept-new -o UserKnownHostsFile=/private/tmp/ds4_spark_known_hosts"
```

Recommended wrapper (stages the v73 zip to Spark1/2, sets `RING_RUN_ID`, and writes a remote log under `~/centaur-smoke/v73/ring_rsync_spark12/run/<run_id>/`):

```bash
export RING_RUN_ID="$(date -u +%Y%m%dT%H%M%SZ)"
sh ./scripts/centaur_spark12_v73_ring_rsync_run.sh spark0@<spark0-host> spark1@<spark1-host> spark2@<spark2-host>
```

If you want exact command capture in the remote log, add:

```bash
export RING_TRACE=1
```

Alternative (direct SSH stream, no wrapper):

```bash
ssh $SSH_OPTS spark0@<spark0-host> "export CENTAUR_ROOT=~/centaur-smoke/v73/run/centaur_spec_impl_v73; export CENTAUR_VENV=~/centaur-smoke/v73/run/venv; sh -s -- spark1@<spark1-host> spark2@<spark2-host>" < ./scripts/centaur_spark_ring_rsync_v73.sh
```

Notes:

- For exact command capture, add `export RING_TRACE=1` on the orchestrator host before running.
- Recommended: add `export RING_RUN_ID="$(date -u +%Y%m%dT%H%M%SZ)"` and `export RING_LOG=~/centaur-smoke/v73/ring_rsync_spark12/run/"$RING_RUN_ID"/ring_rsync.log` on the orchestrator host so logs/manifests are per-run.
- Use `--remote-base <dir>` if you want the script to manage a clean namespace on each Spark (it uses `rsync --delete`).
- This is still a staging workaround; it exercises ring data flow and produces runnable node roots on Spark1/2, but it is not a shared-root deployment model.

After a wrapper run, you can fetch a small artifact bundle (log + manifests) back to your Mac:

```bash
sh ./scripts/centaur_spark12_v73_ring_rsync_fetch_artifacts.sh spark0@<spark0-host> "$RING_RUN_ID"
```

To validate expected ring artifacts exist on the orchestrator host (Spark0):

```bash
export RING_RUN_ID="<run_id>"
sh ./scripts/centaur_spark12_v73_validate_ring_artifacts.sh --mode rsync
```

### After rsync ring-step: quick node validation (Spark1/2)

On each Spark node, validate the pushed node root exists and is readable:

```bash
export CENTAUR_ROOT=~/centaur-smoke/v73/run/centaur_spec_impl_v73
export CENTAUR_VENV=~/centaur-smoke/v73/run/venv
export NODE_ROOT=~/centaur-smoke/v73/ring_node/hyor/node_spark1   # spark2 accordingly

"$CENTAUR_VENV/bin/python3" -u "$CENTAUR_ROOT/centaur.py" hyor-sync-status "$NODE_ROOT" --full
```

If you prefer a Mac-side helper that runs the same `hyor-sync-status` checks over SSH (and optionally writes per-node logs), use:

```bash
sh ./scripts/centaur_spark12_v73_ring_rsync_remote_verify.sh spark1@<spark1-host> spark2@<spark2-host>
```

This helper is also wired into `scripts/centaur_spark12_v73_ring_rsync_evidence_run.sh` when `RING_REMOTE_VERIFY=1`.

If you also want to confirm the “effective view” can be materialized on-node:

```bash
mkdir -p ~/centaur-smoke/v73/ring_node/effective_spark1
"$CENTAUR_VENV/bin/python3" -u "$CENTAUR_ROOT/centaur.py" hyor-sync-apply "$NODE_ROOT" spark1 --node-type default --output-dir ~/centaur-smoke/v73/ring_node/effective_spark1 --clean
ls -la ~/centaur-smoke/v73/ring_node/effective_spark1 | sed -n '1,40p'
```

### Optional: HTTP transport for agents (no shared filesystem)

If you want Spark1/2 to run `hyor-agent-step` without a shared controller filesystem, use Centaur’s HTTP transport.

Important: the controller runs `hyor-controller-http` (controller API). Each node runs `hyor-agent-http` (node agent endpoint). These are different commands.

Prereqs:

- You already ran the Spark0 v73 smoke, so Spark0 has `~/centaur-smoke/v73/run/centaur_spec_impl_v73/centaur.py` and `~/centaur-smoke/v73/run/venv/bin/python3`.
- You already ran per-node setup on Spark1/2 so each node has the same Centaur+venv footprint under `~/centaur-smoke/v73/run/`.
- You already ran the ring rsync step (or otherwise created node roots) so Spark1/2 have:
  - `~/centaur-smoke/v73/ring_node/hyor/node_spark1`
  - `~/centaur-smoke/v73/ring_node/hyor/node_spark2`

Ports (example defaults):

- Spark0 controller: `8765`
- Spark1 agent: `8766`
- Spark2 agent: `8767`

If these ports are not reachable between Sparks, stop and fix network access before proceeding.

1) On the controller host (typically Spark0), run the controller HTTP endpoint (human-run, no system service):

```bash
"$CENTAUR_VENV/bin/python3" -u "$CENTAUR_ROOT/centaur.py" hyor-controller-http ~/centaur-smoke/v73/run/hyor/controller --host 0.0.0.0 --port 8765
```

2) On each node, write an HTTP-configured agent config into the node root and start the node agent HTTP endpoint:

```bash
export CONTROLLER_URL="http://<spark0-host>:8765"
"$CENTAUR_VENV/bin/python3" -u "$CENTAUR_ROOT/centaur.py" hyor-agent-config-write "$NODE_ROOT" --node-id spark1 --node-type default --transport http --controller-url "$CONTROLLER_URL" --allow-no-executor --no-internet --force
"$CENTAUR_VENV/bin/python3" -u "$CENTAUR_ROOT/centaur.py" hyor-agent-http "$NODE_ROOT" --host 0.0.0.0 --port 8766

# On Spark2 (example port):
# export NODE_ROOT=~/centaur-smoke/v73/ring_node/hyor/node_spark2
# "$CENTAUR_VENV/bin/python3" -u "$CENTAUR_ROOT/centaur.py" hyor-agent-config-write "$NODE_ROOT" --node-id spark2 --node-type default --transport http --controller-url "$CONTROLLER_URL" --allow-no-executor --no-internet --force
# "$CENTAUR_VENV/bin/python3" -u "$CENTAUR_ROOT/centaur.py" hyor-agent-http "$NODE_ROOT" --host 0.0.0.0 --port 8767
```

3) On the controller, discover the nodes via their agent HTTP endpoints (this registers them in controller state):

```bash
"$CENTAUR_VENV/bin/python3" -u "$CENTAUR_ROOT/centaur.py" hyor-node-discover ~/centaur-smoke/v73/run/hyor/controller --seed-url http://<spark1-host>:8766 --seed-url http://<spark2-host>:8767
```

4) Then run one agent step on each node (it reads the local config and uses `controller_url`):

```bash
"$CENTAUR_VENV/bin/python3" -u "$CENTAUR_ROOT/centaur.py" hyor-agent-step "$NODE_ROOT"
```

Convenience wrappers for the three commands above (easy to stream over SSH): `scripts/centaur_spark_hyor_controller_http_v73.sh`, `scripts/centaur_spark_hyor_agent_http_v73.sh`, `scripts/centaur_spark_hyor_node_discover_v73.sh`.

#### Stream-run the HTTP smoke from your Mac (recommended)

This uses the wrapper scripts above and avoids copying any scripts to the Sparks.
You will need **three terminals** (or `tmux`) because the HTTP servers run until you stop them.

Terminal 1 (Mac): controller HTTP on Spark0:

```bash
ssh $SSH_OPTS spark0@<spark0-host> "export CENTAUR_ROOT=~/centaur-smoke/v73/run/centaur_spec_impl_v73; export CENTAUR_VENV=~/centaur-smoke/v73/run/venv; sh -s -- ~/centaur-smoke/v73/run/hyor/controller 0.0.0.0 8765 0" < ./scripts/centaur_spark_hyor_controller_http_v73.sh
```

Terminal 2 (Mac): agent HTTP on Spark1:

```bash
export CONTROLLER_URL="http://<spark0-host>:8765"
ssh $SSH_OPTS spark1@<spark1-host> "export CENTAUR_ROOT=~/centaur-smoke/v73/run/centaur_spec_impl_v73; export CENTAUR_VENV=~/centaur-smoke/v73/run/venv; sh -s -- ~/centaur-smoke/v73/ring_node/hyor/node_spark1 spark1 \"$CONTROLLER_URL\" 0.0.0.0 8766 0" < ./scripts/centaur_spark_hyor_agent_http_v73.sh
```

Terminal 3 (Mac): agent HTTP on Spark2:

```bash
export CONTROLLER_URL="http://<spark0-host>:8765"
ssh $SSH_OPTS spark2@<spark2-host> "export CENTAUR_ROOT=~/centaur-smoke/v73/run/centaur_spec_impl_v73; export CENTAUR_VENV=~/centaur-smoke/v73/run/venv; sh -s -- ~/centaur-smoke/v73/ring_node/hyor/node_spark2 spark2 \"$CONTROLLER_URL\" 0.0.0.0 8767 0" < ./scripts/centaur_spark_hyor_agent_http_v73.sh
```

Once all three are running, from a **fourth** terminal (or after stopping the controller with `ctrl-c` and restarting it later), discover the nodes on Spark0:

```bash
ssh $SSH_OPTS spark0@<spark0-host> "export CENTAUR_ROOT=~/centaur-smoke/v73/run/centaur_spec_impl_v73; export CENTAUR_VENV=~/centaur-smoke/v73/run/venv; sh -s -- ~/centaur-smoke/v73/run/hyor/controller http://<spark1-host>:8766 http://<spark2-host>:8767" < ./scripts/centaur_spark_hyor_node_discover_v73.sh
```

Then, on each node (Spark1 and Spark2), run one agent step:

```bash
export CENTAUR_ROOT=~/centaur-smoke/v73/run/centaur_spec_impl_v73
export CENTAUR_VENV=~/centaur-smoke/v73/run/venv
export NODE_ROOT=~/centaur-smoke/v73/ring_node/hyor/node_spark1   # spark2 accordingly
"$CENTAUR_VENV/bin/python3" -u "$CENTAUR_ROOT/centaur.py" hyor-agent-step "$NODE_ROOT"
```

Keep this strictly as a smoke: no secrets, no large model downloads, and stop if you hit network/auth surprises.

## “Real ring” option B: shared filesystem for peer roots

If you can provide a shared writable filesystem path visible on Spark0/1/2 (NFS, CephFS, etc), set each peer root to a real shared path and run `hyor-ring-step` directly without rsync staging.

## Ring issue report template (sanitized)

When the ring sim/rsync run fails, capture:

- Centaur zip facts: `ls -la` and `sha256` of `centaur_spec_impl_v73.zip`
- Mac-side helper: `sh ./scripts/centaur_v73_zip_facts.sh /Users/mac/Downloads/centaur_spec_impl_v73.zip`
- `python3 -V` and `pip freeze` (at least numpy/scipy/scikit-learn)
- Exact Centaur command lines that failed (copy/paste)
- Root paths involved (`controller`, `node_spark1/2`, and any `effective_*` dirs)

Then classify:

- **Centaur bug**: parser/schema/state failures inside `centaur.py` commands
- **DS4 runtime bug**: missing `python3`/`unzip`, permissions, filesystem layout, or other host setup unrelated to Centaur logic

For the shared checklist + sanitization rules, see:

- `docs/centaur-bug-report.md`
