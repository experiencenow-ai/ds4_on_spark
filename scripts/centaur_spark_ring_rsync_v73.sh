#!/usr/bin/env sh
set -eu

usage()
{
	cat <<'USAGE'
Centaur v73 ring-step coordinator using rsync staging.

This runs on Spark0 (or any orchestrator host that can SSH to the other Sparks)
and works around the Centaur constraint that `hyor-ring-step` requires local,
writable peer roots. It does this by:

  1) Maintaining local working copies of node roots for spark0..sparkN
  2) Running ring-step locally across those roots
  3) rsync'ing the mutated node roots back to remote Sparks

Inputs:
  - You must already have Centaur extracted + venv on the orchestrator host.
    The Spark0 v73 smoke (`scripts/centaur_spark0_v73_smoke.sh`) creates:
      ~/centaur-smoke/v73/run/centaur_spec_impl_v73
      ~/centaur-smoke/v73/run/venv

Usage:
  centaur_spark_ring_rsync_v73.sh [--remote-base <dir>] <spark1_user@host> [spark2_user@host ...]

Environment:
  CENTAUR_ROOT     Extracted Centaur dir containing centaur.py
                  (default: ~/centaur-smoke/v73/run/centaur_spec_impl_v73)
  CENTAUR_VENV     Centaur venv dir containing bin/python3
                  (default: ~/centaur-smoke/v73/run/venv)
  RING_WORKDIR     Local orchestrator workdir (default: ~/centaur-smoke/v73/ring_rsync)
  RING_RUN_ID      Optional run id (writes under RING_WORKDIR/run/<run_id>)
  RING_LOG         Optional log path (duplicates stdout/stderr via tee)
  NODE_TYPE        Node type label (default: default)
  RING_APPLY       If set to 1, also run `hyor-sync-apply` locally for remote
                  Sparks and rsync the materialized effective dirs back.
  RING_TRACE       Set to 1 to enable shell tracing
  SSH_OPTS         Optional ssh options override (default includes BatchMode + temp known_hosts)

Notes:
  - No sudo/service changes.
  - Host order defines ring order after local spark0: spark1, spark2, ...
  - remote_base should be a dedicated Centaur ring directory (safe to rsync --delete).
USAGE
}

remote_base=""
while [ $# -gt 0 ]; do
	case "$1" in
		--remote-base)
			remote_base="${2:-}"
			shift 2
			;;
		-h|--help)
			usage
			exit 0
			;;
		*)
			break
			;;
	esac
done

if [ "$#" -lt 1 ]; then
	usage >&2
	exit 2
fi

remote_count="$#"
node_count=$((remote_count + 1))
i=1
while [ "$#" -gt 0 ]; do
	eval "remote_target_$i=\$1"
	i=$((i + 1))
	shift
done

if [ "$remote_base" = "" ]; then
	remote_base="~/centaur-smoke/v73/ring_node"
fi

centaur_root="${CENTAUR_ROOT:-$HOME/centaur-smoke/v73/run/centaur_spec_impl_v73}"
venv_dir="${CENTAUR_VENV:-$HOME/centaur-smoke/v73/run/venv}"
base_workdir="${RING_WORKDIR:-$HOME/centaur-smoke/v73/ring_rsync}"
run_id="${RING_RUN_ID:-}"
if [ "$run_id" = "" ]; then
	workdir="$base_workdir"
else
	workdir="$base_workdir/run/$run_id"
fi
node_type="${NODE_TYPE:-default}"

need_cmd()
{
	if command -v "$1" >/dev/null 2>&1; then
		return 0
	fi
	echo "missing required command: $1" >&2
	exit 2
}

need_cmd ssh
need_cmd rsync
if [ "${RING_LOG:-}" != "" ]; then
	need_cmd tee
	need_cmd mkfifo
	need_cmd dirname
fi

if [ ! -f "$centaur_root/centaur.py" ]; then
	echo "missing centaur.py under CENTAUR_ROOT: $centaur_root" >&2
	exit 2
fi
py="$venv_dir/bin/python3"
if [ ! -x "$py" ]; then
	echo "missing venv python3 under CENTAUR_VENV: $venv_dir" >&2
	exit 2
fi

if [ "${SSH_OPTS:-}" = "" ]; then
	known_hosts="/tmp/ds4_spark_known_hosts"
	if [ -d "/private/tmp" ]; then
		known_hosts="/private/tmp/ds4_spark_known_hosts"
	fi
	SSH_OPTS="-o BatchMode=yes -o ConnectTimeout=10 -o StrictHostKeyChecking=accept-new -o UserKnownHostsFile=$known_hosts"
fi

if [ "${RING_TRACE:-0}" = "1" ]; then
	set -x
fi

log="${RING_LOG:-}"
if [ "$log" != "" ]; then
	mkdir -p "$(dirname -- "$log")"
	fifo="$workdir/.centaur_ring_rsync_log.fifo"
	rm -f "$fifo"
	mkdir -p "$workdir"
	mkfifo "$fifo"
	exec 3>&1 4>&2
	tee "$log" <"$fifo" &
	teepid="$!"
	cleanup_log()
	{
		exec >&3 2>&4
		rm -f "$fifo"
		wait "$teepid" 2>/dev/null || true
	}
	trap 'cleanup_log' EXIT INT TERM
	exec >"$fifo" 2>&1
fi

value_at()
{
	prefix="$1"
	idx="$2"
	eval "printf '%s' \"\${${prefix}_${idx}:-}\""
}

ssh_run()
{
	target="$1"
	shift
	ssh $SSH_OPTS "$target" "$@"
}

rsync_pull()
{
	target="$1"
	remote_path="$2"
	local_path="$3"
	mkdir -p "$local_path"
	rsync -av -e "ssh $SSH_OPTS" --delete "$target:$remote_path/" "$local_path/"
}

rsync_push()
{
	local_path="$1"
	target="$2"
	remote_path="$3"
	ssh_run "$target" "mkdir -p $remote_path"
	rsync -av -e "ssh $SSH_OPTS" --delete "$local_path/" "$target:$remote_path/"
}

centaur()
{
	"$py" -u "$centaur_root/centaur.py" "$@"
}

left_index()
{
	idx="$1"
	echo $(((idx + node_count - 1) % node_count))
}

right_index()
{
	idx="$1"
	echo $(((idx + 1) % node_count))
}

ctrl="$workdir/controller"
i=0
while [ "$i" -lt "$node_count" ]; do
	eval "s$i=\$workdir/spark$i"
	eval "remote_root_$i=\$remote_base/hyor/node_spark$i"
	i=$((i + 1))
done

echo "== centaur v73 ring rsync step =="
echo "workdir: $workdir"
echo "centaur_root: $centaur_root"
echo "venv_dir: $venv_dir"
echo "node_type: $node_type"
echo "remote_base: $remote_base"
echo "node_count=$node_count"
i=1
while [ "$i" -lt "$node_count" ]; do
	echo "spark$i: $(value_at remote_target "$i")"
	i=$((i + 1))
done

echo "== centaur package facts =="
"$py" -V
decomposer_version="$("$py" -c 'import ast,sys
p=sys.argv[1]
try:
    t=open(p,"r",encoding="utf-8",errors="replace").read()
except Exception:
    print("")
    raise SystemExit(0)
try:
    m=ast.parse(t)
except Exception:
    print("")
    raise SystemExit(0)
v=""
for node in getattr(m,"body",[]):
    if isinstance(node, ast.Assign):
        for tgt in getattr(node,"targets",[]):
            if isinstance(tgt, ast.Name) and tgt.id=="DECOMPOSER_VERSION":
                val=getattr(node,"value",None)
                if isinstance(val, ast.Constant) and isinstance(val.value, str):
                    v=val.value
print(v)' "$centaur_root/centaur.py")"
if [ "$decomposer_version" = "" ]; then
	decomposer_version="(unknown)"
fi
echo "decomposer_version: $decomposer_version"

echo "== pip freeze (sanitized) =="
"$py" -m pip freeze | sed -E 's@file://[^ ]+@file://REDACTED@g'

echo "== ensure remote dirs =="
i=1
while [ "$i" -lt "$node_count" ]; do
	ssh_run "$(value_at remote_target "$i")" "mkdir -p $(value_at remote_root "$i")"
	i=$((i + 1))
done

echo "== pull remote node roots (seed) =="
i=1
while [ "$i" -lt "$node_count" ]; do
	rsync_pull "$(value_at remote_target "$i")" "$(value_at remote_root "$i")" "$(value_at s "$i")"
	i=$((i + 1))
done

mkdir -p "$ctrl" "$(value_at s 0)" "$workdir/publish/baseline" "$workdir/publish/node_type_default"

echo "== init roots (local working copies) =="
left="$(value_at s "$(left_index 0)")"
right="$(value_at s "$(right_index 0)")"
set -- hyor-sync-init "$ctrl" --node-id spark0 --node-type "$node_type" --left-peer-root "$left" --right-peer-root "$right"
i=1
while [ "$i" -lt "$node_count" ]; do
	set -- "$@" --broadcast-peer-root "$(value_at s "$i")"
	i=$((i + 1))
done
centaur "$@"

i=0
while [ "$i" -lt "$node_count" ]; do
	root_i="$(value_at s "$i")"
	mkdir -p "$root_i"
	left="$(value_at s "$(left_index "$i")")"
	right="$(value_at s "$(right_index "$i")")"
	centaur hyor-sync-init "$root_i" --node-id "spark$i" --node-type "$node_type" --left-peer-root "$left" --right-peer-root "$right"
	i=$((i + 1))
done

echo "== publish baseline + node_type from controller =="
printf "baseline\n" >"$workdir/publish/baseline/baseline.txt"
printf "node-type\n" >"$workdir/publish/node_type_default/model.txt"
centaur hyor-sync-publish "$ctrl" baseline "$workdir/publish/baseline" --label ring-rsync-v73
centaur hyor-sync-publish "$ctrl" node_type "$workdir/publish/node_type_default" --selector "$node_type" --label ring-rsync-v73

echo "== ring step (metadata) =="
centaur hyor-ring-step "$ctrl" --scope metadata
i=0
while [ "$i" -lt "$node_count" ]; do
	centaur hyor-ring-step "$(value_at s "$i")" --scope metadata
	i=$((i + 1))
done

echo "== ring step (effective) =="
centaur hyor-ring-step "$ctrl" --scope effective
i=0
while [ "$i" -lt "$node_count" ]; do
	centaur hyor-ring-step "$(value_at s "$i")" --scope effective
	i=$((i + 1))
done

echo "== push mutated node roots back to remote Sparks =="
i=1
while [ "$i" -lt "$node_count" ]; do
	rsync_push "$(value_at s "$i")" "$(value_at remote_target "$i")" "$(value_at remote_root "$i")"
	i=$((i + 1))
done

echo "== effective manifests (local non-controller nodes) =="
mkdir -p "$workdir/effective_manifests"
i=1
while [ "$i" -lt "$node_count" ]; do
	centaur hyor-sync-effective "$(value_at s "$i")" "spark$i" --node-type "$node_type" --output "$workdir/effective_manifests/hyor_effective_manifest_spark$i.json"
	i=$((i + 1))
done

if [ "${RING_APPLY:-}" = "1" ]; then
	echo "== optional: effective apply + push (RING_APPLY=1) =="
	i=1
	while [ "$i" -lt "$node_count" ]; do
		mkdir -p "$workdir/effective/spark$i"
		centaur hyor-sync-apply "$(value_at s "$i")" "spark$i" --node-type "$node_type" --output-dir "$workdir/effective/spark$i" --clean
		rsync_push "$workdir/effective/spark$i" "$(value_at remote_target "$i")" "$remote_base/effective_spark$i"
		i=$((i + 1))
	done
fi

echo "== done =="
echo "workdir: $workdir"
