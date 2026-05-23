#!/bin/sh
set -u

LOGTAG=ds4-sshd-watchdog
STATE_DIR=/run/ds4-rescue
FAIL_FILE=$STATE_DIR/sshd-watchdog.failures
LOCK_DIR=$STATE_DIR/sshd-watchdog.lock
REBOOT_AFTER="${DS4_WATCHDOG_REBOOT_AFTER:-0}"
TOP_MEM_COUNT="${DS4_WATCHDOG_KILL_TOP_MEM_COUNT:-16}"
MIN_KILL_RSS_KB="${DS4_WATCHDOG_MIN_KILL_RSS_KB:-262144}"
KILL_GPU_PROCS="${DS4_WATCHDOG_KILL_GPU_PROCS:-1}"

log()
{
	if command -v logger >/dev/null 2>&1
	then
		logger -t "$LOGTAG" "$*"
	else
		echo "$LOGTAG: $*" >&2
	fi
}

probe_ssh()
{
	python3 - <<'PY'
import socket
import sys

try:
    sock = socket.create_connection(("127.0.0.1", 22), timeout=2.0)
    sock.settimeout(2.0)
    data = sock.recv(128)
    sock.close()
    sys.exit(0 if data.startswith(b"SSH-") else 1)
except Exception:
    sys.exit(1)
PY
}

restart_ssh()
{
	if systemctl restart ssh
	then
		return 0
	fi
	systemctl restart sshd
}

kill_container()
{
	name="$1"
	if [ "$name" = "" ]
	then
		return 0
	fi
	log "killing container $name"
	docker kill "$name" >/dev/null 2>&1 || true
}

kill_allowlisted_containers()
{
	name=""
	if ! command -v docker >/dev/null 2>&1
	then
		return 0
	fi
	for name in vllm_deepseek_v4_flash
	do
		kill_container "$name"
	done
	docker ps --format '{{.Names}}' 2>/dev/null | while IFS= read -r name
	do
		case "$name" in
		vllm_*|ds4_vllm_*|centaur_vllm_*)
			kill_container "$name"
			;;
		esac
	done
}

kill_pattern()
{
	pat="$1"
	log "killing processes matching $pat"
	pkill -9 -f "$pat" >/dev/null 2>&1 || true
}

kill_allowlisted_processes()
{
	kill_pattern '/usr/local/bin/vllm serve'
	kill_pattern '/usr/bin/python3 /usr/local/bin/vllm serve'
	kill_pattern 'vllm serve /models/'
	kill_pattern 'VLLM::'
	if [ "${DS4_WATCHDOG_KILL_RAY:-0}" = "1" ]
	then
		kill_pattern '/ray/'
		kill_pattern 'raylet'
	fi
}

kill_gpu_compute_processes()
{
	pid=""
	mem=""
	if [ "$KILL_GPU_PROCS" != "1" ] || ! command -v nvidia-smi >/dev/null 2>&1
	then
		return 0
	fi
	nvidia-smi --query-compute-apps=pid,used_memory --format=csv,noheader,nounits 2>/dev/null | while IFS=, read -r pid mem
	do
		pid="$(echo "$pid" | tr -dc '0-9')"
		mem="$(echo "$mem" | tr -dc '0-9')"
		case "$pid" in
		''|*[!0-9]*)
			continue
			;;
		esac
		if [ "$pid" -le 2 ] || [ "$pid" -eq "$$" ]
		then
			continue
		fi
		log "killing GPU compute process pid=$pid used_gpu_mib=${mem:-unknown}"
		kill -9 "$pid" >/dev/null 2>&1 || true
	done
}

kill_top_memory_processes()
{
	ps -eo pid=,ppid=,user=,rss=,comm=,args= --sort=-rss 2>/dev/null | awk -v min="$MIN_KILL_RSS_KB" -v limit="$TOP_MEM_COUNT" -v self="$$" '
	function protected(pid,ppid,user,rss,comm,args) {
		if (pid <= 2 || pid == self || ppid == self)
			return 1
		if (comm ~ /^(\[.*\]|systemd|systemctl|sshd|ssh|NetworkManager|wpa_supplicant|systemd-network|systemd-resolve|resolved|dbus-daemon|avahi-daemon|chronyd|systemd-journal|systemd-udevd|login|agetty|sudo|su|sh|bash|dash|awk|ps|logger)$/)
			return 1
		if (args ~ /ds4-sshd-watchdog/)
			return 1
		return 0
	}
	BEGIN {
		killed = 0
	}
	{
		pid = $1
		ppid = $2
		user = $3
		rss = $4
		comm = $5
		args = ""
		for (i=6; i<=NF; i++)
			args = args $i (i<NF ? " " : "")
		if (rss < min)
			next
		if (protected(pid,ppid,user,rss,comm,args))
			next
		printf "%s %s %s %s\n", pid, rss, comm, args
		killed++
		if (killed >= limit)
			exit
	}' | while read -r pid rss comm args
	do
		case "$pid" in
		''|*[!0-9]*)
			continue
			;;
		esac
		log "killing top memory process pid=$pid rss_kb=$rss comm=$comm args=$args"
		kill -9 "$pid" >/dev/null 2>&1 || true
	done
}

kill_heavy_runtimes()
{
	log "killing allowlisted and memory-heavy runtimes"
	kill_allowlisted_containers
	kill_allowlisted_processes
	kill_gpu_compute_processes
	kill_top_memory_processes
}

clear_failures()
{
	mkdir -p "$STATE_DIR"
	printf '0\n' > "$FAIL_FILE"
}

record_failure()
{
	old=0
	mkdir -p "$STATE_DIR"
	if [ -r "$FAIL_FILE" ]
	then
		old="$(cat "$FAIL_FILE" 2>/dev/null || echo 0)"
	fi
	case "$old" in
	''|*[!0-9]*)
		old=0
		;;
	esac
	new=$((old + 1))
	printf '%s\n' "$new" > "$FAIL_FILE"
	echo "$new"
}

maybe_reboot()
{
	failures="$1"
	if [ "$REBOOT_AFTER" = "0" ] || [ "$REBOOT_AFTER" = "" ]
	then
		return 0
	fi
	case "$REBOOT_AFTER" in
	*[!0-9]*)
		log "invalid DS4_WATCHDOG_REBOOT_AFTER=$REBOOT_AFTER; reboot escalation disabled"
		return 0
		;;
	esac
	if [ "$failures" -lt "$REBOOT_AFTER" ]
	then
		return 0
	fi
	log "SSH still wedged after $failures failures; rebooting by watchdog policy"
	systemctl reboot --force
}

run_rescue()
{
	reason="$1"
	log "$reason; restarting ssh"
	restart_ssh || true
	sleep 2
	if probe_ssh
	then
		log "SSH banner recovered after restart"
		clear_failures
		return 0
	fi
	log "SSH banner still failing after restart; escalating to runtime and memory-hog kill"
	kill_heavy_runtimes
	sleep 5
	restart_ssh || true
	sleep 2
	if probe_ssh
	then
		log "SSH banner recovered after runtime and memory-hog kill"
		clear_failures
		return 0
	fi
	failures="$(record_failure)"
	log "SSH banner still failing after escalation; consecutive_failures=$failures"
	maybe_reboot "$failures"
	return 1
}

mkdir -p "$STATE_DIR"
if ! mkdir "$LOCK_DIR" 2>/dev/null
then
	log "previous watchdog run still active; skipping"
	exit 0
fi
trap 'rmdir "$LOCK_DIR" 2>/dev/null || true' EXIT INT TERM

case "${1:-}" in
--force|rescue|rescue-now)
	run_rescue "forced local self-rescue requested"
	exit $?
	;;
esac

if probe_ssh
then
	clear_failures
	exit 0
fi

run_rescue "local SSH banner probe failed"
exit $?
