#!/usr/bin/env bash
set -euo pipefail

usage()
{
	cat <<'USAGE'
Usage:
  sudo scripts/ds4_mount_external_nvme.sh --device /dev/sdX2 --migrate --persist

Purpose:
  Move a node-local $HOME/ds4_nvme tree from the root filesystem onto a real
  external NVMe partition without changing the runtime path used by DS4.

Safety:
  - Refuses to run unless root.
  - Refuses to migrate while DS4/vLLM/LMCache-looking processes are active.
  - Mounts the device at a staging path first, copies data, then swaps the
    mount onto the final target.
  - Formatting is never implicit. Use --format-ext4 only when the selected
    device can be destroyed.

Options:
  --device PATH          Block device or partition, for example /dev/sda2.
  --target PATH          Mount target. Default: /home/$SUDO_USER/ds4_nvme.
  --owner USER           Target owner. Default: $SUDO_USER.
  --migrate              Copy existing target contents onto the external disk.
  --merge-existing       Allow --migrate when the external disk is non-empty;
                         existing files are preserved and overwritten files
                         are backed up under .ds4_migrate_overwrites.
  --persist              Add/update an /etc/fstab entry for the target.
  --format-ext4          Destructively format --device as ext4 first.
  --allow-live           Do not refuse when DS4/vLLM/LMCache processes exist.
  --dry-run              Print actions without changing the system.
  -h, --help             Show this help.
USAGE
}

die()
{
	printf 'error: %s\n' "$*" >&2
	exit 1
}

run()
{
	if [ "$dry_run" = 1 ]; then
		printf 'DRY-RUN:'
		printf ' %q' "$@"
		printf '\n'
	else
		"$@"
	fi
}

need_cmd()
{
	command -v "$1" >/dev/null 2>&1 || die "missing required command: $1"
}

require_root()
{
	if [ "$(id -u)" != 0 ]; then
		die "run with sudo/root"
	fi
}

resolve_owner()
{
	owner="${owner:-${SUDO_USER:-}}"
	if [ -z "$owner" ] || [ "$owner" = root ]; then
		die "could not infer owner; pass --owner sparkN"
	fi
	uid="$(id -u "$owner")" || die "unknown owner: $owner"
	gid="$(id -g "$owner")" || die "unknown owner: $owner"
	target="${target:-/home/$owner/ds4_nvme}"
}

check_live_processes()
{
	if [ "$allow_live" = 1 ]; then
		return
	fi
	if pgrep -af 'ds4_run_vllm_from_source|vllm.entrypoints|LMCache|lmcache|ds4_pipeline|ds4_coordinator' >/tmp/ds4_nvme_live_processes.$$ 2>/dev/null; then
		cat /tmp/ds4_nvme_live_processes.$$ >&2
		rm -f /tmp/ds4_nvme_live_processes.$$
		die "DS4/vLLM/LMCache-looking processes are active; stop services first or pass --allow-live"
	fi
	rm -f /tmp/ds4_nvme_live_processes.$$
}

device_uuid()
{
	blkid -s UUID -o value "$device" 2>/dev/null || true
}

device_fstype()
{
	blkid -s TYPE -o value "$device" 2>/dev/null || true
}

mount_options_for()
{
	case "$1" in
		exfat|vfat)
			printf 'nofail,uid=%s,gid=%s,umask=022,x-systemd.device-timeout=10' "$uid" "$gid"
			;;
		*)
			printf 'defaults,nofail,x-systemd.device-timeout=10'
			;;
	esac
}

mount_runtime_options_for()
{
	case "$1" in
		exfat|vfat)
			printf 'uid=%s,gid=%s,umask=022' "$uid" "$gid"
			;;
		*)
			printf ''
			;;
	esac
}

is_portable_fs()
{
	case "$(device_fstype)" in
		exfat|vfat)
			return 0
			;;
		*)
			return 1
			;;
	esac
}

mount_device()
{
	mp="$1"
	opts="$(mount_runtime_options_for "$(device_fstype)")"
	if [ -n "$opts" ]; then
		run mount -o "$opts" "$device" "$mp"
	else
		run mount "$device" "$mp"
	fi
}

persist_fstab()
{
	uuid="$(device_uuid)"
	fstype="$(device_fstype)"
	[ -n "$uuid" ] || die "could not read UUID for $device"
	[ -n "$fstype" ] || die "could not read filesystem type for $device"
	opts="$(mount_options_for "$fstype")"
	line="UUID=$uuid $target $fstype $opts 0 0"
	if grep -qE "[[:space:]]$(printf '%s' "$target" | sed 's/[.[\*^$()+?{|]/\\&/g')[[:space:]]" /etc/fstab; then
		run cp /etc/fstab "/etc/fstab.ds4_nvme_backup.$(date +%Y%m%dT%H%M%S)"
		if [ "$dry_run" = 1 ]; then
			printf 'DRY-RUN: replace /etc/fstab entry for %s with: %s\n' "$target" "$line"
		else
			python3 - "$target" "$line" <<'PY'
from pathlib import Path
import sys
target = sys.argv[1]
line = sys.argv[2]
path = Path("/etc/fstab")
rows = path.read_text(encoding="utf-8").splitlines()
out = []
done = False
for row in rows:
    parts = row.split()
    if len(parts) >= 2 and parts[1] == target:
        if not done:
            out.append(line)
            done = True
        continue
    out.append(row)
if not done:
    out.append(line)
path.write_text("\n".join(out) + "\n", encoding="utf-8")
PY
		fi
	else
		run cp /etc/fstab "/etc/fstab.ds4_nvme_backup.$(date +%Y%m%dT%H%M%S)"
		if [ "$dry_run" = 1 ]; then
			printf 'DRY-RUN: append to /etc/fstab: %s\n' "$line"
		else
			printf '%s\n' "$line" >> /etc/fstab
		fi
	fi
}

format_ext4()
{
	[ "$format_ext4" = 1 ] || return 0
	[ -b "$device" ] || die "not a block device: $device"
	run mkfs.ext4 -F -L ds4_nvme "$device"
}

mount_staging()
{
	staging="${target}.external-staging"
	run mkdir -p "$staging"
	if mountpoint -q "$staging"; then
		return
	fi
	mount_device "$staging"
}

copy_existing_tree()
{
	[ "$migrate" = 1 ] || return 0
	[ -d "$target" ] || run mkdir -p "$target"
	if [ "$merge_existing" = 0 ] && find "$staging" -mindepth 1 -maxdepth 1 | grep -q .; then
		die "staging mount $staging is not empty; refusing to merge blindly"
	fi
	if command -v rsync >/dev/null 2>&1; then
		backup_dir="$staging/.ds4_migrate_overwrites/$(date +%Y%m%dT%H%M%S)"
		if is_portable_fs; then
			run rsync -rt --omit-dir-times --no-perms --no-owner --no-group --backup --backup-dir "$backup_dir" "$target"/ "$staging"/
		else
			run rsync -aH --numeric-ids --backup --backup-dir "$backup_dir" "$target"/ "$staging"/
		fi
	else
		[ "$merge_existing" = 0 ] || die "rsync is required for --merge-existing"
		run cp -a "$target"/. "$staging"/
	fi
	if ! is_portable_fs; then
		run chown -R "$uid:$gid" "$staging"
	fi
}

swap_mount()
{
	backup="${target}.rootfs-backup.$(date +%Y%m%dT%H%M%S)"
	if mountpoint -q "$target"; then
		printf '%s is already a mountpoint\n' "$target"
		return
	fi
	run mv "$target" "$backup"
	run mkdir -p "$target"
	run chown "$uid:$gid" "$target"
	run umount "$staging"
	mount_device "$target"
	if ! is_portable_fs; then
		run chown "$uid:$gid" "$target"
	fi
	printf 'mounted %s at %s; old rootfs tree is %s\n' "$device" "$target" "$backup"
}

device=""
target=""
owner=""
migrate=0
merge_existing=0
persist=0
format_ext4=0
allow_live=0
dry_run=0

while [ $# -gt 0 ]; do
	case "$1" in
		--device)
			device="${2:-}"
			shift 2
			;;
		--target)
			target="${2:-}"
			shift 2
			;;
		--owner)
			owner="${2:-}"
			shift 2
			;;
		--migrate)
			migrate=1
			shift
			;;
		--merge-existing)
			merge_existing=1
			shift
			;;
		--persist)
			persist=1
			shift
			;;
		--format-ext4)
			format_ext4=1
			shift
			;;
		--allow-live)
			allow_live=1
			shift
			;;
		--dry-run)
			dry_run=1
			shift
			;;
		-h|--help)
			usage
			exit 0
			;;
		*)
			die "unknown option: $1"
			;;
	esac
done

require_root
resolve_owner
[ -n "$device" ] || die "pass --device /dev/..."
[ -b "$device" ] || die "not a block device: $device"
need_cmd blkid
need_cmd mount
need_cmd umount
need_cmd find
need_cmd pgrep
check_live_processes
format_ext4
mount_staging
copy_existing_tree
swap_mount
if [ "$persist" = 1 ]; then
	persist_fstab
fi
printf 'done: %s now uses %s (%s)\n' "$target" "$device" "$(device_fstype)"
