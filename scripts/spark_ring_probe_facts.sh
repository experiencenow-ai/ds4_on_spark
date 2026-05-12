#!/usr/bin/env sh
set -eu

usage()
{
	cat <<'EOF'
usage: spark_ring_probe_facts.sh [--stamp YYYY-MM-DDTHHMMZ] [host...]

Runs commit-safe per-node hardware/toolchain probes (`spark_probe.sh` facts-only)
and writes one output file per target:
  docs/spark-ring-node-facts-<host>-<stamp>.md

Defaults:
  - Targets: aitopatom-9ab9.local spark1.local spark2.local
  - REDACT=1
  - SPARK_KNOWN_HOSTS_PER_HOST=1

Environment:
  STAMP               Override stamp (default: date -u +%Y-%m-%dT%H%MZ)
  DOCS_DIR            Output directory (default: docs)
  REDACT              Redact IP/MAC/GPU UUID tokens (default: 1)
  SPARK_SSH_USER      Default SSH user for host-only args (default: spark0)
  SPARK_KNOWN_HOSTS_PER_HOST   Default: 1
  DS4_GIT_DIR/DS4_GIT_WORK_TREE Optional git hash source for probe meta

Examples:
  REDACT=1 ./scripts/spark_ring_probe_facts.sh aitopatom-9ab9.local spark1.local spark2.local
  STAMP=2026-05-12T0500Z REDACT=1 ./scripts/spark_ring_probe_facts.sh spark1.local
EOF
}

stamp_arg=""
while [ $# -gt 0 ]; do
	case "$1" in
		--stamp)
			stamp_arg="${2:-}"
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

DOCS_DIR="${DOCS_DIR:-docs}"
REDACT="${REDACT:-1}"
SPARK_SSH_USER="${SPARK_SSH_USER:-spark0}"
SPARK_KNOWN_HOSTS_PER_HOST="${SPARK_KNOWN_HOSTS_PER_HOST:-1}"

if [ "$stamp_arg" != "" ]; then
	stamp="$stamp_arg"
elif [ "${STAMP:-}" != "" ]; then
	stamp="$STAMP"
else
	stamp="$(date -u +%Y-%m-%dT%H%MZ)"
fi

targets="$*"
if [ "$targets" = "" ]; then
	targets="aitopatom-9ab9.local spark1.local spark2.local"
fi

mkdir -p "$DOCS_DIR"

echo "stamp: $stamp"
echo "targets: $targets"
echo "docs dir: $DOCS_DIR"
echo "REDACT: $REDACT"
echo "SPARK_SSH_USER: $SPARK_SSH_USER"
echo "SPARK_KNOWN_HOSTS_PER_HOST: $SPARK_KNOWN_HOSTS_PER_HOST"
echo

for host in $targets; do
	host_only="${host#*@}"
	safe_h="$(printf "%s" "$host_only" | sed -E 's/[^A-Za-z0-9_.-]/_/g')"
	out="${DOCS_DIR}/spark-ring-node-facts-${safe_h}-${stamp}.md"
	echo "writing: $out"
	(SPARK_SSH_USER="$SPARK_SSH_USER" REDACT="$REDACT" SPARK_PROBE_FACTS=1 SPARK_KNOWN_HOSTS_PER_HOST="$SPARK_KNOWN_HOSTS_PER_HOST" ./scripts/spark_probe.sh "$host_only" || true) >"$out"
done

echo
echo "done"

