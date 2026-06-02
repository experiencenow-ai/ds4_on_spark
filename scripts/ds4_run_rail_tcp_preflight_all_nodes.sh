#!/usr/bin/env bash
set -euo pipefail

nodes=(spark0 spark1 spark2 spark3 spark4 spark5 spark6 spark7)
world_size="${DS4_WORLD_SIZE:-8}"
source_root="${DS4_VLLM_SOURCE_ROOT:-~/src/vllm}"
python_bin="${DS4_VLLM_PYTHON:-~/ds4-vllm-local/bin/python}"
pairs="${DS4_RAIL_TCP_PREFLIGHT_PAIRS:-0-1;1-2;2-3;3-4;4-5;5-6;6-7}"
streams="${DS4_RAIL_TCP_PREFLIGHT_STREAMS:-16}"
duration="${DS4_RAIL_TCP_PREFLIGHT_DURATION_S:-5}"
tool="${DS4_RAIL_TCP_PREFLIGHT_TOOL:-iperf}"
min_gbit="${DS4_RAIL_TCP_PREFLIGHT_MIN_GBIT_S:-10}"
warn_gbit="${DS4_RAIL_TCP_PREFLIGHT_WARN_GBIT_S:-64}"
allowed_ifname="${DS4_RAIL_TCP_ALLOWED_IFNAME:-${DS4_200G_EFFECTIVE_IFNAME:-${DS4_200G_IFNAME:-enP2p1s0f0np0,enP2p1s0f1np1}}}"
port_base="${DS4_RAIL_TCP_PREFLIGHT_PORT_BASE:-49400}"
ssh_opts="${DS4_SSH_OPTS:-}"

remote_quote()
{
	printf '%q' "$1"
}

pair_log_label()
{
	local raw="$1"
	local old_ifs="$IFS"
	local items=()
	local item,left,right,label,sep
	IFS=';'
	read -r -a items <<< "$raw"
	IFS="$old_ifs"
	label=""
	sep=""
	for item in "${items[@]}"
	do
		item="${item//[[:space:]]/}"
		if [ -z "$item" ]
		then
			continue
		fi
		if [[ "$item" == *-* ]]
		then
			left="${item%%-*}"
			right="${item#*-}"
		elif [[ "$item" == *:* ]]
		then
			left="${item%%:*}"
			right="${item#*:}"
		elif [[ "$item" == *,* ]]
		then
			left="${item%%,*}"
			right="${item#*,}"
		else
			left="$item"
			right=""
		fi
		if [ -n "$right" ]
		then
			label="${label}${sep}spark${left}-spark${right}"
		else
			label="${label}${sep}spark${left}"
		fi
		sep="_"
	done
	if [ -z "$label" ]
	then
		label="all"
	fi
	printf '%s' "$label"
}

pair_label="$(pair_log_label "$pairs")"
run_stamp="$(date +%Y%m%dT%H%M%S)"
log_dir="${DS4_RAIL_TCP_PREFLIGHT_LOG_DIR:-/tmp/ds4_rail_tcp_preflight_${pair_label}_${run_stamp}_pid$$}"

mkdir -p "$log_dir"
echo "DS4 rail TCP preflight wrapper"
echo "  pairs=$pairs"
echo "  tool=$tool streams=$streams duration_s=$duration fail_Gbit_s=$min_gbit warn_Gbit_s=$warn_gbit allowed_ifname=$allowed_ifname"
echo "  logs=$log_dir"

pids=()
for rank in $(seq 0 $((world_size - 1)))
do
	node="${nodes[$rank]}"
	log="$log_dir/rank${rank}_${node}.log"
	cmd="cd $source_root && env RANK=$rank WORLD_SIZE=$world_size DS4_RAIL_TCP_ALLOWED_IFNAME=$(remote_quote "$allowed_ifname") DS4_RAIL_TCP_PREFLIGHT_PAIRS=$(remote_quote "$pairs") DS4_RAIL_TCP_PREFLIGHT_STREAMS=$(remote_quote "$streams") DS4_RAIL_TCP_PREFLIGHT_DURATION_S=$(remote_quote "$duration") DS4_RAIL_TCP_PREFLIGHT_TOOL=$(remote_quote "$tool") DS4_RAIL_TCP_PREFLIGHT_MIN_GBIT_S=$(remote_quote "$min_gbit") DS4_RAIL_TCP_PREFLIGHT_WARN_GBIT_S=$(remote_quote "$warn_gbit") DS4_RAIL_TCP_PREFLIGHT_PORT_BASE=$(remote_quote "$port_base") $python_bin tools/ds4_rail_tcp_preflight.py"
	ssh $ssh_opts "$node" "$cmd" >"$log" 2>&1 &
	pids+=("$!")
done

failed=0
for pid in "${pids[@]}"
do
	if ! wait "$pid"
	then
		failed=1
	fi
done

for log in "$log_dir"/rank*.log
do
	echo "==== $log"
	cat "$log"
done

if [ "$failed" -ne 0 ]
then
	echo "DS4 rail TCP preflight failed" >&2
	exit 1
fi
echo "DS4 rail TCP preflight passed"
