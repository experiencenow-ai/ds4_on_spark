# Centaur on Spark0: spec-impl v73 smoke (reproducible)

Goal: run a repeatable, non-destructive Centaur v73 smoke on Spark0 that exercises:

- Centaur v73 venv + requirements install
- Centaur selftest
- HyoR distribution init/sync/publish/ring-step/effective/apply
- Agent config write + node announce + runtime init + agent step
- Provider + model-catalog registration (no model downloads)
- Benchmark suite register + benchmark record/results
- Dashboard generation

This is **human-run**. No `sudo`, no service changes, no secrets, and no model weight downloads.

## Inputs

- Centaur package zip (Mac-local): `/Users/mac/Downloads/centaur_spec_impl_v73.zip`
  - Zip contains `centaur_spec_impl_v73/` with `centaur.py`, `requirements.txt`, and tests.
  - Do **not** commit the zip or venvs into this repo.
  - Optional (Mac-side): capture zip facts without extracting (useful for bug reports):

    ```bash
    sh ./scripts/centaur_v73_zip_facts.sh /Users/mac/Downloads/centaur_spec_impl_v73.zip
    ```

## Package facts (captured by the smoke)

The smoke prints “package facts” early in the run so bug reports can include version/dep context even when later steps fail:

- `zip_mtime/size`: from `ls -la "$CENTAUR_ZIP"`
- `zip_sha256`: computed from the zip bytes
- `decomposer_version`: extracted from `centaur.py` `DECOMPOSER_VERSION` (observed in `/Users/mac/Downloads/centaur_spec_impl_v73.zip` mtime `2026-05-11 02:08` local: `centaur-impl-0.68`)
- `zip_sha256` (observed in the same zip): `3d61b1258aac815d294b3c8fdb4e72ac7851e1b47d02a0daff55117f2885af5a`
- `requirements.txt` (observed in the same zip):
  - `numpy>=1.26`
  - `scipy>=1.11`
  - `scikit-learn>=1.4`

If `pip install` falls back to building these from source (missing wheels for your Python/OS), treat that as a **DS4 runtime/host compatibility** issue for the purposes of triage (not a Centaur logic bug).

## Quickstart (recommended)

If you don’t already have `SSH_OPTS` set, use a safe non-interactive default:

```bash
export SSH_OPTS="-o BatchMode=yes -o ConnectTimeout=10 -o StrictHostKeyChecking=accept-new -o UserKnownHostsFile=/private/tmp/ds4_spark_known_hosts"
```

Mac-side prerequisites for the helper scripts:

- `ssh`
- `rsync` (preferred) or `scp` (fallback)
- `tee` (only if you pass a `local_log` to `scripts/centaur_spark0_v73_run.sh`)

### One-command run from your Mac (recommended)

This stages the zip + fixture and then streams the smoke over SSH:

```bash
sh ./scripts/centaur_spark0_v73_run.sh spark0@<spark0-host>
```

This auto-generates a UTC `CENTAUR_RUN_ID` and writes a remote `smoke.log` under `~/centaur-smoke/v73/run/<run_id>/`.

From your Mac repo root, stage the zip + tiny model catalog fixture to Spark0:

```bash
./scripts/centaur_spark0_v73_stage.sh spark0@<spark0-host>
```

Then run the smoke on Spark0 (the stage script prints the exact command). The smoke script is streamed over SSH, so nothing new needs to be installed on Spark0 besides python3 + unzip:

```bash
ssh $SSH_OPTS spark0@<spark0-host> "cd ~/centaur-smoke/v73 && sh -s" < ./scripts/centaur_spark0_v73_smoke.sh
```

Artifacts are written under:

- `~/centaur-smoke/v73/run/<run_id>/` when `CENTAUR_RUN_ID` is set (recommended), or
- `~/centaur-smoke/v73/run/` otherwise.

Convenience symlinks (recommended for ring runbooks):

- When `CENTAUR_RUN_ID` is set, the smoke also updates:
  - `~/centaur-smoke/v73/run/centaur_spec_impl_v73` -> `~/centaur-smoke/v73/run/<run_id>/centaur_spec_impl_v73`
  - `~/centaur-smoke/v73/run/venv` -> `~/centaur-smoke/v73/run/<run_id>/venv`

Notable outputs:

- `effective_manifests/hyor_effective_manifest_spark0.json` (from `hyor-sync-effective`)
- `hyor_effective/spark0/` (materialized node view from `hyor-sync-apply`)
- `hyor_dashboard/` (HTML/JSON dashboard output)
- `smoke.log` (if `CENTAUR_LOG` is set; `centaur_spark0_v73_run.sh` sets it automatically)

To validate the expected artifacts exist (run on Spark0):

```bash
export CENTAUR_RUN_ID="<run_id>"
sh ./scripts/centaur_spark0_v73_validate_artifacts.sh
```

### Optional: faster/offline dependency install

Centaur v73 `requirements.txt` includes `numpy/scipy/scikit-learn`. On Spark0, install can be slow without cached wheels.

If you have a wheelhouse on Spark0, pass:

- `CENTAUR_PIP_ARGS="--no-index --find-links=/path/to/wheels"`

Or to skip install entirely (when re-running in the same venv):

- `CENTAUR_SKIP_PIP=1`

## What the smoke actually runs

See `scripts/centaur_spark0_v73_smoke.sh` for the fully reproducible command sequence.
Highlights:

- `python3 -m venv "$CENTAUR_WORKDIR/venv"`
- `pip install -r "$CENTAUR_WORKDIR/centaur_spec_impl_v73/requirements.txt"` (numpy/scipy/scikit-learn)
- `python3 -m py_compile centaur.py tests/test_centaur.py`
- `python3 -u centaur.py selftest --json`
- `python3 -u centaur.py hyor-sync-init ...`
- `python3 -u centaur.py hyor-sync-publish ...`
- `python3 -u centaur.py hyor-ring-step --scope metadata` and `--scope effective`
- `python3 -u centaur.py hyor-sync-effective ...` + `hyor-sync-apply ...`
- `python3 -u centaur.py hyor-agent-config-write ...`
- `python3 -u centaur.py hyor-node-announce ...`
- `python3 -u centaur.py hyor-runtime-init ...`
- `python3 -u centaur.py hyor-agent-step ...`
- `python3 -u centaur.py hyor-provider-register ...`
- `python3 -u centaur.py hyor-model-catalog-import ...`
- `python3 -u centaur.py hyor-benchmark-suite-register ...`
- `python3 -u centaur.py hyor-benchmark-record ...` + `hyor-benchmark-results ...`
- `python3 -u centaur.py hyor-dashboard ...`

The provider/model path uses the tiny synthetic fixture at:

- `fixtures/centaur-smoke/spark0-v73/unit_model_catalog.json`

## Capturing a smoke report (sanitized)

When saving a smoke excerpt for PRs/issues, capture:

- The exact Spark0 command line and working directory (`pwd`, `CENTAUR_ZIP`, `CENTAUR_WORKDIR`)
- `python3 -V` and venv python path
- `pip freeze` output
- `sha256` of the Centaur zip (the smoke prints it as `zip_sha256: ...`)
- Command outputs for each failing sub-step (bounded tails)

Avoid committing:

- raw SSH host keys
- private IPs / MAC addresses
- any API keys / tokens (Centaur provider registration should only reference env var names via `--auth-env`, not values)

If you ran with `CENTAUR_RUN_ID` (recommended), you can fetch a small artifact bundle (log + manifests + dashboard) back to your Mac:

```bash
sh ./scripts/centaur_spark0_v73_fetch_artifacts.sh spark0@<spark0-host> "$CENTAUR_RUN_ID"
```

To pack a fetched bundle into a commit-ready fixtures directory (after review/redaction), run:

```bash
sh ./scripts/centaur_spark0_v73_fixture_pack.sh "$CENTAUR_RUN_ID"
```

For a fuller bug-report checklist and sanitization guidance, see:

- `docs/centaur-bug-report.md`

## Known-good evidence (Spark0 v73 PASS)

The repo includes sanitized, commit-safe Spark0 v73 smoke artifact bundles:

- Run id: `20260512T030829Z`
- Zip: `/Users/mac/Downloads/centaur_spec_impl_v73.zip`
  - `zip_sha256`: `3d61b1258aac815d294b3c8fdb4e72ac7851e1b47d02a0daff55117f2885af5a`
  - `decomposer_version`: `centaur-impl-0.68`
- Spark0 python: `Python 3.12.3` (`aarch64`, Ubuntu `6.17.0-1014-nvidia`)
- Spark0 deps (pip): `numpy==2.4.4`, `scipy==1.17.1`, `scikit-learn==1.8.0`
- Bundle path:
  - `fixtures/centaur-smoke/spark0-v73/20260512T030829Z/`

- Run id: `20260512T073455Z`
- Zip: `/Users/mac/Downloads/centaur_spec_impl_v73.zip`
  - `zip_sha256`: `3d61b1258aac815d294b3c8fdb4e72ac7851e1b47d02a0daff55117f2885af5a`
  - `decomposer_version`: `centaur-impl-0.68`
- Spark0 python: `Python 3.12.3` (`aarch64`, Ubuntu `6.17.0-1014-nvidia`)
- Spark0 deps (pip): `numpy==2.4.4`, `scipy==1.17.1`, `scikit-learn==1.8.0`
- Bundle path:
  - `fixtures/centaur-smoke/spark0-v73/20260512T073455Z/`

The bundle contains `smoke.log`, `effective_manifests/`, `hyor_effective/`, and `hyor_dashboard/`.

## Bug triage: Centaur vs DS4 runtime

When something fails, label it explicitly:

- **Centaur bug**: failures inside `centaur.py` commands (parser errors, schema errors, state corruption, selftest failures).
- **DS4 runtime bug**: failures caused by missing system dependencies / Spark runtime layout unrelated to Centaur (missing `python3`, missing `unzip`, broken filesystem permissions, etc).

For Centaur bugs, always include:

- `zip_sha256` + zip mtime
- exact Centaur command line
- the affected Centaur root directory (e.g. `~/centaur-smoke/v73/run/hyor/controller`)
- `pip freeze` excerpt for `numpy`, `scipy`, and `scikit-learn`

## Smoke report template (copy/paste)

```text
Spark0 host: <redacted-hostname>
Run date (UTC): <yyyy-mm-dd>
Working dir: <pwd>
Command:
  ssh ... "cd ... && sh -s" < ./scripts/centaur_spark0_v73_smoke.sh

Centaur zip:
  path: <CENTAUR_ZIP>
  mtime: <ls -la>
  sha256: <zip_sha256>

Python:
  python3 -V: <...>
  venv python: <sys.executable>

Deps:
  pip freeze (top offenders): <numpy/scipy/scikit-learn versions>

Result:
  selftest: PASS|FAIL
  hyor sync/publish/ring-step/effective/apply: PASS|FAIL
  agent config/announce/runtime/step: PASS|FAIL
  provider/model catalog: PASS|FAIL
  benchmark register/record/results: PASS|FAIL
  dashboard: PASS|FAIL

If FAIL:
  Classification: Centaur bug | DS4 runtime bug
  Failing command: <exact centaur.py ...>
  Tail excerpt (sanitized): <...>
```
