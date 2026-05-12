#!/usr/bin/env sh
set -eu

usage()
{
	cat <<'USAGE'
usage: centaur_spark12_v73_stage.sh <spark1_user@host> <spark2_user@host> [remote_dir]

Convenience wrapper to stage Centaur spec-impl v73 zip to both Spark1 and
Spark2 using `scripts/centaur_spark_v73_stage.sh`.

Environment:
  CENTAUR_ZIP             Local zip path (default: /Users/mac/Downloads/centaur_spec_impl_v73.zip)
  CENTAUR_CATALOG_FIXTURE Optional local JSON path to stage as unit_model_catalog.json
  SSH_OPTS                Optional ssh options override (passed through)
  STAGE_SKIP_PREFLIGHT    Set to 1 to skip SSH preflight checks

Example:
  ./scripts/centaur_spark12_v73_stage.sh spark1@<spark1-host> spark2@<spark2-host> "~/centaur-smoke/v73"
USAGE
}

case "${1:-}" in
	-h|--help|"")
		usage
		exit 2
		;;
esac

if [ "${2:-}" = "" ]; then
	usage >&2
	exit 2
fi

spark1="$1"
spark2="$2"
remote_dir="${3:-}"

root="$(CDPATH= cd -- "$(dirname -- "$0")/.." && pwd)"
stage="$root/scripts/centaur_spark_v73_stage.sh"
if [ ! -x "$stage" ]; then
	echo "missing stage script: $stage" >&2
	exit 2
fi

if [ "${SSH_OPTS:-}" = "" ]; then
	known_hosts="/tmp/ds4_spark_known_hosts"
	if [ -d "/private/tmp" ]; then
		known_hosts="/private/tmp/ds4_spark_known_hosts"
	fi
	SSH_OPTS="-o BatchMode=yes -o ConnectTimeout=10 -o StrictHostKeyChecking=accept-new -o UserKnownHostsFile=$known_hosts"
fi
export SSH_OPTS

ssh_preflight()
{
	t="$1"
	if ssh $SSH_OPTS "$t" "true" >/dev/null 2>&1; then
		echo "preflight: ssh ok: $t"
		return 0
	fi
	echo "preflight: ssh failed: $t" >&2
	echo "hint: check DNS/SSH reachability and keys; try:" >&2
	echo "  REDACT=1 ./scripts/mac_spark_discovery.sh $(printf "%s" "$t" | sed 's/^[^@]*@//')" >&2
	return 1
}

if [ "${STAGE_SKIP_PREFLIGHT:-0}" != "1" ]; then
	echo "== stage preflight ssh =="
	ssh_preflight "$spark1" || exit 21
	ssh_preflight "$spark2" || exit 22
else
	echo "== skip preflight (STAGE_SKIP_PREFLIGHT=1) =="
fi

if [ "$remote_dir" = "" ]; then
	"$stage" "$spark1"
	"$stage" "$spark2"
else
	"$stage" "$spark1" "$remote_dir"
	"$stage" "$spark2" "$remote_dir"
fi
