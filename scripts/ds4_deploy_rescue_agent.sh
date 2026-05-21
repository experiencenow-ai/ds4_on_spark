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
if [ ! -s "$token_file" ]
then
	umask 077
	python3 - <<'PY' > "$token_file"
import secrets

print(secrets.token_urlsafe(48))
PY
fi

copy_payload()
{
	host="$1"
	ssh "$host" 'mkdir -p "$HOME/.ds4-rescue" "$HOME/.config/systemd/user"'
	scp "$repo_dir/scripts/ds4_rescue_agent.py" "$host:.ds4-rescue/ds4_rescue_agent.py"
	scp "$repo_dir/scripts/ds4_rescue_agent.service" "$host:.config/systemd/user/ds4-rescue-agent.service"
	scp "$repo_dir/scripts/ds4_rescue_client.py" "$host:.ds4-rescue/ds4_rescue_client.py"
	scp "$repo_dir/scripts/ds4_sshd_watchdog.sh" "$host:.ds4-rescue/ds4_sshd_watchdog.sh"
	scp "$repo_dir/scripts/ds4_install_sshd_watchdog.sh" "$host:.ds4-rescue/ds4_install_sshd_watchdog.sh"
	scp "$repo_dir/scripts/ds4-sshd-watchdog.service" "$host:.ds4-rescue/ds4-sshd-watchdog.service"
	scp "$repo_dir/scripts/ds4-sshd-watchdog.timer" "$host:.ds4-rescue/ds4-sshd-watchdog.timer"
	scp "$repo_dir/scripts/ds4-sshd-rescue.sudoers" "$host:.ds4-rescue/ds4-sshd-rescue.sudoers"
	scp "$repo_dir/scripts/ds4-sshd-rescue.conf" "$host:.ds4-rescue/ds4-sshd-rescue.conf"
	scp "$token_file" "$host:.ds4-rescue/token"
}

start_user_service()
{
	host="$1"
	ssh "$host" 'chmod 700 "$HOME/.ds4-rescue"; chmod 600 "$HOME/.ds4-rescue/token"; chmod 755 "$HOME/.ds4-rescue/"*.sh; systemctl --user daemon-reload; systemctl --user enable ds4-rescue-agent; systemctl --user restart ds4-rescue-agent; systemctl --user --no-pager --plain status ds4-rescue-agent | sed -n "1,8p"'
}

install_root_watchdog()
{
	host="$1"
	ssh -t "$host" 'sudo "$HOME/.ds4-rescue/ds4_install_sshd_watchdog.sh" "$HOME/.ds4-rescue"; sudo loginctl enable-linger "$USER"; loginctl show-user "$USER" -p Linger'
}

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
