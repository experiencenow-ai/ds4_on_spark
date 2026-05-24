#!/usr/bin/env bash
set -euo pipefail

nodes="${1:-spark0,spark1,spark2,spark3,spark4,spark5,spark6,spark7}"
script_dir="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
repo_dir="$(cd "$script_dir/.." && pwd)"
monitor="$repo_dir/scripts/spark_node_telemetry_monitor.py"
service="$repo_dir/deploy/systemd/ds4-spark-telemetry.service"

IFS=',' read -r -a node_list <<< "$nodes"
for node in "${node_list[@]}"; do
	node="${node//[[:space:]]/}"
	[ -n "$node" ] || continue
	echo "== $node =="
	ssh "$node" 'mkdir -p ~/bin ~/.config/systemd/user /tmp/ds4_telemetry'
	scp "$monitor" "$node:~/bin/spark_node_telemetry_monitor.py" >/dev/null
	ssh "$node" 'chmod +x ~/bin/spark_node_telemetry_monitor.py'
	scp "$service" "$node:~/.config/systemd/user/ds4-spark-telemetry.service" >/dev/null
	if ssh "$node" 'systemctl --user daemon-reload && systemctl --user enable ds4-spark-telemetry.service && systemctl --user restart ds4-spark-telemetry.service'; then
		ssh "$node" 'systemctl --user --no-pager --plain status ds4-spark-telemetry.service | sed -n "1,8p"'
	else
		echo "systemd user service failed on $node; falling back to nohup"
		ssh "$node" 'pkill -f spark_node_telemetry_monitor.py || true; nohup python3 ~/bin/spark_node_telemetry_monitor.py --interval 5 --out-dir /tmp/ds4_telemetry > /tmp/ds4_telemetry/node_telemetry.nohup.log 2>&1 & echo pid=$!'
	fi
done
