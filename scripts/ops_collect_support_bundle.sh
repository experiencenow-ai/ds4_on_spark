#!/usr/bin/env sh
set -eu

usage()
{
	cat <<'EOF'
ops_collect_support_bundle.sh -- collect a non-destructive DS4 support bundle

Usage:
  ops_collect_support_bundle.sh --instance <name> [--since <journalctl-since>] [--out <path>] [--env <path>]...

Options:
  --instance <name>      DS4 instance (e.g. spark0, spark1)
  --since <str>          Passed to journalctl --since (default: "1 hour ago")
  --out <path>           Output .tgz path (default: /tmp/ds4-support-<instance>-<ts>.tgz)
  --env <path>           Env file path (parsed as KEY=VALUE; no shell execution)
                         Prefix a path with '-' to make it optional if missing.

Notes:
  - Non-destructive; does not require sudo (but some commands may provide more detail with it).
  - This intentionally does NOT dump full env files. It captures a small allowlist of DS4_* keys.
  - The bundle is meant for human review before sharing; redact as needed.
EOF
}

instance=""
since="1 hour ago"
out=""
env_paths=""

while [ $# -gt 0 ]; do
	case "$1" in
		--instance)
			instance="${2:-}"
			shift 2
			;;
		--since)
			since="${2:-}"
			shift 2
			;;
		--out)
			out="${2:-}"
			shift 2
			;;
		--env)
			env_paths="$env_paths ${2:-}"
			shift 2
			;;
		-h|--help)
			usage
			exit 0
			;;
		*)
			echo "unknown arg: $1" >&2
			usage >&2
			exit 2
			;;
	esac
done

if [ "$instance" = "" ]; then
	echo "--instance is required" >&2
	usage >&2
	exit 2
fi

ts="$(date -u +%Y%m%dT%H%M%SZ 2>/dev/null || date +%s)"
work_dir="/tmp/ds4-support-${instance}-${ts}"

if [ "$out" = "" ]; then
	out="/tmp/ds4-support-${instance}-${ts}.tgz"
fi

mkdir -p "$work_dir"

have_cmd()
{
	command -v "$1" >/dev/null 2>&1
}

run_cmd()
{
	name="$1"
	shift
	out_path="$work_dir/$name"
	mkdir -p "$(dirname -- "$out_path")"
	{
		echo "== cmd =="
		printf '%s' "$*"
		echo
		echo "== date =="
		date -Is 2>/dev/null || date || true
		echo "== output =="
		"$@" 2>&1
	} >"$out_path" || {
		rc="$?"
		echo "rc=$rc" >>"$out_path" || true
		return 0
	}
	return 0
}

write_note()
{
	name="$1"
	shift
	out_path="$work_dir/$name"
	mkdir -p "$(dirname -- "$out_path")"
	{
		date -Is 2>/dev/null || date || true
		echo "$*"
	} >"$out_path"
}

extract_env_value()
{
	key="$1"
	path="$2"
	val=""

	if [ ! -f "$path" ] || [ ! -r "$path" ]; then
		return 0
	fi

	val="$(awk -v k="$key" -F= '
		/^[[:space:]]*#/ { next }
		/^[[:space:]]*$/ { next }
		{
			line=$0
			sub(/^[[:space:]]*/, "", line)
			sub(/[[:space:]]*$/, "", line)
			if (line ~ /^export[[:space:]]+/) sub(/^export[[:space:]]+/, "", line)
			pos=index(line, "=")
			if (pos <= 0) next
			k0=substr(line, 1, pos-1)
			v0=substr(line, pos+1)
			sub(/[[:space:]]*$/, "", k0)
			sub(/^[[:space:]]*/, "", v0)
			if (k0 != k) next
			if (v0 ~ /^".*"$/) { sub(/^"/, "", v0); sub(/"$/, "", v0) }
			if (v0 ~ /^'\''.*'\''$/) { sub(/^'\''/, "", v0); sub(/'\''$/, "", v0) }
			print v0
		}
	' "$path" | tail -n 1)"

	printf '%s' "$val"
	return 0
}

maybe_put_env_key()
{
	key="$1"
	val="$2"

	if [ "$val" = "" ]; then
		return 0
	fi

	case "$key" in
		*KEY*|*TOKEN*|*SECRET*|*PASSWORD*)
			printf '%s=%s\n' "$key" "<redacted>"
			return 0
			;;
	esac

	printf '%s=%s\n' "$key" "$val"
}

echo "== ds4 support bundle =="
echo "instance=$instance"
echo "work_dir=$work_dir"
echo "out=$out"

run_cmd "meta.txt" sh -c "echo instance=$instance; echo since='$since'; echo out=$out; echo work_dir=$work_dir"

run_cmd "system/date.txt" date
run_cmd "system/uname.txt" uname -a
if have_cmd lsb_release; then
	run_cmd "system/lsb_release.txt" lsb_release -a
fi
if have_cmd cat; then
	run_cmd "system/os_release.txt" sh -c "cat /etc/os-release 2>/dev/null || true"
fi

if have_cmd nvidia-smi; then
	run_cmd "gpu/nvidia_smi.txt" nvidia-smi
	run_cmd "gpu/nvidia_smi_topo.txt" sh -c "nvidia-smi topo -m 2>/dev/null || true"
fi

if have_cmd ip; then
	run_cmd "net/ip_addr.txt" ip addr
	run_cmd "net/ip_route.txt" ip route
	run_cmd "net/ip_route_table_all.txt" sh -c "ip route show table all 2>/dev/null || true"
fi
if have_cmd ss; then
	run_cmd "net/ss_lntu.txt" ss -lntu
fi

if have_cmd df; then
	run_cmd "fs/df_h.txt" df -h
fi
if have_cmd mount; then
	run_cmd "fs/mount.txt" mount
fi
if have_cmd ulimit; then
	run_cmd "limits/ulimit_a.txt" sh -c "ulimit -a 2>/dev/null || true"
fi

env_summary="$work_dir/ds4_env_allowlist.txt"
{
	date -Is 2>/dev/null || date || true
	echo "instance=$instance"
	echo
	echo "== ds4 env allowlist (last value wins across --env files) =="
} >"$env_summary"

DS4_CONFIG_PATH=""
	DS4_MASTER_ADDR=""
	DS4_MASTER_PORT=""
	DS4_PEER_HOST=""
	DS4_PEER_SSH=""
	DS4_METRICS_ADDR=""
	DS4_METRICS_PORT=""

if [ "$env_paths" != "" ]; then
	for raw in $env_paths; do
		optional=0
		env_path="$raw"
		case "$raw" in
			-/*)
				optional=1
				env_path="${raw#-}"
				;;
		esac
		if [ ! -f "$env_path" ]; then
			if [ "$optional" -ne 0 ]; then
				continue
			fi
			echo "missing env file: $env_path" >&2
			exit 2
		fi
		if [ ! -r "$env_path" ]; then
			echo "unreadable env file (check owner/group/mode): $env_path" >&2
			exit 2
		fi

		printf '\n== source env file (metadata only): %s ==\n' "$env_path" >>"$env_summary"
		ls -l "$env_path" >>"$env_summary" 2>&1 || true

		v="$(extract_env_value DS4_CONFIG_PATH "$env_path")"
		if [ "$v" != "" ]; then DS4_CONFIG_PATH="$v"; fi
		v="$(extract_env_value DS4_MASTER_ADDR "$env_path")"
		if [ "$v" != "" ]; then DS4_MASTER_ADDR="$v"; fi
		v="$(extract_env_value DS4_MASTER_PORT "$env_path")"
		if [ "$v" != "" ]; then DS4_MASTER_PORT="$v"; fi
			v="$(extract_env_value DS4_PEER_HOST "$env_path")"
			if [ "$v" != "" ]; then DS4_PEER_HOST="$v"; fi
			v="$(extract_env_value DS4_PEER_SSH "$env_path")"
			if [ "$v" != "" ]; then DS4_PEER_SSH="$v"; fi
			v="$(extract_env_value DS4_METRICS_ADDR "$env_path")"
			if [ "$v" != "" ]; then DS4_METRICS_ADDR="$v"; fi
			v="$(extract_env_value DS4_METRICS_PORT "$env_path")"
			if [ "$v" != "" ]; then DS4_METRICS_PORT="$v"; fi
	done
fi

{
	maybe_put_env_key "DS4_CONFIG_PATH" "$DS4_CONFIG_PATH"
		maybe_put_env_key "DS4_MASTER_ADDR" "$DS4_MASTER_ADDR"
		maybe_put_env_key "DS4_MASTER_PORT" "$DS4_MASTER_PORT"
		maybe_put_env_key "DS4_PEER_HOST" "$DS4_PEER_HOST"
		maybe_put_env_key "DS4_PEER_SSH" "$DS4_PEER_SSH"
		maybe_put_env_key "DS4_METRICS_ADDR" "$DS4_METRICS_ADDR"
		maybe_put_env_key "DS4_METRICS_PORT" "$DS4_METRICS_PORT"
	} >>"$env_summary"

	local_scripts_dir="$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)"

	if [ "$DS4_CONFIG_PATH" != "" ]; then
		run_cmd "ds4/config_stat.txt" sh -c "ls -l \"$DS4_CONFIG_PATH\" 2>/dev/null || true"
		run_cmd "ds4/config_head.txt" sh -c "sed -n '1,120p' \"$DS4_CONFIG_PATH\" 2>/dev/null || true"
		if [ -x "$local_scripts_dir/ops_ds4_config_check.sh" ]; then
			run_cmd "ds4/config_check.txt" "$local_scripts_dir/ops_ds4_config_check.sh" --strict-unknown "$DS4_CONFIG_PATH"
		fi
	fi

	if [ "$env_paths" != "" ]; then
		if [ -x "$local_scripts_dir/ops_ds4_env_check.sh" ]; then
			(
				set -- "$local_scripts_dir/ops_ds4_env_check.sh"
				for raw in $env_paths; do
					set -- "$@" "$raw"
				done
				run_cmd "ds4/env_check.txt" "$@"
			)
		fi

		if [ -x "$local_scripts_dir/ops_tp2_readiness.sh" ]; then
			(
				set -- "$local_scripts_dir/ops_tp2_readiness.sh" --self "$instance"
				for raw in $env_paths; do
					set -- "$@" --env "$raw"
				done
				if [ "$DS4_PEER_HOST" != "" ]; then
					set -- "$@" --peer "$DS4_PEER_HOST"
				fi
				run_cmd "ds4/tp2_readiness.txt" "$@"
			)
		fi
	fi

	if have_cmd systemctl; then
		run_cmd "systemd/systemctl_status_ds4.txt" systemctl --no-pager status "ds4@${instance}.service"
	run_cmd "systemd/systemctl_status_ds4_strict.txt" systemctl --no-pager status "ds4-strict@${instance}.service"
	run_cmd "systemd/systemctl_status_preflight.txt" systemctl --no-pager status "ds4-preflight@${instance}.service"
	run_cmd "systemd/systemctl_status_preflight_strict.txt" systemctl --no-pager status "ds4-preflight-strict@${instance}.service"
	run_cmd "systemd/systemctl_status_spark_master.txt" systemctl --no-pager status "spark-master@${instance}.service"
	run_cmd "systemd/systemctl_status_spark_worker.txt" systemctl --no-pager status "spark-worker@${instance}.service"
	run_cmd "systemd/systemctl_show_ds4.txt" systemctl show "ds4@${instance}.service"
	run_cmd "systemd/systemctl_list_units_ds4.txt" sh -c "systemctl list-units --no-pager | grep -E '^ds4' || true"
	run_cmd "systemd/systemctl_list_units_spark.txt" sh -c "systemctl list-units --no-pager | grep -E '^(spark-master|spark-worker)' || true"
fi

if have_cmd journalctl; then
	run_cmd "journald/journal_ds4.txt" journalctl --no-pager -u "ds4@${instance}.service" --since "$since"
	run_cmd "journald/journal_preflight.txt" journalctl --no-pager -u "ds4-preflight@${instance}.service" --since "$since"
	run_cmd "journald/journal_preflight_strict.txt" journalctl --no-pager -u "ds4-preflight-strict@${instance}.service" --since "$since"
	run_cmd "journald/journal_spark_master.txt" journalctl --no-pager -u "spark-master@${instance}.service" --since "$since"
	run_cmd "journald/journal_spark_worker.txt" journalctl --no-pager -u "spark-worker@${instance}.service" --since "$since"
fi

if have_cmd getent; then
	if [ "$DS4_MASTER_ADDR" != "" ]; then
		run_cmd "net/getent_master_addr.txt" getent hosts "$DS4_MASTER_ADDR"
	fi
	if [ "$DS4_PEER_HOST" != "" ]; then
		run_cmd "net/getent_peer_host.txt" getent hosts "$DS4_PEER_HOST"
	fi
fi

if have_cmd ip; then
	if [ "$DS4_MASTER_ADDR" != "" ]; then
		run_cmd "net/ip_route_get_master.txt" sh -c "ip route get \"$DS4_MASTER_ADDR\" 2>&1 || true"
	fi
	if [ "$DS4_PEER_HOST" != "" ]; then
		run_cmd "net/ip_route_get_peer.txt" sh -c "ip route get \"$DS4_PEER_HOST\" 2>&1 || true"
	fi
fi

if have_cmd ping; then
	if [ "$DS4_MASTER_ADDR" != "" ]; then
		run_cmd "net/ping_master.txt" sh -c "ping -c 2 -W 2 \"$DS4_MASTER_ADDR\" 2>&1 || true"
	fi
	if [ "$DS4_PEER_HOST" != "" ]; then
		run_cmd "net/ping_peer.txt" sh -c "ping -c 2 -W 2 \"$DS4_PEER_HOST\" 2>&1 || true"
	fi
fi

if have_cmd curl; then
	if [ "$DS4_METRICS_PORT" != "" ]; then
		if [ "$DS4_METRICS_ADDR" = "" ]; then
			DS4_METRICS_ADDR="127.0.0.1"
		fi
		run_cmd "ds4/metrics_http.txt" sh -c "curl -fsS --max-time 2 \"http://$DS4_METRICS_ADDR:$DS4_METRICS_PORT/metrics\" | head -n 80 2>&1 || true"
	fi
fi

if have_cmd tar; then
	( cd "$(dirname -- "$work_dir")" && tar -czf "$out" "$(basename -- "$work_dir")" ) || true
	if [ -f "$out" ]; then
		echo "wrote: $out"
	else
		write_note "bundle_error.txt" "failed to create $out (tar/gzip unavailable?)"
		echo "bundle directory: $work_dir"
	fi
else
	write_note "bundle_error.txt" "missing tar; bundle directory only"
	echo "bundle directory: $work_dir"
fi
