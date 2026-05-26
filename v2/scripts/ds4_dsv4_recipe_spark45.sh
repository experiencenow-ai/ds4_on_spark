#!/usr/bin/env bash
set -euo pipefail

mode="${1:-start}"
recipe_repo="${DS4_DSV4_RECIPE_RUNNER_DIR:-$HOME/spark-vllm-docker}"
recipe_source="${DS4_DSV4_RECIPE_SOURCE:-$HOME/ds4_on_spark/v2/recipes/deepseek-v4-flash-spark45.yaml}"
runner_repo="${DS4_DSV4_RECIPE_RUNNER_REPO:-https://github.com/eugr/spark-vllm-docker.git}"
recipe_runner_ref="${DS4_DSV4_RECIPE_RUNNER_REF:-refs/remotes/origin/pr/219}"
head_ip="${DS4_DSV4_HEAD_IP:-10.20.0.14}"
worker_ip="${DS4_DSV4_WORKER_IP:-10.20.0.15}"
worker_user="${DS4_DSV4_WORKER_USER:-spark5}"
eth_if="${DS4_DSV4_ETH_IF:-enP7s7}"
ib_if="${DS4_DSV4_IB_IF:-__disabled__}"
container_name="${DS4_DSV4_CONTAINER_NAME:-vllm_deepseek_v4_flash}"
container_image="${DS4_DSV4_IMAGE_NAME:-vllm-node-dsv4-lmcache-rankfix}"
lmcache_config_dir="${DS4_DSV4_LMCACHE_CONFIG_DIR:-/tmp/ds4-lmcache}"
lmcache_config_host="${DS4_DSV4_LMCACHE_CONFIG_HOST:-$lmcache_config_dir/lmcache_dsv4_spark45.yaml}"
lmcache_config_container="${DS4_DSV4_LMCACHE_CONFIG_CONTAINER:-/etc/ds4/lmcache_dsv4_spark45.yaml}"
lmcache_dir="${DS4_DSV4_LMCACHE_DIR:-/tmp/ds4-lmcache/dsv4-spark45}"

ensure_runner()
{
	if [ ! -d "$recipe_repo/.git" ]; then
		git clone "$runner_repo" "$recipe_repo"
	fi
	git -C "$recipe_repo" fetch --quiet origin || true
	git -C "$recipe_repo" fetch --quiet origin '+refs/pull/219/head:refs/remotes/origin/pr/219' || true
	git -C "$recipe_repo" checkout --quiet "$recipe_runner_ref"
}

ensure_worker_ssh()
{
	mkdir -p "$HOME/.ssh"
	chmod 700 "$HOME/.ssh"
	touch "$HOME/.ssh/config"
	if ! grep -q "^Host $worker_ip$" "$HOME/.ssh/config"; then
		{
			echo ""
			echo "Host $worker_ip"
			echo "    User $worker_user"
			echo "    IdentityFile ~/.ssh/ds4_spark_launch_ed25519"
			echo "    StrictHostKeyChecking no"
			echo "    UserKnownHostsFile ~/.ssh/known_hosts"
		} >> "$HOME/.ssh/config"
	fi
	chmod 600 "$HOME/.ssh/config"
}

write_lmcache_config()
{
	mkdir -p "$lmcache_config_dir" "$lmcache_dir"
	cat > "$lmcache_config_host" <<EOF
chunk_size: 256
local_cpu: true
max_local_cpu_size: 16.0
local_disk: "file://$lmcache_dir/"
max_local_disk_size: 512.0
EOF
	ssh -o BatchMode=yes -o ConnectTimeout=5 "$worker_ip" "mkdir -p '$lmcache_config_dir' '$lmcache_dir'"
	scp -q "$lmcache_config_host" "$worker_ip:$lmcache_config_host"
}

write_env()
{
	cat > "$recipe_repo/.env" <<EOF
CLUSTER_NODES=$head_ip,$worker_ip
LOCAL_IP=$head_ip
ETH_IF=$eth_if
IB_IF=$ib_if
CONTAINER_NAME=$container_name
CONTAINER_NCCL_DEBUG=WARN
CONTAINER_NCCL_IGNORE_CPU_AFFINITY=1
CONTAINER_NCCL_IB_DISABLE=1
CONTAINER_NCCL_SOCKET_IFNAME=$eth_if
CONTAINER_GLOO_SOCKET_IFNAME=$eth_if
CONTAINER_TP_SOCKET_IFNAME=$eth_if
CONTAINER_LMCACHE_USE_EXPERIMENTAL=True
CONTAINER_LMCACHE_CONFIG_FILE=$lmcache_config_container
CONTAINER_CUDA_HOME=/usr/local/cuda
EOF
}

export_lmcache_mounts()
{
	local extra="${VLLM_SPARK_EXTRA_DOCKER_ARGS:-}"
	extra="$extra -v $lmcache_config_dir:/etc/ds4:ro -v $lmcache_dir:$lmcache_dir"
	export VLLM_SPARK_EXTRA_DOCKER_ARGS="$extra"
}

case "$mode" in
	install)
		ensure_runner
		ensure_worker_ssh
		write_lmcache_config
		install -m 0644 "$recipe_source" "$recipe_repo/recipes/deepseek-v4-flash-spark45.yaml"
		write_env
		;;
	start)
		ensure_runner
		ensure_worker_ssh
		write_lmcache_config
		export_lmcache_mounts
		install -m 0644 "$recipe_source" "$recipe_repo/recipes/deepseek-v4-flash-spark45.yaml"
		write_env
		cd "$recipe_repo"
		exec ./run-recipe.sh recipes/deepseek-v4-flash-spark45.yaml -t "$container_image" --no-ray --no-cache-dirs -d
		;;
	stop)
		if [ -x "$recipe_repo/launch-cluster.sh" ]; then
			cd "$recipe_repo"
			exec ./launch-cluster.sh -t "$container_image" --name "$container_name" -n "$head_ip,$worker_ip" --eth-if "$eth_if" --ib-if "$ib_if" --no-ray --no-cache-dirs stop
		fi
		;;
	status)
		if [ -x "$recipe_repo/launch-cluster.sh" ]; then
			cd "$recipe_repo"
			exec ./launch-cluster.sh -t "$container_image" --name "$container_name" -n "$head_ip,$worker_ip" --eth-if "$eth_if" --ib-if "$ib_if" --no-ray --no-cache-dirs status
		fi
		;;
	*)
		echo "usage: $0 install|start|stop|status" >&2
		exit 2
		;;
esac
