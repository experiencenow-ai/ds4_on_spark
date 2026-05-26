#!/bin/sh
set -eu

user="${SUDO_USER:-}"
if [ "$user" = "" ] || [ "$user" = "root" ]
then
	user="$(logname 2>/dev/null || true)"
fi
if [ "$user" = "" ] || [ "$user" = "root" ]
then
	echo "could not identify Spark user for root watchdog install" >&2
	exit 1
fi
home_dir="$(getent passwd "$user" | awk -F: '{print $6}')"
if [ "$home_dir" = "" ]
then
	home_dir="/home/$user"
fi
"$home_dir/.ds4-rescue/ds4_install_sshd_watchdog.sh" "$home_dir/.ds4-rescue"
loginctl enable-linger "$user"
loginctl show-user "$user" -p Linger
