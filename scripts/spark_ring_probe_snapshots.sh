#!/usr/bin/env sh
set -eu

usage()
{
	cat <<'EOF'
usage: spark_ring_probe_snapshots.sh [--stamp YYYY-MM-DDTHHMMZ] [--topology ring|full] [host...]

Mac-side wrapper that produces a commit-safe (REDACT=1) snapshot set for Spark ring bring-up:
  - docs/spark-ring-mac-discovery-<stamp>.md
  - docs/spark-ring-probe-<stamp>.md
  - docs/spark-ring-mtu-probe-<stamp>.md
  - docs/spark-ring-bw-probe-<stamp>.md
  - docs/spark0-probe-facts-<stamp>.md

Defaults:
  - Targets: aitopatom-9ab9.local spark1.local spark2.local
  - Topology: ring
  - REDACT=1 (recommended for committed output)

Environment:
  STAMP               Override stamp (default: date -u +%Y-%m-%dT%H%MZ)
  DOCS_DIR            Output directory (default: docs)
  REDACT              Redact IP/MAC/GPU UUID tokens (default: 1)
  SPARK_SSH_USER      Default SSH user for host-only args (default: spark0)
  SPARK_KNOWN_HOSTS_PER_HOST   Default: 1
  DS4_GIT_DIR/DS4_GIT_WORK_TREE Optional git hash source for probe meta
  BW_MB               Bandwidth probe payload size (default: 16)
  SKIP_MTU=1          Skip MTU DF-ping snapshot
  SKIP_BW=1           Skip bandwidth smoke snapshot
  SKIP_SPARK0_FACTS=1 Skip Spark0 facts-only probe snapshot

Examples:
  DS4_GIT_DIR=.codex_git DS4_GIT_WORK_TREE=. ./scripts/spark_ring_probe_snapshots.sh
  REDACT=1 SPARK_KNOWN_HOSTS_PER_HOST=1 DS4_GIT_DIR=.codex_git DS4_GIT_WORK_TREE=. ./scripts/spark_ring_probe_snapshots.sh --topology full
  STAMP=2026-05-11T2324Z ./scripts/spark_ring_probe_snapshots.sh aitopatom-9ab9.local
EOF
}

stamp_arg=""
topology="ring"
while [ $# -gt 0 ]; do
	case "$1" in
		--stamp)
			stamp_arg="${2:-}"
			shift 2
			;;
		--topology)
			topology="${2:-}"
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

case "$topology" in
	ring|full)
		;;
	*)
		echo "invalid --topology: $topology (expected ring|full)" >&2
		exit 2
		;;
esac

DOCS_DIR="${DOCS_DIR:-docs}"
REDACT="${REDACT:-1}"
SPARK_SSH_USER="${SPARK_SSH_USER:-spark0}"
SPARK_KNOWN_HOSTS_PER_HOST="${SPARK_KNOWN_HOSTS_PER_HOST:-1}"
BW_MB="${BW_MB:-16}"

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

if [ "${DS4_GIT_DIR:-}" = "" ] && [ -d .codex_git ] && [ -r .codex_git/HEAD ]; then
	DS4_GIT_DIR=".codex_git"
	DS4_GIT_WORK_TREE="."
	export DS4_GIT_DIR DS4_GIT_WORK_TREE
fi

mkdir -p "$DOCS_DIR"

mac_out="${DOCS_DIR}/spark-ring-mac-discovery-${stamp}.md"
ring_out="${DOCS_DIR}/spark-ring-probe-${stamp}.md"
mtu_out="${DOCS_DIR}/spark-ring-mtu-probe-${stamp}.md"
bw_out="${DOCS_DIR}/spark-ring-bw-probe-${stamp}.md"
spark0_facts_out="${DOCS_DIR}/spark0-probe-facts-${stamp}.md"

echo "stamp: $stamp"
echo "targets: $targets"
echo "topology: $topology"
echo "docs dir: $DOCS_DIR"
echo "REDACT: $REDACT"
echo "SPARK_SSH_USER: $SPARK_SSH_USER"
echo "SPARK_KNOWN_HOSTS_PER_HOST: $SPARK_KNOWN_HOSTS_PER_HOST"
echo

echo "writing: $mac_out"
REDACT="$REDACT" ./scripts/mac_spark_discovery.sh $targets >"$mac_out"

ring_args=""
if [ "$topology" = "full" ]; then
	ring_args="--topology full"
fi
echo "writing: $ring_out"
(SPARK_SSH_USER="$SPARK_SSH_USER" REDACT="$REDACT" SPARK_KNOWN_HOSTS_PER_HOST="$SPARK_KNOWN_HOSTS_PER_HOST" ./scripts/spark_ring_probe.sh $ring_args $targets || true) >"$ring_out"

if [ "${SKIP_MTU:-0}" != "1" ]; then
	echo "writing: $mtu_out"
	(SPARK_SSH_USER="$SPARK_SSH_USER" REDACT="$REDACT" SPARK_KNOWN_HOSTS_PER_HOST="$SPARK_KNOWN_HOSTS_PER_HOST" ./scripts/spark_ring_probe_mtu.sh --topology full $targets || true) >"$mtu_out"
else
	echo "skip: mtu probe (SKIP_MTU=1)"
fi

if [ "${SKIP_BW:-0}" != "1" ]; then
	echo "writing: $bw_out"
	(BW_MB="$BW_MB" SPARK_SSH_USER="$SPARK_SSH_USER" REDACT="$REDACT" SPARK_KNOWN_HOSTS_PER_HOST="$SPARK_KNOWN_HOSTS_PER_HOST" ./scripts/spark_ring_probe_bw.sh $targets || true) >"$bw_out"
else
	echo "skip: bw probe (SKIP_BW=1)"
fi

if [ "${SKIP_SPARK0_FACTS:-0}" != "1" ]; then
	echo "writing: $spark0_facts_out"
	(SPARK_SSH_USER="$SPARK_SSH_USER" REDACT="$REDACT" SPARK_PROBE_FACTS=1 SPARK_KNOWN_HOSTS_PER_HOST="$SPARK_KNOWN_HOSTS_PER_HOST" ./scripts/spark_probe.sh aitopatom-9ab9.local || true) >"$spark0_facts_out"
else
	echo "skip: spark0 facts (SKIP_SPARK0_FACTS=1)"
fi

echo
echo "done"
