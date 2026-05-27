#!/usr/bin/env bash
set -euo pipefail

usage()
{
	cat >&2 <<'EOF'
usage: scripts/ds4_update_spark_nodes.sh [spark0 spark1 ...]

Updates reachable Spark nodes to the current merged DS4 repo ref, then installs
the current rescue/watchdog payload and the spark4/spark5 local DSV4 service
units.

Important environment knobs:
  DS4_UPDATE_REF=origin/main        git ref to deploy on each Spark checkout
  DS4_REMOTE_REPO=$HOME/ds4_on_spark remote repo path on each Spark
  DS4_FORCE_RESET=0                set 1 to reset dirty remote checkouts
  DS4_INSTALL_RESCUE=1             rerun scripts/ds4_deploy_rescue_agent.sh
  DS4_RESCUE_ROOT=1                install root watchdog while deploying rescue
  DS4_EXTEND_SWAP=1                install survival swap while deploying rescue
  DS4_INSTALL_DSV4_LOCAL=1         install spark4/spark5 local vLLM units
  DS4_RESTART_DSV4=0               set 1 to restart spark5 worker then spark4 head
  DS4_DSV4_KV_OFFLOAD_SIZE=4       recovery-safe total GiB for spark4+spark5
EOF
	exit 2
}

if [ "${1:-}" = "-h" ] || [ "${1:-}" = "--help" ]; then
	usage
fi

repo_dir=$(CDPATH= cd -- "$(dirname -- "$0")/.." && pwd)
nodes=("$@")
if [ "${#nodes[@]}" -eq 0 ]; then
	nodes=(spark0 spark1 spark2 spark3 spark4 spark5 spark6 spark7)
fi

remote_repo="${DS4_REMOTE_REPO:-}"
update_remote="${DS4_UPDATE_REMOTE:-origin}"
update_branch="${DS4_UPDATE_BRANCH:-main}"
update_ref="${DS4_UPDATE_REF:-origin/main}"
force_reset="${DS4_FORCE_RESET:-0}"
skip_unreachable="${DS4_SKIP_UNREACHABLE:-1}"
connect_timeout="${DS4_CONNECT_TIMEOUT:-8}"
ssh_opts="${DS4_SSH_OPTS:-}"
scp_opts="${DS4_SCP_OPTS:-$ssh_opts}"
install_rescue="${DS4_INSTALL_RESCUE:-1}"
install_dsv4_local="${DS4_INSTALL_DSV4_LOCAL:-1}"
restart_dsv4="${DS4_RESTART_DSV4:-0}"
dsv4_kv_offload_size="${DS4_DSV4_KV_OFFLOAD_SIZE:-4}"
dsv4_persist_store="${DS4_DSV4_PERSIST_STORE:-/var/tmp/ds4_hma_store/dsv4/simple_cpu_offload}"
dsv4_persist_strict="${DS4_DSV4_PERSIST_STRICT:-1}"
dsv4_pythonhashseed="${DS4_DSV4_PYTHONHASHSEED:-0}"

ssh_cmd()
{
	local host="$1"
	shift
	ssh $ssh_opts -o BatchMode=yes -o ConnectTimeout="$connect_timeout" "$host" "$@"
}

scp_cmd()
{
	scp $scp_opts "$@"
}

node_is_selected()
{
	local wanted="$1"
	local node
	for node in "${reachable[@]}"
	do
		if [ "$node" = "$wanted" ]; then
			return 0
		fi
	done
	return 1
}

update_remote_repo()
{
	local host="$1"
	echo "==> $host: update $remote_repo to $update_ref"
	ssh_cmd "$host" \
		"DS4_REMOTE_REPO='$remote_repo' DS4_UPDATE_REMOTE='$update_remote' DS4_UPDATE_BRANCH='$update_branch' DS4_UPDATE_REF='$update_ref' DS4_FORCE_RESET='$force_reset' bash -s" <<'REMOTE'
set -euo pipefail
repo="${DS4_REMOTE_REPO:-$HOME/ds4_on_spark}"
remote="$DS4_UPDATE_REMOTE"
branch="$DS4_UPDATE_BRANCH"
ref="$DS4_UPDATE_REF"
if [ ! -d "$repo/.git" ]; then
	echo "missing repo: $repo" >&2
	exit 20
fi
cd "$repo"
git fetch --prune "$remote" "$branch"
if [ "$DS4_FORCE_RESET" = "1" ]; then
	git checkout "$branch" 2>/dev/null || git checkout -b "$branch" "$ref"
	git reset --hard "$ref"
else
	if [ -n "$(git status --porcelain)" ]; then
		echo "dirty remote checkout; set DS4_FORCE_RESET=1 to reset $repo" >&2
		git status --short >&2
		exit 21
	fi
	git checkout "$branch"
	git merge --ff-only "$ref"
fi
git rev-parse --short HEAD
REMOTE
}

write_dsv4_env()
{
	local host="$1"
	ssh_cmd "$host" 'mkdir -p "$HOME/.config/ds4"; cat > "$HOME/.config/ds4/dsv4-spark45.env"' <<EOF
# Written by ds4_update_spark_nodes.sh.
# Recovery default: keep the DSV4 CPU KV offload pool small enough that sshd
# and systemd remain reachable. Raise this after a stable boot if needed.
DS4_DSV4_KV_OFFLOAD_SIZE=$dsv4_kv_offload_size
DS4_DSV4_PERSIST_STORE=$dsv4_persist_store
DS4_DSV4_PERSIST_STRICT=$dsv4_persist_strict
DS4_DSV4_PYTHONHASHSEED=$dsv4_pythonhashseed
EOF
}

install_dsv4_unit()
{
	local host="$1"
	local unit="$2"
	echo "==> $host: install $unit"
	ssh_cmd "$host" 'mkdir -p "$HOME/.config/systemd/user"'
	scp_cmd "$repo_dir/v2/deploy/systemd-user/$unit" "$host:.config/systemd/user/$unit"
	write_dsv4_env "$host"
	ssh_cmd "$host" "systemctl --user daemon-reload; systemctl --user enable '$unit'; systemctl --user --no-pager --plain status '$unit' | sed -n '1,8p' || true"
}

reachable=()
for node in "${nodes[@]}"
do
	echo "==> $node: probe ssh"
	if ssh_cmd "$node" 'printf ok' >/dev/null 2>&1; then
		reachable+=("$node")
	else
		echo "WARN: $node is unreachable"
		if [ "$skip_unreachable" != "1" ]; then
			exit 10
		fi
	fi
done

if [ "${#reachable[@]}" -eq 0 ]; then
	echo "no reachable nodes" >&2
	exit 11
fi

for node in "${reachable[@]}"
do
	update_remote_repo "$node"
done

if [ "$install_rescue" = "1" ]; then
	echo "==> reinstall rescue/watchdog payload on reachable nodes"
	DS4_RESCUE_ROOT="${DS4_RESCUE_ROOT:-1}" DS4_EXTEND_SWAP="${DS4_EXTEND_SWAP:-1}" \
		"$repo_dir/scripts/ds4_deploy_rescue_agent.sh" "${reachable[@]}"
fi

if [ "$install_dsv4_local" = "1" ]; then
	if node_is_selected spark4; then
		install_dsv4_unit spark4 ds4-dsv4-local-head.service
	fi
	if node_is_selected spark5; then
		install_dsv4_unit spark5 ds4-dsv4-local-worker.service
	fi
fi

if [ "$restart_dsv4" = "1" ]; then
	if node_is_selected spark4 && node_is_selected spark5; then
		echo "==> restart DSV4 local lane: spark5 worker, then spark4 head"
		ssh_cmd spark4 'systemctl --user stop ds4-dsv4-local-head.service || true'
		ssh_cmd spark5 'systemctl --user stop ds4-dsv4-local-worker.service || true'
		ssh_cmd spark5 'systemctl --user restart ds4-dsv4-local-worker.service'
		sleep 5
		ssh_cmd spark4 'systemctl --user restart ds4-dsv4-local-head.service'
	else
		echo "WARN: DS4_RESTART_DSV4=1 requested, but spark4 and spark5 are not both reachable"
	fi
fi

echo "==> updated nodes: ${reachable[*]}"
