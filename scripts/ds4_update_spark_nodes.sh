#!/usr/bin/env bash
set -euo pipefail

usage()
{
	local code="${1:-2}"
	cat >&2 <<'EOF'
usage: scripts/ds4_update_spark_nodes.sh [--code-only] [spark0 spark1 ...]

Updates reachable Spark nodes to the merged DS4 repo ref. The default mode is
--code-only: pull origin/main on all reachable Spark checkouts and do not touch
runtime env, systemd units, or running services.
When no nodes are provided, the node list comes from
v2/profiles/transfer/spark_200g.json.

Modes:
  --code-only                  pull Spark checkouts only; no service side effects
  --runtime-config             DISABLED; use v2/scripts/ds4_pipeline_lifecycle.py
  --self-update                fetch/detach this Mac checkout before running
  --restart-qwen               restart Qwen gateways after runtime env update
  --restart-dsv4               DISABLED; use v2/scripts/ds4_pipeline_lifecycle.py

Important environment knobs:
  DS4_UPDATE_MODE=code-only       code-only only
  DS4_SELF_UPDATE=0               set 1 to fetch/detach this local worktree first
  DS4_UPDATE_REF=origin/main        git ref to deploy on each Spark checkout
  DS4_REMOTE_REPO=$HOME/src/ds4_on_spark remote repo path on each Spark
  DS4_CONFIGURE_QWEN_RUNTIME=0     set 1 to point Qwen gateways at host-local vLLM
  DS4_RESTART_QWEN=0               restart Qwen model gateways after env update
  DS4_QWEN_RUNTIME_TARGET=...      trim-capable target for ~/ds4-vllm-local
  DS4_INSTALL_DSV4_LOCAL=0         must remain 0; old spark4/spark5 lane is disabled
  DS4_RESTART_DSV4=0               must remain 0; use the lifecycle runner
  DS4_DSV4_KV_OFFLOAD_SIZE=4       recovery-safe total GiB for spark4+spark5

Zero-drift rule:
  this script refuses local sync payloads and only updates clean Spark
  checkouts. Resident pipeline launch is handled by the lifecycle runner.
EOF
	exit "$code"
}

if [ "${1:-}" = "-h" ] || [ "${1:-}" = "--help" ]; then
	usage 0
fi

repo_dir=$(CDPATH= cd -- "$(dirname -- "$0")/.." && pwd)
topology_path="${DS4_SPARK_FLEET_TOPOLOGY:-$repo_dir/v2/profiles/transfer/spark_200g.json}"
update_mode="${DS4_UPDATE_MODE:-code-only}"
nodes=()
while [ "$#" -gt 0 ]
do
	case "$1" in
	-h|--help)
		usage 0
		;;
	--code-only|--pull-only)
		update_mode="code-only"
		;;
	--runtime-config|--configure-runtime)
		echo "ERROR: --runtime-config is disabled; use v2/scripts/ds4_pipeline_lifecycle.py" >&2
		exit 64
		;;
	--self-update)
		DS4_SELF_UPDATE=1
		;;
	--restart-qwen)
		DS4_RESTART_QWEN=1
		;;
	--restart-dsv4)
		echo "ERROR: --restart-dsv4 is disabled; use v2/scripts/ds4_pipeline_lifecycle.py --service dsv4_flash_pp8 relaunch --execute" >&2
		exit 64
		;;
	--)
		shift
		nodes+=("$@")
		break
		;;
	-*)
		echo "unknown option: $1" >&2
		usage
		;;
	*)
		nodes+=("$1")
		;;
	esac
	shift
done

load_default_nodes()
{
	python3 - "$topology_path" <<'PY'
import json
import sys

path = sys.argv[1]
with open(path, "r", encoding="utf-8") as handle:
    topology = json.load(handle)
for node in topology.get("nodes", []):
    node_id = node.get("node_id")
    if node_id:
        print(node_id)
PY
}

node_ssh_target()
{
	local node="$1"
	python3 - "$topology_path" "$node" <<'PY'
import json
import sys

path = sys.argv[1]
node_id = sys.argv[2]
try:
    with open(path, "r", encoding="utf-8") as handle:
        topology = json.load(handle)
except (OSError, ValueError, json.JSONDecodeError):
    print(node_id)
    raise SystemExit(0)
for node in topology.get("nodes", []):
    if node.get("node_id") == node_id:
        print(node.get("host") or node_id)
        raise SystemExit(0)
print(node_id)
PY
}

if [ "${#nodes[@]}" -eq 0 ]; then
	while IFS= read -r node
	do
		if [ "$node" != "" ]; then
			nodes+=("$node")
		fi
	done < <(load_default_nodes)
	if [ "${#nodes[@]}" -eq 0 ]; then
		echo "no default Spark nodes found in topology: $topology_path" >&2
		exit 15
	fi
fi

case "$update_mode" in
code-only)
	default_self_update=0
	default_configure_qwen_runtime=0
	default_install_dsv4_local=0
	;;
runtime-config)
	echo "ERROR: DS4_UPDATE_MODE=runtime-config is disabled; use v2/scripts/ds4_pipeline_lifecycle.py" >&2
	exit 64
	;;
*)
	echo "unknown DS4_UPDATE_MODE: $update_mode" >&2
	exit 14
	;;
esac

remote_repo="${DS4_REMOTE_REPO:-}"
update_remote="${DS4_UPDATE_REMOTE:-origin}"
update_branch="${DS4_UPDATE_BRANCH:-main}"
update_ref="${DS4_UPDATE_REF:-origin/main}"
local_self_update="${DS4_SELF_UPDATE:-$default_self_update}"
skip_unreachable="${DS4_SKIP_UNREACHABLE:-1}"
connect_timeout="${DS4_CONNECT_TIMEOUT:-8}"
ssh_opts="${DS4_SSH_OPTS:-}"
configure_qwen_runtime="${DS4_CONFIGURE_QWEN_RUNTIME:-$default_configure_qwen_runtime}"
restart_qwen="${DS4_RESTART_QWEN:-0}"
qwen_runtime_target="${DS4_QWEN_RUNTIME_TARGET:-~/standard-runtimes/vllm-main-gdn-nixl/venv}"
install_dsv4_local="${DS4_INSTALL_DSV4_LOCAL:-$default_install_dsv4_local}"
restart_dsv4="${DS4_RESTART_DSV4:-0}"
dsv4_kv_offload_size="${DS4_DSV4_KV_OFFLOAD_SIZE:-4}"
dsv4_persist_store="${DS4_DSV4_PERSIST_STORE:-/var/tmp/ds4_hma_store/dsv4/simple_cpu_offload}"
dsv4_persist_strict="${DS4_DSV4_PERSIST_STRICT:-1}"
dsv4_pythonhashseed="${DS4_DSV4_PYTHONHASHSEED:-0}"

if [ "$update_remote" != "origin" ] || [ "$update_branch" != "main" ] || [ "$update_ref" != "origin/main" ]; then
	echo "zero-drift deployment requires DS4_UPDATE_REMOTE=origin DS4_UPDATE_BRANCH=main DS4_UPDATE_REF=origin/main" >&2
	exit 13
fi
if [ "$install_dsv4_local" != "0" ] || [ "$restart_dsv4" != "0" ]; then
	echo "ERROR: deprecated spark4/spark5 DSV4 unit install/restart is disabled; use v2/scripts/ds4_pipeline_lifecycle.py --service dsv4_flash_pp8 relaunch --execute" >&2
	exit 64
fi

self_update_local_checkout()
{
	if [ "$local_self_update" != "1" ] || [ "${DS4_SELF_UPDATE_DONE:-0}" = "1" ]; then
		return 0
	fi
	if ! git -C "$repo_dir" rev-parse --is-inside-work-tree >/dev/null 2>&1; then
		return 0
	fi
	if [ -n "$(git -C "$repo_dir" status --porcelain)" ]; then
		echo "local checkout is dirty; refusing to self-update" >&2
		echo "set DS4_SELF_UPDATE=0 to run this exact checkout anyway" >&2
		git -C "$repo_dir" status --short >&2
		exit 12
	fi
	echo "==> local: fetch $update_remote $update_branch"
	git -C "$repo_dir" fetch "$update_remote" "$update_branch"
	target="$(git -C "$repo_dir" rev-parse --verify "$update_ref")"
	current="$(git -C "$repo_dir" rev-parse --verify HEAD)"
	if [ "$current" = "$target" ]; then
		echo "==> local: already at $update_ref ($(git -C "$repo_dir" rev-parse --short HEAD))"
		return 0
	fi
	echo "==> local: checkout --detach $update_ref"
	git -C "$repo_dir" checkout --detach "$update_ref"
	exec env \
		DS4_SELF_UPDATE_DONE=1 \
		DS4_UPDATE_MODE="$update_mode" \
		DS4_RESTART_QWEN="$restart_qwen" \
		DS4_RESTART_DSV4="$restart_dsv4" \
		"$0" "$@"
}

self_update_local_checkout "${nodes[@]}"

echo "==> spark update mode: $update_mode"
echo "==> actions: self_update=$local_self_update qwen_runtime=$configure_qwen_runtime qwen_restart=$restart_qwen dsv4_units=$install_dsv4_local dsv4_restart=$restart_dsv4"

ssh_cmd()
{
	local host="$1"
	shift
	ssh $ssh_opts -o BatchMode=yes -o ConnectTimeout="$connect_timeout" "$(node_ssh_target "$host")" "$@"
}

remote_repo_path()
{
	local host="$1"
	ssh_cmd "$host" "DS4_REMOTE_REPO='$remote_repo' bash -s" <<'REMOTE'
set -eu
repo="${DS4_REMOTE_REPO:-$HOME/src/ds4_on_spark}"
printf '%s\n' "$repo"
REMOTE
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

node_is_qwen_gateway()
{
	case "$1" in
	spark0|spark1|spark2|spark3|spark6)
		return 0
		;;
	*)
		return 1
		;;
	esac
}

update_remote_repo()
{
	local host="$1"
	local repo_path
	repo_path="$(remote_repo_path "$host")"
	echo "==> $host: git update $repo_path to $update_ref"
	ssh_cmd "$host" \
		"DS4_REMOTE_REPO='$remote_repo' DS4_UPDATE_REMOTE='$update_remote' DS4_UPDATE_BRANCH='$update_branch' DS4_UPDATE_REF='$update_ref' bash -s" <<'REMOTE'
set -euo pipefail
repo="${DS4_REMOTE_REPO:-$HOME/src/ds4_on_spark}"
remote="$DS4_UPDATE_REMOTE"
branch="$DS4_UPDATE_BRANCH"
ref="$DS4_UPDATE_REF"
if [ ! -d "$repo/.git" ]; then
	echo "missing repo: $repo" >&2
	exit 20
fi
cd "$repo"
git fetch --prune "$remote" "$branch"
if [ -n "$(git status --porcelain)" ]; then
	echo "dirty remote checkout; refusing zero-drift deployment: $repo" >&2
	git status --short >&2
	exit 21
fi
git checkout "$branch"
git merge --ff-only "$ref"
git rev-parse --short HEAD
REMOTE
}

configure_qwen_node_runtime()
{
	local host="$1"
	echo "==> $host: configure Qwen host-local vLLM runtime"
	ssh_cmd "$host" \
		"DS4_QWEN_RUNTIME_TARGET='$qwen_runtime_target' DS4_RESTART_QWEN='$restart_qwen' bash -s" <<'REMOTE'
set -euo pipefail
runtime_target="${DS4_QWEN_RUNTIME_TARGET:-$HOME/standard-runtimes/vllm-0.21.0}"
runtime_target="${runtime_target/#\~/$HOME}"
runtime_target="${runtime_target/#\$HOME/$HOME}"
if [ ! -x "$runtime_target/bin/python" ] || [ ! -x "$runtime_target/bin/vllm" ]; then
	echo "missing Qwen vLLM runtime: $runtime_target" >&2
	exit 30
fi
ln -sfn "$runtime_target" "$HOME/ds4-vllm-local"
mkdir -p "$HOME/.config/ds4"
envfile="$HOME/.config/ds4/model-gateway.env"
tmp="$envfile.tmp.$$"
touch "$envfile"
awk '
BEGIN { wrote=0 }
/^VLLM_HOME=/ {
	if ( wrote == 0 ) {
		print "VLLM_HOME=~/ds4-vllm-local"
		wrote=1
	}
	next
}
{ print }
END {
	if ( wrote == 0 )
		print "VLLM_HOME=~/ds4-vllm-local"
}
' "$envfile" > "$tmp"
mv "$tmp" "$envfile"
"$HOME/ds4-vllm-local/bin/python" -c 'import vllm; print("vllm=" + vllm.__version__)'
"$HOME/ds4-vllm-local/bin/python" - <<'PY'
import pathlib
import sys
import vllm
root = pathlib.Path(vllm.__file__).resolve().parent
for path in root.rglob("*.py"):
    try:
        if "trim_memory" in path.read_text(errors="ignore"):
            raise SystemExit(0)
    except OSError:
        pass
print("vLLM runtime lacks trim_memory support", file=sys.stderr)
raise SystemExit(31)
PY
if [ "$DS4_RESTART_QWEN" = "1" ]; then
	systemctl --user restart ds4-model-gateway.service
fi
REMOTE
}

update_node_code()
{
	local host="$1"
	update_remote_repo "$host"
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
	write_dsv4_env "$host"
	ssh_cmd "$host" "DS4_REMOTE_REPO='$remote_repo' bash -s '$unit'" <<'REMOTE'
set -euo pipefail
unit="$1"
repo="${DS4_REMOTE_REPO:-$HOME/src/ds4_on_spark}"
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
	update_node_code "$node"
done

if [ "$configure_qwen_runtime" = "1" ]; then
	for node in "${reachable[@]}"
	do
		if node_is_qwen_gateway "$node"; then
			configure_qwen_node_runtime "$node"
		fi
	done
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
