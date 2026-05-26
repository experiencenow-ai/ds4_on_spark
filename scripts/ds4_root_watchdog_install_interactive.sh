#!/usr/bin/env bash
set -euo pipefail

repo_dir="$(CDPATH= cd -- "$(dirname -- "$0")/.." && pwd)"
nodes=("$@")
if [ "${#nodes[@]}" -eq 0 ]
then
	nodes=(spark0 spark1 spark2 spark3 spark4 spark5 spark6 spark7)
fi

restore_tty()
{
	stty echo 2>/dev/null || true
}
trap restore_tty EXIT INT TERM

if [ "${DS4_SUDO_PASSWORD:-}" = "" ]
then
	cat >&2 <<'EOF'
This installer first uses normal ssh/scp access to copy the payload.
When root install starts, each reachable Spark will show a normal remote sudo prompt.
Type that Spark account password at the sudo prompt when it appears.
EOF
	DS4_REMOTE_SUDO_TTY=1 DS4_RESCUE_ROOT=1 "$repo_dir/scripts/ds4_deploy_rescue_agent.sh" "${nodes[@]}"
else
	DS4_RESCUE_ROOT=1 "$repo_dir/scripts/ds4_deploy_rescue_agent.sh" "${nodes[@]}"
fi
