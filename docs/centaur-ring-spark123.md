# Example Centaur HyoR ring rehearsal: Spark1/Spark2/Spark3

Prefer the inventory-driven scripts for new work:

- `scripts/centaur_spark_ring_sim_v73.sh` with `SPARK_NODE_COUNT=<N>`
- `scripts/centaur_spark_ring_rsync_v73.sh <spark1> [spark2 ...]`

The current 3-node example remains:

- `docs/centaur-ring-spark12.md`

This file is retained as a 4-node example, not as a source of truth for the current inventory.

Goal: prepare repeatable Spark1/Spark2/Spark3 ring steps **without needing extra hardware yet**, then provide a first “real ring” path once Spark1/2/3 exist.

Important limitation: `centaur.py hyor-ring-step` and `hyor-broadcast-step` require the peer roots to be **local writable paths** (they copy manifests/objects directly between roots). Until we have a shared filesystem between Sparks (or a wrapper that stages peer roots via rsync), the ring work is rehearsed as a **multi-root simulation on Spark0**.

## Spark1/Spark2/Spark3 bring-up checklist (when hardware exists)

Before attempting a real ring on Spark1/2/3, ensure each node has a local Centaur v73 install footprint (no sudo required):

- `python3` + `python3 -m venv` available
- `unzip` available
- A Centaur v73 extraction + venv under a user-writable dir (recommended: `~/centaur-smoke/v73/run/`)

From your Mac repo root, you can stage the zip to each node:

```bash
sh ./scripts/centaur_spark_v73_stage.sh spark1@<spark1-host> ~/centaur-smoke/v73
sh ./scripts/centaur_spark_v73_stage.sh spark2@<spark2-host> ~/centaur-smoke/v73
sh ./scripts/centaur_spark_v73_stage.sh spark3@<spark3-host> ~/centaur-smoke/v73
```

Recommended per-node setup (run on Spark{1,2,3}) using the reproducible setup script:

```bash
export SSH_OPTS="-o BatchMode=yes -o ConnectTimeout=10 -o StrictHostKeyChecking=accept-new -o UserKnownHostsFile=/private/tmp/ds4_spark_known_hosts"
ssh $SSH_OPTS spark1@<spark1-host> "cd ~/centaur-smoke/v73 && export CENTAUR_ZIP=~/centaur-smoke/v73/centaur_spec_impl_v73.zip && export CENTAUR_LOG=~/centaur-smoke/v73/run/node_setup_spark1.log && sh -s" < ./scripts/centaur_spark_v73_node_setup.sh
ssh $SSH_OPTS spark2@<spark2-host> "cd ~/centaur-smoke/v73 && export CENTAUR_ZIP=~/centaur-smoke/v73/centaur_spec_impl_v73.zip && export CENTAUR_LOG=~/centaur-smoke/v73/run/node_setup_spark2.log && sh -s" < ./scripts/centaur_spark_v73_node_setup.sh
ssh $SSH_OPTS spark3@<spark3-host> "cd ~/centaur-smoke/v73 && export CENTAUR_ZIP=~/centaur-smoke/v73/centaur_spec_impl_v73.zip && export CENTAUR_LOG=~/centaur-smoke/v73/run/node_setup_spark3.log && sh -s" < ./scripts/centaur_spark_v73_node_setup.sh
```

Minimal per-node setup (run on Spark{1,2,3}) if you prefer doing it manually:

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

## Run the Spark0-local ring sim

On Spark0:

```bash
export CENTAUR_ROOT=~/centaur-smoke/v73/run/centaur_spec_impl_v73
export CENTAUR_VENV=~/centaur-smoke/v73/run/venv
sh ./scripts/centaur_spark_ring_sim_v73.sh | tee ~/centaur-smoke/v73/ring_sim/ring_sim.log
```

This creates four Centaur roots under:

- `~/centaur-smoke/v73/ring_sim/controller`
- `~/centaur-smoke/v73/ring_sim/spark0`
- `~/centaur-smoke/v73/ring_sim/spark1`
- `~/centaur-smoke/v73/ring_sim/spark2`
- `~/centaur-smoke/v73/ring_sim/spark3`

And then exercises, for Spark1/Spark2/Spark3:

- `hyor-sync-init` with left/right peer roots
- `hyor-ring-step --scope metadata`
- `hyor-ring-step --scope effective`
- `hyor-sync-effective` manifests to `~/centaur-smoke/v73/ring_sim/effective_manifests/hyor_effective_manifest_spark{1,2,3}.json`
- `hyor-sync-apply` materialization to `~/centaur-smoke/v73/ring_sim/effective/spark{1,2,3}`

## What to record for “ring readiness”

Capture these outputs (sanitized) after the sim:

- `ls -la ~/centaur-smoke/v73/ring_sim/effective/spark1`
- `ls -la ~/centaur-smoke/v73/ring_sim/effective/spark2`
- `ls -la ~/centaur-smoke/v73/ring_sim/effective/spark3`
- `ls -la ~/centaur-smoke/v73/ring_sim/effective_manifests`
- `python3 -u centaur.py hyor-sync-status` for each root (controller + spark0..spark3)

## Next step (when Spark1/2/3 hardware exists)

Decide one of:

- shared filesystem for Centaur roots (so peer roots are real paths), or
- a wrapper that stages peer roots via `rsync` into a local temp dir, runs `hyor-ring-step`, then rsyncs the mutated peer root back (needs careful conflict handling because ring-step writes both sides).

Until one of those exists, treat the ring sim as “API/format readiness”, not as a networked deployment.

## “Real ring” option A (recommended for now): rsync-staged ring-step from Spark0

If Spark1/Spark2/Spark3 hardware exists but there is still **no shared filesystem**, use:

- `scripts/centaur_spark_ring_rsync_v73.sh`

This script runs on Spark0 (or any orchestrator with SSH reachability to Spark1/2/3) and:

1. Pulls `hyor/node_spark{1,2,3}` roots from the remote Sparks into a local workdir
2. Runs `hyor-sync-init` + `hyor-sync-publish` + `hyor-ring-step` (metadata + effective) locally across those roots
3. Captures `hyor-sync-effective` manifests under `RING_WORKDIR/effective_manifests/`
4. Pushes the mutated node roots back to the remote Sparks (and optionally effective dirs when `RING_APPLY=1`)

From your Mac repo root (stream-run on Spark0, passing Spark1/2/3 SSH targets as args):

```bash
export SSH_OPTS="-o BatchMode=yes -o ConnectTimeout=10 -o StrictHostKeyChecking=accept-new -o UserKnownHostsFile=/private/tmp/ds4_spark_known_hosts"
```

```bash
ssh $SSH_OPTS spark0@<spark0-host> "export CENTAUR_ROOT=~/centaur-smoke/v73/run/centaur_spec_impl_v73; export CENTAUR_VENV=~/centaur-smoke/v73/run/venv; sh -s -- spark1@<spark1-host> spark2@<spark2-host> spark3@<spark3-host>" < ./scripts/centaur_spark_ring_rsync_v73.sh
```

Notes:

- Use a dedicated `remote_base_dir` (4th arg) if you want the script to manage a clean namespace on each Spark (it uses `rsync --delete`).
- This is still a staging workaround; it exercises ring data flow and produces runnable node roots on Spark1/2/3, but it is not a shared-root deployment model.

### After rsync ring-step: quick node validation (Spark1/2/3)

On each Spark node, validate the pushed node root exists and is readable:

```bash
export CENTAUR_ROOT=~/centaur-smoke/v73/run/centaur_spec_impl_v73
export CENTAUR_VENV=~/centaur-smoke/v73/run/venv
export NODE_ROOT=~/centaur-smoke/v73/ring_node/hyor/node_spark1   # spark2/spark3 accordingly

"$CENTAUR_VENV/bin/python3" -u "$CENTAUR_ROOT/centaur.py" hyor-sync-status "$NODE_ROOT" --full
```

If you also want to confirm the “effective view” can be materialized on-node:

```bash
mkdir -p ~/centaur-smoke/v73/ring_node/effective_spark1
"$CENTAUR_VENV/bin/python3" -u "$CENTAUR_ROOT/centaur.py" hyor-sync-apply "$NODE_ROOT" spark1 --node-type default --output-dir ~/centaur-smoke/v73/ring_node/effective_spark1 --clean
ls -la ~/centaur-smoke/v73/ring_node/effective_spark1 | sed -n '1,40p'
```

### Optional: HTTP transport for agents (no shared filesystem)

If you want Spark1/2/3 to run `hyor-agent-step` without a shared controller filesystem, use Centaur’s HTTP transport.

Important: the controller runs `hyor-controller-http` (controller API). Each node runs `hyor-agent-http` (node agent endpoint). These are different commands.

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
#
# On Spark3 (example port):
# export NODE_ROOT=~/centaur-smoke/v73/ring_node/hyor/node_spark3
# "$CENTAUR_VENV/bin/python3" -u "$CENTAUR_ROOT/centaur.py" hyor-agent-config-write "$NODE_ROOT" --node-id spark3 --node-type default --transport http --controller-url "$CONTROLLER_URL" --allow-no-executor --no-internet --force
# "$CENTAUR_VENV/bin/python3" -u "$CENTAUR_ROOT/centaur.py" hyor-agent-http "$NODE_ROOT" --host 0.0.0.0 --port 8768
```

3) On the controller, discover the nodes via their agent HTTP endpoints (this registers them in controller state):

```bash
"$CENTAUR_VENV/bin/python3" -u "$CENTAUR_ROOT/centaur.py" hyor-node-discover ~/centaur-smoke/v73/run/hyor/controller --seed-url http://<spark1-host>:8766 --seed-url http://<spark2-host>:8767 --seed-url http://<spark3-host>:8768
```

4) Then run one agent step on each node (it reads the local config and uses `controller_url`):

```bash
"$CENTAUR_VENV/bin/python3" -u "$CENTAUR_ROOT/centaur.py" hyor-agent-step "$NODE_ROOT"
```

Convenience wrappers for the three commands above (easy to stream over SSH): `scripts/centaur_spark_hyor_controller_http_v73.sh`, `scripts/centaur_spark_hyor_agent_http_v73.sh`, `scripts/centaur_spark_hyor_node_discover_v73.sh`.

Keep this strictly as a smoke: no secrets, no large model downloads, and stop if you hit network/auth surprises.

## “Real ring” option B: shared filesystem for peer roots

If you can provide a shared writable filesystem path visible on Spark0/1/2/3 (NFS, CephFS, etc), set each peer root to a real shared path and run `hyor-ring-step` directly without rsync staging.

## Ring issue report template (sanitized)

When the ring sim/rsync run fails, capture:

- Centaur zip facts: `ls -la` and `sha256` of `centaur_spec_impl_v73.zip`
- Mac-side helper: `sh ./scripts/centaur_v73_zip_facts.sh /Users/mac/Downloads/centaur_spec_impl_v73.zip`
- `python3 -V` and `pip freeze` (at least numpy/scipy/scikit-learn)
- Exact Centaur command lines that failed (copy/paste)
- Root paths involved (`controller`, `node_spark1/2/3`, and any `effective_*` dirs)

Then classify:

- **Centaur bug**: parser/schema/state failures inside `centaur.py` commands
- **DS4 runtime bug**: missing `python3`/`unzip`, permissions, filesystem layout, or other host setup unrelated to Centaur logic

For the shared checklist + sanitization rules, see:

- `docs/centaur-bug-report.md`
