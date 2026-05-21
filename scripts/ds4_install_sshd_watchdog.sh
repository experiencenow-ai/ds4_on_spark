#!/bin/sh
set -eu

src="${1:?usage: ds4_install_sshd_watchdog.sh /home/sparkN/.ds4-rescue}"
sshd_bin="$(command -v sshd || true)"
if [ -z "$sshd_bin" ] && [ -x /usr/sbin/sshd ]
then
	sshd_bin=/usr/sbin/sshd
fi
if [ -z "$sshd_bin" ]
then
	echo "sshd binary not found" >&2
	exit 1
fi

install -m 0755 "$src/ds4_sshd_watchdog.sh" /usr/local/sbin/ds4-sshd-watchdog
install -m 0644 "$src/ds4-sshd-watchdog.service" /etc/systemd/system/ds4-sshd-watchdog.service
install -m 0644 "$src/ds4-sshd-watchdog.timer" /etc/systemd/system/ds4-sshd-watchdog.timer
install -m 0440 "$src/ds4-sshd-rescue.sudoers" /etc/sudoers.d/ds4-sshd-rescue
visudo -cf /etc/sudoers.d/ds4-sshd-rescue
mkdir -p /etc/ssh/sshd_config.d
install -m 0644 "$src/ds4-sshd-rescue.conf" /etc/ssh/sshd_config.d/99-ds4-rescue.conf
"$sshd_bin" -t
systemctl daemon-reload
systemctl enable --now ds4-sshd-watchdog.timer
systemctl start ds4-sshd-watchdog.service
systemctl reload ssh || systemctl restart ssh || systemctl restart sshd
systemctl --no-pager --plain list-timers ds4-sshd-watchdog.timer
