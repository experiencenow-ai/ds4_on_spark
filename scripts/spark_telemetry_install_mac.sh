#!/usr/bin/env bash
set -euo pipefail

script_dir="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
repo_dir="$(cd "$script_dir/.." && pwd)"
install_dir="${DS4_TELEMETRY_INSTALL_DIR:-$HOME/.local/share/ds4_telemetry}"
launch_agents_dir="${DS4_TELEMETRY_LAUNCH_AGENTS_DIR:-$HOME/Library/LaunchAgents}"
uid="$(id -u)"

mkdir -p "$install_dir" "$launch_agents_dir" /tmp/ds4_telemetry/mac

for name in spark_telemetry_collect.py spark_telemetry_common.py spark_telemetry_dashboard.py; do
	cp "$repo_dir/scripts/$name" "$install_dir/$name"
	chmod +x "$install_dir/$name"
done

if [ -r "$install_dir/model_layer_partitions.json" ]; then
	echo "keeping $install_dir/model_layer_partitions.json"
else
	echo '{"model_layer_partitions":{}}' > "$install_dir/model_layer_partitions.json"
fi

for plist in com.ds4.spark-telemetry-collector.plist com.ds4.spark-telemetry-dashboard.plist; do
	cp "$repo_dir/deploy/launchd/$plist" "$launch_agents_dir/$plist"
done

for plist in com.ds4.spark-telemetry-collector.plist com.ds4.spark-telemetry-dashboard.plist; do
	launchctl bootout "gui/$uid" "$launch_agents_dir/$plist" >/dev/null 2>&1 || true
done

launchctl bootstrap "gui/$uid" "$launch_agents_dir/com.ds4.spark-telemetry-collector.plist"
launchctl bootstrap "gui/$uid" "$launch_agents_dir/com.ds4.spark-telemetry-dashboard.plist"
launchctl kickstart -k "gui/$uid/com.ds4.spark-telemetry-collector"
launchctl kickstart -k "gui/$uid/com.ds4.spark-telemetry-dashboard"

echo "installed Spark telemetry to $install_dir"
echo "dashboard: http://127.0.0.1:8765"
