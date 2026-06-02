#!/usr/bin/env bash
set -euo pipefail

usage()
{
	cat >&2 <<'EOF'
usage: scripts/spark_sync_standard_repos.sh [--check] [spark0 spark1 ...]

Verifies or updates the standard Spark repo set:
  $HOME/src/ds4_on_spark
  $HOME/src/centaur
  $HOME/src/vllm
  $HOME/src/trimind-brain
  $HOME/src/web

Each repo must exist, be on main, and be clean. Sync mode runs:
  git fetch --prune origin main
  git pull --ff-only origin main
EOF
	exit 2
}

mode="sync"
if [ "${1:-}" = "-h" ] || [ "${1:-}" = "--help" ]; then
	usage
fi
if [ "${1:-}" = "--check" ]; then
	mode="check"
	shift
fi

nodes=("$@")
if [ "${DS4_STANDARD_REPOS:-}" != "" ]; then
	IFS=',' read -r -a repos <<<"$DS4_STANDARD_REPOS"
else
	repos=(ds4_on_spark centaur vllm trimind-brain web)
fi
if [ "${#nodes[@]}" -eq 0 ]; then
	nodes=(spark0 spark1 spark2 spark3 spark4 spark5 spark6 spark7)
fi

ssh_cmd()
{
	local host="$1"
	shift
	ssh -o BatchMode=yes -o ConnectTimeout=8 "$host" "$@"
}

for node in "${nodes[@]}"
do
	echo "==> $node"
	ssh_cmd "$node" "MODE='$mode' bash -s" "${repos[@]}" <<'REMOTE'
set -euo pipefail
mode="$MODE"
shift 0
for repo_name in "$@"
do
	repo="$HOME/src/$repo_name"
	if [ ! -d "$repo/.git" ]; then
		echo "missing canonical repo: $repo" >&2
		exit 20
	fi
	cd "$repo"
	branch="$(git branch --show-current)"
	if [ "$branch" != "main" ]; then
		echo "repo is not on main: $repo branch=$branch" >&2
		exit 21
	fi
	if [ -n "$(git status --porcelain)" ]; then
		echo "dirty canonical repo: $repo" >&2
		git status --short >&2
		exit 22
	fi
	if [ "$mode" = "sync" ]; then
		git fetch --prune origin main >/dev/null
		git pull --ff-only origin main >/dev/null
	fi
	printf '%s branch=main head=%s\n' "$repo_name" "$(git rev-parse --short HEAD)"
done
REMOTE
done
