#!/usr/bin/env sh
set -eu

usage()
{
	cat <<'USAGE'
Spark0 Centaur spec-impl v73 smoke (runs on Spark0; no sudo).

Environment (recommended):
  CENTAUR_ZIP           Path to centaur_spec_impl_v73.zip (required)
  CENTAUR_WORKDIR       Workspace dir (default: ~/centaur-smoke/v73/run)
  CENTAUR_CATALOG_JSON  Optional path to a model-catalog JSON fixture
  CENTAUR_PIP_ARGS      Optional extra args for pip install (e.g. "--no-index --find-links=/path/to/wheels")
  CENTAUR_SKIP_PIP      Set to 1 to skip pip install (assumes venv already has deps)

Example (on Spark0):
  export CENTAUR_ZIP=~/centaur-smoke/v73/centaur_spec_impl_v73.zip
  export CENTAUR_CATALOG_JSON=~/centaur-smoke/v73/unit_model_catalog.json
  sh ./centaur_spark0_v73_smoke.sh | tee ~/centaur-smoke/v73/run/smoke.log

Notes:
  - Avoids large model downloads; registers only a tiny synthetic model candidate.
  - Installs numpy/scipy/scikit-learn from Centaur requirements; ensure you have network or cached wheels.
USAGE
}

case "${1:-}" in
	-h|--help)
		usage
		exit 0
		;;
esac

need_cmd()
{
	if command -v "$1" >/dev/null 2>&1; then
		return 0
	fi
	echo "missing required command: $1" >&2
	exit 2
}

need_cmd python3
need_cmd unzip

if python3 -c 'import venv' >/dev/null 2>&1; then
	:
else
	echo "python3 venv module missing; on Debian/Ubuntu install python3-venv" >&2
	exit 2
fi

zip="${CENTAUR_ZIP:-}"
if [ "$zip" = "" ]; then
	echo "CENTAUR_ZIP is required" >&2
	usage >&2
	exit 2
fi
if [ ! -f "$zip" ]; then
	echo "CENTAUR_ZIP not found: $zip" >&2
	exit 2
fi

workdir="${CENTAUR_WORKDIR:-$HOME/centaur-smoke/v73/run}"
pkgdir="$workdir/centaur_spec_impl_v73"
venvdir="$workdir/venv"
ctrldir="$workdir/hyor/controller"
nodedir="$workdir/hyor/node_spark0"
publish_baseline="$workdir/hyor_publish/baseline"
publish_type="$workdir/hyor_publish/node_type_default"
effective_out="$workdir/hyor_effective/spark0"
catalog_json="${CENTAUR_CATALOG_JSON:-}"

mkdir -p "$workdir" "$ctrldir" "$nodedir" "$publish_baseline" "$publish_type" "$effective_out"

echo "== centaur v73 smoke (spark0) =="
echo "zip: $zip"
echo "workdir: $workdir"

echo "== python =="
python3 -V
python3 -c 'import sys,platform; print("executable:",sys.executable); print("platform:",platform.platform())'

echo "== unpack centaur =="
rm -rf "$pkgdir"
unzip -q "$zip" -d "$workdir"
if [ ! -f "$pkgdir/centaur.py" ]; then
	echo "expected $pkgdir/centaur.py after unzip" >&2
	exit 2
fi

echo "== venv =="
python3 -m venv "$venvdir"
venv_py="$venvdir/bin/python3"
if [ ! -x "$venv_py" ]; then
	echo "expected venv python: $venv_py" >&2
	exit 2
fi

echo "== pip install (centaur requirements) =="
"$venv_py" -m pip -V
if [ "${CENTAUR_SKIP_PIP:-0}" = "1" ]; then
	echo "skipping pip install (CENTAUR_SKIP_PIP=1)"
else
	pip_args="${CENTAUR_PIP_ARGS:-}"
	if [ "$pip_args" = "" ]; then
		"$venv_py" -m pip install -r "$pkgdir/requirements.txt"
	else
		"$venv_py" -m pip install $pip_args -r "$pkgdir/requirements.txt"
	fi
fi

echo "== centaur package facts =="
ls -la "$pkgdir" | sed -n '1,20p'
sha256="$(python3 - <<PY
import hashlib,sys
p=sys.argv[1]
h=hashlib.sha256()
with open(p,'rb') as f:
    h.update(f.read())
print(h.hexdigest())
PY
"$zip")"
echo "zip_sha256: $sha256"

echo "== pip freeze (sanitized) =="
"$venv_py" -m pip freeze | sed -E 's@file://[^ ]+@file://REDACTED@g'

centaur()
{
	"$venv_py" -u "$pkgdir/centaur.py" "$@"
}

echo "== centaur selftest =="
"$venv_py" -m py_compile "$pkgdir/centaur.py" "$pkgdir/tests/test_centaur.py"
centaur selftest --json

echo "== hyor: init controller/node workspaces =="
centaur hyor-sync-init "$ctrldir" --node-id spark0 --node-type default --right-peer-root "$nodedir" --broadcast-peer-root "$nodedir"
centaur hyor-sync-init "$nodedir" --node-id spark0 --node-type default --left-peer-root "$ctrldir" --broadcast-peer-root "$ctrldir"
centaur hyor-sync-status "$ctrldir"
centaur hyor-sync-status "$nodedir"

echo "== hyor: publish baseline + node_type =="
printf "baseline\n" >"$publish_baseline/baseline.txt"
printf "node-type\n" >"$publish_type/model.txt"
centaur hyor-sync-publish "$ctrldir" baseline "$publish_baseline" --label spark0-v73-smoke
centaur hyor-sync-publish "$ctrldir" node_type "$publish_type" --selector default --label spark0-v73-smoke

echo "== hyor: ring-step (metadata) =="
centaur hyor-ring-step "$ctrldir" --node-id spark0 --node-type default --right-peer-root "$nodedir" --scope metadata
centaur hyor-ring-step "$nodedir" --node-id spark0 --node-type default --left-peer-root "$ctrldir" --scope metadata

echo "== hyor: ring-step (effective) =="
centaur hyor-ring-step "$ctrldir" --node-id spark0 --node-type default --right-peer-root "$nodedir" --scope effective
centaur hyor-ring-step "$nodedir" --node-id spark0 --node-type default --left-peer-root "$ctrldir" --scope effective

echo "== hyor: effective + apply (node view) =="
centaur hyor-sync-effective "$nodedir" spark0 --node-type default --output "$workdir/hyor_effective_manifest_spark0.json"
centaur hyor-sync-apply "$nodedir" spark0 --node-type default --output-dir "$effective_out" --clean
ls -la "$effective_out" | sed -n '1,40p'

echo "== hyor: agent config write (no internet; no executor) =="
centaur hyor-agent-config-write "$nodedir" --node-id spark0 --node-type default --controller-root "$ctrldir" --effective-output-dir "$effective_out" --allow-no-executor --no-internet --announce-before-poll --sync-before-poll --sync-after-poll --ring-scope metadata --notes spark0-v73-smoke --force
centaur hyor-agent-config "$nodedir" --full

echo "== hyor: node announce + runtime init =="
centaur hyor-node-announce "$nodedir" --controller-root "$ctrldir"
centaur hyor-node-announcements "$ctrldir" --limit 5 --full
centaur hyor-runtime-init "$ctrldir" --force
centaur hyor-runtime "$ctrldir" --full

echo "== hyor: agent step (expected to be idle) =="
centaur hyor-agent-step "$nodedir" --controller-root "$ctrldir"

echo "== hyor: provider + model catalog registration (no downloads) =="
if [ "$catalog_json" = "" ]; then
	catalog_json="$workdir/unit_model_catalog.json"
	cat >"$catalog_json" <<'EOF'
{
  "models": [
    {
      "model_id": "unit/test-model",
      "display_name": "unit test model (no weights)",
      "model_class": "code",
      "access_mode": "download",
      "context_tokens": 1024,
      "strengths": ["code_edit"],
      "weaknesses": [],
      "install_methods": ["manual"],
      "notes": "Synthetic catalog entry for Spark0 v73 smoke; no downloads."
    }
  ]
}
EOF
fi
centaur hyor-provider-register "$ctrldir" unit --kind open_source_catalog --catalog-url "$catalog_json" --notes spark0-v73-smoke --force
centaur hyor-model-catalog-import "$ctrldir" unit "$catalog_json" --default-model-class code --default-access-mode download --default-strength code_edit --force
centaur hyor-model-catalog "$ctrldir" --full

echo "== hyor: benchmark suite + record + results =="
centaur hyor-benchmark-suite-register "$ctrldir" spark0_smoke_suite --task-type code_edit --model-class code --metric quality_score --metric cost_score --notes spark0-v73-smoke --force

catalog_key="$(centaur hyor-model-catalog "$ctrldir" --full | "$venv_py" - <<'PY'
import json,sys
data=json.load(sys.stdin)
matches=data.get("matches") or []
if not matches:
    print("")
    sys.exit(0)
print(matches[0].get("catalog_key",""))
PY
)"
if [ "$catalog_key" = "" ]; then
	echo "failed to resolve catalog_key from hyor-model-catalog output" >&2
	exit 2
fi
centaur hyor-benchmark-record "$ctrldir" "$catalog_key" spark0_smoke_suite spark0 unit/test-model --status success --quality-score 0.50 --cost-score 0.50 --input-tokens-per-second 0 --output-tokens-per-second 0 --latency-ms 0 --memory-gib 0 --tokens-in 1 --tokens-out 1 --notes spark0-v73-smoke
centaur hyor-benchmark-results "$ctrldir" --catalog-key "$catalog_key" --suite-id spark0_smoke_suite --limit 10 --full

echo "== hyor: dashboard =="
centaur hyor-dashboard "$ctrldir" --output-dir "$workdir/hyor_dashboard" --print-snapshot --full
ls -la "$workdir/hyor_dashboard" | sed -n '1,40p'

echo "== done =="
echo "workdir: $workdir"
