#!/usr/bin/env sh
set -eu

usage()
{
	cat <<'EOF'
ops_run_dir_init.sh -- initialize a private ops run directory (Mac-side)

Usage:
  ops_run_dir_init.sh [--tp tp2|tp3|tp4] [--tag <tag>] [--out <path>]

Notes:
  - Creates a run directory with restrictive permissions (umask 077).
  - Writes a starter `run.md` and prints the run directory path to stdout.
  - If `--out` already exists, a numeric suffix is appended to avoid clobber.
EOF
}

sanitize_tag()
{
	# Keep path-safe characters only; replace everything else with '_'.
	printf "%s" "$1" | tr -c 'A-Za-z0-9_.@-+' '_'
}

tp=""
tag=""
out=""

while [ $# -gt 0 ]; do
	case "$1" in
		--tp)
			tp="${2:-}"
			shift 2
			;;
		--tag)
			tag="${2:-}"
			shift 2
			;;
		--out)
			out="${2:-}"
			shift 2
			;;
		-h|--help)
			usage
			exit 0
			;;
		*)
			echo "unknown arg: $1" >&2
			usage >&2
			exit 2
			;;
	esac
done

case "$tp" in
	""|tp2|tp3|tp4)
		;;
	*)
		echo "invalid --tp: $tp (expected tp2|tp3|tp4)" >&2
		exit 2
		;;
esac

umask 077

ts="$(date -u +%Y%m%d-%H%M%SZ 2>/dev/null || date +%Y%m%d-%H%M%SZ)"
iso="$(date -u +%Y-%m-%dT%H:%M:%SZ 2>/dev/null || date)"

if [ "$out" = "" ]; then
	base="${HOME:-$PWD}/ds4_run_logs"
	suffix=""
	if [ "$tp" != "" ]; then
		suffix="${suffix}_${tp}"
	fi
	if [ "$tag" != "" ]; then
		suffix="${suffix}_$(sanitize_tag "$tag")"
	fi
	out="${base}/${ts}${suffix}"
fi

final="$out"
i=0
while [ -e "$final" ]; do
	i=$((i + 1))
	final="${out}_${i}"
done

mkdir -p "$final"

git_sha="$(git rev-parse HEAD 2>/dev/null || echo "unknown")"
git_branch="$(git rev-parse --abbrev-ref HEAD 2>/dev/null || echo "unknown")"

cat >"$final/run.md" <<EOF
# DS4 Run Notes

## Summary
- Started (UTC): $iso
- Topology: ${tp:-tp?}
- Goal:

## Inventory
- spark0:
- spark1:
- spark2:

## Code + Build
- Repo: experiencenow-ai/ds4_on_spark
- Git SHA: $git_sha
- Branch: $git_branch
- Build mode:

## Config
- DS4_WORLD_SIZE=
- DS4_RANK per host:
- DS4_RING_HOSTS=
- DS4_MASTER_ADDR=
- Interface path (wired vs Wi‑Fi):

## Commands
- Mac-side:
- Spark-side:

## Artifacts
- ops snapshot(s):
- support bundle(s):
EOF

echo "$final"
