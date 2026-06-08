#!/usr/bin/env bash
set -euo pipefail

script_dir="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
repo_dir="$(cd "$script_dir/.." && pwd)"
default_nodes="$(PYTHONPATH="$script_dir" python3 -c 'import spark_telemetry_common as t; print(t.DEFAULT_NODE_TARGETS)')"
telemetry_dir="$(PYTHONPATH="$script_dir" python3 -c 'import spark_telemetry_common as t; print(t.TELEMETRY_DIR)')"
nodes="${1:-$default_nodes}"
monitor="$repo_dir/scripts/spark_node_telemetry_monitor.py"
common="$repo_dir/scripts/spark_telemetry_common.py"
stopper="$repo_dir/scripts/spark_telemetry_stop.py"
service="$repo_dir/deploy/systemd/ds4-spark-telemetry.service"

IFS=',' read -r -a node_list <<< "$nodes"
for spec in "${node_list[@]}"; do
	spec="${spec//[[:space:]]/}"
	[ -n "$spec" ] || continue
	node="$spec"
	target="$spec"
	if [[ "$spec" == *=* ]]; then
		node="${spec%%=*}"
		target="${spec#*=}"
	fi
	echo "== $node ($target) =="
	ssh "$target" "mkdir -p ~/bin ~/.config/systemd/user '$telemetry_dir'"
	scp "$monitor" "$target:~/bin/spark_node_telemetry_monitor.py" >/dev/null
	scp "$common" "$target:~/bin/spark_telemetry_common.py" >/dev/null
	scp "$stopper" "$target:~/bin/spark_telemetry_stop.py" >/dev/null
	ssh "$target" 'chmod +x ~/bin/spark_node_telemetry_monitor.py'
	ssh "$target" 'chmod +x ~/bin/spark_telemetry_stop.py'
	scp "$service" "$target:~/.config/systemd/user/ds4-spark-telemetry.service" >/dev/null
	if ssh "$target" 'systemctl --user daemon-reload && systemctl --user enable ds4-spark-telemetry.service && systemctl --user restart ds4-spark-telemetry.service'; then
		ssh "$target" 'systemctl --user --no-pager --plain status ds4-spark-telemetry.service | sed -n "1,8p"'
	else
		echo "systemd user service failed on $node; falling back to nohup"
		ssh "$target" "python3 ~/bin/spark_telemetry_stop.py --out-dir '$telemetry_dir'; nohup python3 ~/bin/spark_node_telemetry_monitor.py --node \"\$(whoami)\" --interval 5 --out-dir '$telemetry_dir' > '$telemetry_dir/node_telemetry.nohup.log' 2>&1 & echo pid=\$!"
	fi
done
