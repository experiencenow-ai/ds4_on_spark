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

printf 'Remote sudo password for Spark accounts: ' >&2
stty -echo
IFS= read -r sudo_password
stty echo
printf '\n' >&2

DS4_SUDO_PASSWORD="$sudo_password" DS4_RESCUE_ROOT=1 "$repo_dir/scripts/ds4_deploy_rescue_agent.sh" "${nodes[@]}"
