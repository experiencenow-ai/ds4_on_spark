#!/usr/bin/env bash
set -euo pipefail

usage()
{
	cat >&2 <<'EOF'
usage: scripts/ds4_update_spark_nodes.sh [spark0 spark1 ...]

Updates DS4 on the selected Spark nodes from the canonical checkout:
  $HOME/src/ds4_on_spark

The remote checkout must exist, be on main, and be clean. The update is:
  git fetch --prune origin main
  git pull --ff-only origin main

This script is intentionally zero-drift. It installs deployment files from the
remote Spark checkout after the pull, never from the Mac working tree.

This script also disables model autoload services so experimental pipelines do
not load models on reboot. Set DS4_INSTALL_EXPERIMENTAL_MODEL_UNITS=1 only
when intentionally re-arming those units for a test.
EOF
	exit 2
}

if [ "${1:-}" = "-h" ] || [ "${1:-}" = "--help" ]; then
	usage
fi

install_experimental_model_units="${DS4_INSTALL_EXPERIMENTAL_MODEL_UNITS:-0}"
nodes=("$@")
if [ "${#nodes[@]}" -eq 0 ]; then
	nodes=(spark0 spark1 spark2 spark3 spark4 spark5 spark6 spark7)
fi

ssh_cmd()
{
	local host="$1"
	shift
	ssh -o BatchMode=yes -o ConnectTimeout=8 "$host" "$@"
}

node_is_selected()
{
	local wanted="$1"
	local node
	for node in "${nodes[@]}"
	do
		if [ "$node" = "$wanted" ]; then
			return 0
		fi
	done
	return 1
}

update_ds4_repo()
{
	local host="$1"
	echo "==> $host: update \$HOME/src/ds4_on_spark"
	ssh_cmd "$host" 'bash -s' <<'REMOTE'
set -euo pipefail
repo="$HOME/src/ds4_on_spark"
if [ ! -d "$repo/.git" ]; then
	echo "missing canonical repo: $repo" >&2
	exit 20
fi
cd "$repo"
branch="$(git symbolic-ref --short HEAD)"
if [ "$branch" != "main" ]; then
	echo "repo is not on main: $repo branch=$branch" >&2
	exit 21
fi
if [ -n "$(git status --porcelain)" ]; then
	echo "dirty canonical repo: $repo" >&2
	git status --short >&2
	exit 22
fi
git fetch --prune origin main
git pull --ff-only origin main
git rev-parse --short HEAD
REMOTE
}

write_dsv4_env()
{
	local host="$1"
	ssh_cmd "$host" 'mkdir -p "$HOME/.config/ds4"; cat > "$HOME/.config/ds4/dsv4-spark45.env"' <<'EOF'
# Written by ds4_update_spark_nodes.sh.
DS4_DSV4_KV_OFFLOAD_SIZE=4
DS4_DSV4_PERSIST_STORE=/var/tmp/ds4_hma_store/dsv4/simple_cpu_offload
DS4_DSV4_PERSIST_STRICT=1
DS4_DSV4_PYTHONHASHSEED=0
EOF
}

write_startup_models_env()
{
	local host="$1"
	ssh_cmd "$host" 'mkdir -p "$HOME/.config/ds4"; cat > "$HOME/.config/ds4/startup-models.env"' <<'EOF'
# Written by ds4_update_spark_nodes.sh.
DS4_STARTUP_BASE_URL=http://127.0.0.1:8000
EOF
}

disable_model_autoload()
{
	local host="$1"
	echo "==> $host: disable model autoload"
	ssh_cmd "$host" 'bash -s' <<'REMOTE'
set -euo pipefail
mkdir -p "$HOME/.config/ds4"
tmp="$HOME/.config/ds4/model-gateway.env.tmp"
if [ -f "$HOME/.config/ds4/model-gateway.env" ]; then
	grep -v '^DS4_RESIDENT_START=' "$HOME/.config/ds4/model-gateway.env" > "$tmp" || true
else
	: > "$tmp"
fi
printf 'DS4_RESIDENT_START=0\n' >> "$tmp"
mv "$tmp" "$HOME/.config/ds4/model-gateway.env"
for unit in \
	ds4-startup-models.service \
	ds4-model-gateway.service \
	ds4-qwen35b.service \
	ds4-dsv4-local-head.service \
	ds4-dsv4-local-worker.service \
	ds4-dsv4-vllm.service \
	ds4-dsv4-docker-legacy.service \
	ds4-dsv4-gateway.service \
	ds4-dsv4-ray-head.service \
	ds4-dsv4-ray-worker.service
do
	systemctl --user stop "$unit" >/dev/null 2>&1 || true
	systemctl --user disable "$unit" >/dev/null 2>&1 || true
done
systemctl --user reset-failed >/dev/null 2>&1 || true
systemctl --user daemon-reload
REMOTE
}

install_unit()
{
	local host="$1"
	local unit="$2"
	echo "==> $host: install $unit"
	ssh_cmd "$host" "bash -s '$unit'" <<'REMOTE'
set -euo pipefail
unit="$1"
repo="$HOME/src/ds4_on_spark"
src="$repo/v2/deploy/systemd-user/$unit"
dst="$HOME/.config/systemd/user/$unit"
if [ ! -f "$src" ]; then
	echo "missing pulled unit file: $src" >&2
	exit 30
fi
mkdir -p "$HOME/.config/systemd/user"
install -m 0644 "$src" "$dst"
systemctl --user daemon-reload
systemctl --user enable "$unit"
systemctl --user --no-pager --plain status "$unit" | sed -n '1,8p' || true
REMOTE
}

for node in "${nodes[@]}"
do
	echo "==> $node: probe ssh"
	ssh_cmd "$node" 'printf ok >/dev/null'
done

for node in "${nodes[@]}"
do
	update_ds4_repo "$node"
	write_startup_models_env "$node"
	disable_model_autoload "$node"
	if [ "$install_experimental_model_units" = "1" ]; then
		install_unit "$node" ds4-startup-models.service
	fi
done

if [ "$install_experimental_model_units" = "1" ] && node_is_selected spark4; then
	write_dsv4_env spark4
	install_unit spark4 ds4-dsv4-local-head.service
fi
if [ "$install_experimental_model_units" = "1" ] && node_is_selected spark5; then
	write_dsv4_env spark5
	install_unit spark5 ds4-dsv4-local-worker.service
fi

echo "==> updated nodes: ${nodes[*]}"
