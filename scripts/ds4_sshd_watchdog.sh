#!/bin/sh
set -u

LOGTAG=ds4-sshd-watchdog
STATE_DIR=/run/ds4-rescue
FAIL_FILE=$STATE_DIR/sshd-watchdog.failures
LOCK_DIR=$STATE_DIR/sshd-watchdog.lock
REBOOT_AFTER="${DS4_WATCHDOG_REBOOT_AFTER:-3}"
TOP_MEM_COUNT="${DS4_WATCHDOG_KILL_TOP_MEM_COUNT:-16}"
MIN_KILL_RSS_KB="${DS4_WATCHDOG_MIN_KILL_RSS_KB:-262144}"
KILL_GPU_PROCS="${DS4_WATCHDOG_KILL_GPU_PROCS:-1}"
PEER_DIR="${DS4_WATCHDOG_PEER_DIR:-}"
PEER_STALE_SECONDS="${DS4_WATCHDOG_PEER_STALE_SECONDS:-300}"
PEER_MIN_FRESH="${DS4_WATCHDOG_PEER_MIN_FRESH:-1}"
PEER_BOOT_GRACE_SECONDS="${DS4_WATCHDOG_PEER_BOOT_GRACE_SECONDS:-600}"
RUNTIME_LOAD_GRACE_SECONDS="${DS4_WATCHDOG_RUNTIME_LOAD_GRACE_SECONDS:-2400}"
RUNTIME_LOAD_FILE=$STATE_DIR/runtime-load-grace-start

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

peer_dir()
{
	if [ "$PEER_DIR" != "" ]
	then
		printf '%s\n' "$PEER_DIR"
		return 0
	fi
	for dir in /home/spark*/.ds4-rescue/peer-heartbeats
	do
		if [ -d "$dir" ]
		then
			printf '%s\n' "$dir"
			return 0
		fi
	done
	return 1
}

peer_health()
{
	dir="$(peer_dir 2>/dev/null || true)"
	if [ "$dir" = "" ]
	then
		printf 'peer_health=disabled reason=no-peer-dir\n'
		return 0
	fi
	DS4_PEER_DIR="$dir" DS4_PEER_STALE_SECONDS="$PEER_STALE_SECONDS" DS4_PEER_MIN_FRESH="$PEER_MIN_FRESH" DS4_PEER_BOOT_GRACE_SECONDS="$PEER_BOOT_GRACE_SECONDS" python3 - <<'PY'
import glob
import json
import os
import sys
import time

def intval(name, default):
    try:
        return int(os.environ.get(name, str(default)))
    except Exception:
        return default

peer_dir = os.environ["DS4_PEER_DIR"]
stale = max(30, intval("DS4_PEER_STALE_SECONDS", 300))
min_fresh = max(1, intval("DS4_PEER_MIN_FRESH", 1))
boot_grace = max(stale, intval("DS4_PEER_BOOT_GRACE_SECONDS", 600))
now = int(time.time())
try:
    with open("/proc/uptime", "r", encoding="utf-8") as fp:
        uptime = int(float(fp.read().split()[0]))
except Exception:
    uptime = boot_grace + 1
fresh = 0
healthy = 0
degraded = 0
newest_age = None
seen_files = 0
for path in glob.glob(os.path.join(peer_dir, "*.json")):
    seen_files += 1
    try:
        with open(path, "r", encoding="utf-8") as fp:
            rec = json.load(fp)
    except Exception:
        continue
    checked = int(float(rec.get("checked_at_unix", 0)))
    age = now - checked
    if newest_age is None or age < newest_age:
        newest_age = age
    if checked <= 0 or age > stale:
        continue
    fresh += 1
    if rec.get("ssh_exec_ok") is True:
        healthy += 1
    else:
        degraded += 1
summary = "peer_health=%s dir=%s fresh=%d healthy=%d degraded=%d newest_age=%s min_fresh=%d stale_s=%d" % (
    "%s", peer_dir, fresh, healthy, degraded, "none" if newest_age is None else newest_age, min_fresh, stale
)
if healthy >= min_fresh:
    print(summary % "healthy")
    sys.exit(0)
if seen_files == 0:
    try:
        dir_age = now - int(os.stat(peer_dir).st_mtime)
    except Exception:
        dir_age = stale
    if dir_age < stale:
        print((summary % "init-grace") + " dir_age=%d" % dir_age)
        sys.exit(0)
if uptime < boot_grace and fresh == 0:
    print(summary % "boot-grace")
    sys.exit(0)
if fresh >= min_fresh:
    print(summary % "degraded")
    sys.exit(10)
print(summary % "stale")
sys.exit(11)
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

allowlisted_runtime_present()
{
	if command -v docker >/dev/null 2>&1
	then
		if docker ps --format '{{.Names}}' 2>/dev/null | grep -Eq '^(vllm_deepseek_v4_flash|vllm_|ds4_vllm_|centaur_vllm_)'
		then
			return 0
		fi
	fi
	if pgrep -f '/usr/local/bin/vllm serve|/usr/bin/python3 /usr/local/bin/vllm serve|vllm serve /models/|VLLM::' >/dev/null 2>&1
	then
		return 0
	fi
	return 1
}

runtime_age_seconds()
{
	best=""
	now="$(date +%s)"
	if command -v docker >/dev/null 2>&1
	then
		for name in $(docker ps --format '{{.Names}}' 2>/dev/null | grep -E '^(vllm_deepseek_v4_flash|vllm_|ds4_vllm_|centaur_vllm_)' || true)
		do
			started="$(docker inspect -f '{{.State.StartedAt}}' "$name" 2>/dev/null || true)"
			start_s="$(date -d "$started" +%s 2>/dev/null || echo '')"
			case "$start_s" in
			''|*[!0-9]*)
				continue
				;;
			esac
			age=$((now - start_s))
			if [ "$age" -ge 0 ] && { [ "$best" = "" ] || [ "$age" -lt "$best" ]; }
			then
				best="$age"
			fi
		done
	fi
	for pid in $(pgrep -f '/usr/local/bin/vllm serve|/usr/bin/python3 /usr/local/bin/vllm serve|vllm serve /models/|VLLM::' 2>/dev/null || true)
	do
		case "$pid" in
		''|*[!0-9]*)
			continue
			;;
		esac
		age="$(ps -o etimes= -p "$pid" 2>/dev/null | tr -dc '0-9')"
		case "$age" in
		''|*[!0-9]*)
			continue
			;;
		esac
		if [ "$best" = "" ] || [ "$age" -lt "$best" ]
		then
			best="$age"
		fi
	done
	if [ "$best" != "" ]
	then
		printf '%s\n' "$best"
		return 0
	fi
	return 1
}

runtime_load_grace_active()
{
	now="$(date +%s)"
	case "$RUNTIME_LOAD_GRACE_SECONDS" in
	''|*[!0-9]*|0)
		return 1
		;;
	esac
	if ! allowlisted_runtime_present
	then
		rm -f "$RUNTIME_LOAD_FILE" 2>/dev/null || true
		return 1
	fi
	runtime_age="$(runtime_age_seconds 2>/dev/null || echo '')"
	case "$runtime_age" in
	''|*[!0-9]*)
		runtime_age=""
		;;
	esac
	if [ "$runtime_age" != "" ]
	then
		if [ "$runtime_age" -lt "$RUNTIME_LOAD_GRACE_SECONDS" ]
		then
			log "runtime load grace active runtime_age=${runtime_age}s limit=${RUNTIME_LOAD_GRACE_SECONDS}s; deferring heavy runtime kill"
			return 0
		fi
		log "runtime load grace expired runtime_age=${runtime_age}s limit=${RUNTIME_LOAD_GRACE_SECONDS}s"
		return 1
	fi
	if [ ! -r "$RUNTIME_LOAD_FILE" ]
	then
		mkdir -p "$STATE_DIR"
		printf '%s\n' "$now" > "$RUNTIME_LOAD_FILE"
	fi
	start="$(cat "$RUNTIME_LOAD_FILE" 2>/dev/null || echo "$now")"
	case "$start" in
	''|*[!0-9]*)
		start="$now"
		printf '%s\n' "$now" > "$RUNTIME_LOAD_FILE"
		;;
	esac
	age=$((now - start))
	if [ "$age" -lt "$RUNTIME_LOAD_GRACE_SECONDS" ]
	then
		log "runtime load grace active age=${age}s limit=${RUNTIME_LOAD_GRACE_SECONDS}s; deferring heavy runtime kill"
		return 0
	fi
	log "runtime load grace expired age=${age}s limit=${RUNTIME_LOAD_GRACE_SECONDS}s"
	return 1
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
	rm -f "$RUNTIME_LOAD_FILE" 2>/dev/null || true
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
	log "watchdog still failing after $failures failures; rebooting by watchdog policy"
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
	if runtime_load_grace_active
	then
		failures="$(record_failure)"
		log "SSH banner still failing after restart, but runtime load grace is active; consecutive_failures=$failures reboot_deferred=1"
		return 1
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

run_peer_rescue()
{
	reason="$1"
	log "$reason; external peer health failed; restarting ssh"
	restart_ssh || true
	sleep 2
	if runtime_load_grace_active
	then
		failures="$(record_failure)"
		log "external peer health still unhealthy, but runtime load grace is active; consecutive_failures=$failures reboot_deferred=1"
		return 1
	fi
	log "external peer health still unhealthy after ssh restart; killing heavy runtimes"
	kill_heavy_runtimes
	sleep 5
	restart_ssh || true
	failures="$(record_failure)"
	log "external peer health still awaiting recovery; consecutive_failures=$failures"
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
	peer_status="$(peer_health)"
	peer_rc=$?
	case "$peer_rc" in
	0)
		log "$peer_status"
		clear_failures
		exit 0
		;;
	10)
		run_peer_rescue "peer records fresh but external SSH unhealthy: $peer_status"
		exit $?
		;;
	11)
		run_peer_rescue "peer records stale or missing for external SSH: $peer_status"
		exit $?
		;;
	*)
		log "peer health check failed rc=$peer_rc status=$peer_status; local SSH healthy"
		clear_failures
		exit 0
		;;
	esac
	clear_failures
	exit 0
fi

run_rescue "local SSH banner probe failed"
exit $?
