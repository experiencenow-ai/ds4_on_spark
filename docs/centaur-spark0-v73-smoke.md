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

## Quickstart (recommended)

If you don’t already have `SSH_OPTS` set, use a safe non-interactive default:

```bash
export SSH_OPTS="-o BatchMode=yes -o ConnectTimeout=10 -o StrictHostKeyChecking=accept-new -o UserKnownHostsFile=/private/tmp/ds4_spark_known_hosts"
```

From your Mac repo root, stage the zip + tiny model catalog fixture to Spark0:

```bash
./scripts/centaur_spark0_v73_stage.sh spark0@<spark0-host>
```

Then run the smoke on Spark0 (the stage script prints the exact command). The smoke script is streamed over SSH, so nothing new needs to be installed on Spark0 besides python3 + unzip:

```bash
ssh $SSH_OPTS spark0@<spark0-host> "cd ~/centaur-smoke/v73 && sh -s" < ./scripts/centaur_spark0_v73_smoke.sh
```

Artifacts are written under `~/centaur-smoke/v73/run/` on Spark0.

### Optional: faster/offline dependency install

Centaur v73 `requirements.txt` includes `numpy/scipy/scikit-learn`. On Spark0, install can be slow without cached wheels.

If you have a wheelhouse on Spark0, pass:

- `CENTAUR_PIP_ARGS="--no-index --find-links=/path/to/wheels"`

Or to skip install entirely (when re-running in the same venv):

- `CENTAUR_SKIP_PIP=1`

## What the smoke actually runs

See `scripts/centaur_spark0_v73_smoke.sh` for the fully reproducible command sequence.
Highlights:

- `python3 -m venv ~/centaur-smoke/v73/run/venv`
- `pip install -r centaur_spec_impl_v73/requirements.txt` (numpy/scipy/scikit-learn)
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
