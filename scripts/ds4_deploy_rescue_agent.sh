#!/bin/sh
set -eu

usage()
{
	echo "usage: DS4_RESCUE_ROOT=1 $0 spark2 spark3 ..." >&2
	exit 1
}

if [ "$#" -eq 0 ]
then
	usage
fi

repo_dir=$(CDPATH= cd -- "$(dirname -- "$0")/.." && pwd)
token_file="${DS4_RESCUE_TOKEN_FILE:-/private/tmp/ds4_rescue_token}"
sudo_password="${DS4_SUDO_PASSWORD:-}"
ssh_opts="${DS4_SSH_OPTS:-}"
scp_opts="${DS4_SCP_OPTS:-$ssh_opts}"
if [ ! -s "$token_file" ]
then
	umask 077
	python3 - <<'PY' > "$token_file"
import secrets

print(secrets.token_urlsafe(48))
PY
fi
keys_file="$(mktemp)"
cleanup()
{
	rm -f "$keys_file"
}
trap cleanup EXIT INT TERM

ensure_peer_key()
{
	host="$1"
	ssh $ssh_opts "$host" 'mkdir -p "$HOME/.ssh"; chmod 700 "$HOME/.ssh"; if [ ! -s "$HOME/.ssh/id_ed25519.pub" ]; then ssh-keygen -q -t ed25519 -N "" -f "$HOME/.ssh/id_ed25519" -C "ds4-peer-ssh:$(whoami)@$(hostname)"; fi; chmod 600 "$HOME/.ssh/id_ed25519"; chmod 644 "$HOME/.ssh/id_ed25519.pub"; cat "$HOME/.ssh/id_ed25519.pub"'
}

install_peer_keys()
{
	host="$1"
	ssh $ssh_opts "$host" 'mkdir -p "$HOME/.ssh"; chmod 700 "$HOME/.ssh"; touch "$HOME/.ssh/authorized_keys"; chmod 600 "$HOME/.ssh/authorized_keys"; tmp="$(mktemp)"; cat > "$tmp"; while IFS= read -r key; do [ "$key" != "" ] || continue; grep -qxF "$key" "$HOME/.ssh/authorized_keys" || printf "%s\n" "$key" >> "$HOME/.ssh/authorized_keys"; done < "$tmp"; rm -f "$tmp"' < "$keys_file"
}

copy_payload()
{
	host="$1"
	ssh $ssh_opts "$host" 'mkdir -p "$HOME/.ds4-rescue" "$HOME/.config/systemd/user"'
	scp $scp_opts "$repo_dir/scripts/ds4_rescue_agent.py" "$host:.ds4-rescue/ds4_rescue_agent.py"
	scp $scp_opts "$repo_dir/scripts/ds4_rescue_agent.service" "$host:.config/systemd/user/ds4-rescue-agent.service"
	scp $scp_opts "$repo_dir/scripts/ds4_rescue_client.py" "$host:.ds4-rescue/ds4_rescue_client.py"
	scp $scp_opts "$repo_dir/scripts/ds4_peer_ssh_heartbeat.py" "$host:.ds4-rescue/ds4_peer_ssh_heartbeat.py"
	scp $scp_opts "$repo_dir/scripts/spark_memory_launch_guard.py" "$host:.ds4-rescue/spark_memory_launch_guard.py"
	scp $scp_opts "$repo_dir/scripts/spark_extend_swap.sh" "$host:.ds4-rescue/spark_extend_swap.sh"
	scp $scp_opts "$repo_dir/scripts/ds4-peer-ssh-heartbeat.service" "$host:.config/systemd/user/ds4-peer-ssh-heartbeat.service"
	scp $scp_opts "$repo_dir/scripts/ds4-peer-ssh-heartbeat.timer" "$host:.config/systemd/user/ds4-peer-ssh-heartbeat.timer"
	scp $scp_opts "$repo_dir/scripts/ds4_sshd_watchdog.sh" "$host:.ds4-rescue/ds4_sshd_watchdog.sh"
	scp $scp_opts "$repo_dir/scripts/ds4_install_sshd_watchdog.sh" "$host:.ds4-rescue/ds4_install_sshd_watchdog.sh"
	scp $scp_opts "$repo_dir/scripts/ds4_root_watchdog_install_root_once.sh" "$host:.ds4-rescue/ds4_root_watchdog_install_root_once.sh"
	scp $scp_opts "$repo_dir/scripts/ds4-sshd-watchdog.service" "$host:.ds4-rescue/ds4-sshd-watchdog.service"
	scp $scp_opts "$repo_dir/scripts/ds4-sshd-watchdog.timer" "$host:.ds4-rescue/ds4-sshd-watchdog.timer"
	scp $scp_opts "$repo_dir/scripts/ds4-sshd-rescue.sudoers" "$host:.ds4-rescue/ds4-sshd-rescue.sudoers"
	scp $scp_opts "$repo_dir/scripts/ds4-sshd-rescue.conf" "$host:.ds4-rescue/ds4-sshd-rescue.conf"
	scp $scp_opts "$token_file" "$host:.ds4-rescue/token"
}

start_user_service()
{
	host="$1"
	ssh $ssh_opts "$host" 'chmod 700 "$HOME/.ds4-rescue"; mkdir -p "$HOME/.ds4-rescue/peer-heartbeats"; chmod 700 "$HOME/.ds4-rescue/peer-heartbeats"; chmod 600 "$HOME/.ds4-rescue/token"; chmod 755 "$HOME/.ds4-rescue/"*.sh "$HOME/.ds4-rescue/"*.py; systemctl --user daemon-reload; systemctl --user enable ds4-rescue-agent ds4-peer-ssh-heartbeat.timer; systemctl --user restart ds4-rescue-agent; systemctl --user restart ds4-peer-ssh-heartbeat.timer; systemctl --user --no-pager --plain status ds4-rescue-agent | sed -n "1,8p"; systemctl --user --no-pager --plain list-timers ds4-peer-ssh-heartbeat.timer'
}

install_root_watchdog()
{
	host="$1"
	if [ "${DS4_REMOTE_SUDO_TTY:-0}" = "1" ]
	then
		ssh $ssh_opts -tt "$host" 'sudo "$HOME/.ds4-rescue/ds4_root_watchdog_install_root_once.sh"'
	elif [ "$sudo_password" = "" ]
	then
		ssh $ssh_opts "$host" 'sudo -n "$HOME/.ds4-rescue/ds4_root_watchdog_install_root_once.sh"'
	else
		printf '%s\n' "$sudo_password" | ssh $ssh_opts "$host" 'sudo -S -p "" "$HOME/.ds4-rescue/ds4_root_watchdog_install_root_once.sh"'
	fi
}

echo "==> preparing peer SSH key mesh"
for host in "$@"
do
	echo "==> $host: ensure peer SSH key"
	ensure_peer_key "$host" >> "$keys_file"
done
for host in "$@"
do
	echo "==> $host: install peer authorized keys"
	install_peer_keys "$host"
done

for host in "$@"
do
	echo "==> $host: copy rescue payload"
	copy_payload "$host"
	echo "==> $host: start user rescue agent"
	start_user_service "$host"
	if [ "${DS4_RESCUE_ROOT:-0}" = "1" ]
	then
		echo "==> $host: install root watchdog and enable linger"
		install_root_watchdog "$host"
	else
		echo "==> $host: skipped root watchdog; rerun with DS4_RESCUE_ROOT=1"
	fi
done
