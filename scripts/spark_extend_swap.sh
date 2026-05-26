#!/bin/sh
set -eu

usage()
{
	echo "usage: $0 [swapfile] [gib]" >&2
	exit 1
}

swapfile="${1:-/swap-extra-16g.img}"
gib="${2:-16}"
case "$swapfile" in
/*)
	;;
*)
	usage
	;;
esac
case "$gib" in
''|*[!0-9]*)
	usage
	;;
esac

if swapon --show=NAME --noheadings | grep -qx "$swapfile"
then
	echo "swap already active: $swapfile"
	exit 0
fi

if [ ! -f "$swapfile" ]
then
	fallocate -l "${gib}G" "$swapfile"
	chmod 600 "$swapfile"
	mkswap "$swapfile"
fi

swapon "$swapfile"
if ! grep -q "^$swapfile " /etc/fstab
then
	printf '%s none swap sw 0 0\n' "$swapfile" >> /etc/fstab
fi
swapon --show
