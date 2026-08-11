#!/usr/bin/env bash
set -euo pipefail

FABRIC_DEVICE="${DS4_SWITCHED_FABRIC_DEVICE:-}"
FABRIC_PREFIX="${DS4_SWITCHED_FABRIC_PREFIX:-10.10.100}"
FABRIC_MTU="${DS4_SWITCHED_FABRIC_MTU:-9000}"
CX7_HOTPLUG_MARKER="${DS4_CX7_HOTPLUG_MARKER:-/etc/nvidia/cx7-hotplug-enabled}"
CX7_HOTPLUG_HANDLER="${DS4_CX7_HOTPLUG_HANDLER:-/opt/nvidia/dgx-spark-mlnx-hotplug/mtk-hotplug-handler.sh}"

fabric_devices()
{
    printf '%s\n' \
        enp1s0f0np0 \
        enp1s0f1np1 \
        enP2p1s0f0np0 \
        enP2p1s0f1np1 \
        enP2p1 \
        enP2p2
}

fabric_primary_devices()
{
    printf '%s\n' \
        enp1s0f0np0 \
        enp1s0f1np1
}

disable_cx7_hotplug_power_saving()
{
    rm -f "${CX7_HOTPLUG_MARKER}"
    if [ -x "${CX7_HOTPLUG_HANDLER}" ]; then
        "${CX7_HOTPLUG_HANDLER}" boot >/dev/null
    fi
}

select_fabric_device()
{
    local attempt carrier device
    local linked=()
    if [ -n "${FABRIC_DEVICE}" ]; then
        if [ ! -e "/sys/class/net/${FABRIC_DEVICE}" ]; then
            printf 'configured fabric device is missing: %s\n' "${FABRIC_DEVICE}" >&2
            return 3
        fi
        printf '%s\n' "${FABRIC_DEVICE}"
        return 0
    fi
    while read -r device; do
        [ -e "/sys/class/net/${device}" ] || continue
        ip link set dev "${device}" up 2>/dev/null || true
    done < <(fabric_primary_devices)
    for attempt in $(seq 1 30); do
        linked=()
        while read -r device; do
            [ -r "/sys/class/net/${device}/carrier" ] || continue
            carrier="$(cat "/sys/class/net/${device}/carrier" 2>/dev/null || true)"
            if [ "${carrier}" = "1" ]; then
                linked+=("${device}")
            fi
        done < <(fabric_primary_devices)
        if [ "${#linked[@]}" -eq 1 ]; then
            printf '%s\n' "${linked[0]}"
            return 0
        fi
        if [ "${#linked[@]}" -gt 1 ]; then
            printf 'multiple fabric devices have carrier: %s\n' "${linked[*]}" >&2
            return 4
        fi
        sleep 0.5
    done
    printf 'no Spark fabric device acquired carrier\n' >&2
    return 5
}

node_name()
{
    hostname -s
}

node_rank()
{
    if [ ! -r /etc/ds4-node-rank ]; then
        printf 'missing canonical rank file: /etc/ds4-node-rank\n' >&2
        return 2
    fi
    tr -cd '0-9' < /etc/ds4-node-rank
    printf '\n'
}

install_service()
{
    install -m 0755 "$0" /usr/local/sbin/ds4-switched-fabric-apply
    cat > /etc/systemd/system/ds4-switched-fabric.service <<'EOF'
[Unit]
Description=DS4 single-switch 100G fabric address
After=NetworkManager.service network-pre.target
Before=network-online.target
Wants=network-pre.target

[Service]
Type=oneshot
ExecStart=/usr/local/sbin/ds4-switched-fabric-apply
RemainAfterExit=yes

[Install]
WantedBy=multi-user.target
EOF
    systemctl daemon-reload
    systemctl enable ds4-switched-fabric.service
}

disable_legacy_ring()
{
    local unit dropin
    for unit in ds4-ring-200g.service ds4-ring-control-iface.service; do
        systemctl disable --now "${unit}" 2>/dev/null || true
        dropin="/etc/systemd/system/${unit}.d/zz-retired-switched-fabric.conf"
        mkdir -p "${dropin%/*}"
        cat > "${dropin}" <<'EOF'
[Unit]
ConditionPathExists=/run/ds4-ring-explicitly-enabled
EOF
        systemctl reset-failed "${unit}" 2>/dev/null || true
    done
    systemctl daemon-reload
    ip link delete ds4ring0 2>/dev/null || true
}

remove_legacy_addresses()
{
    local device
    while read -r device; do
        ip -4 addr flush dev "${device}" 2>/dev/null || true
        ip -4 route flush dev "${device}" 2>/dev/null || true
        if [ "${device}" != "${FABRIC_DEVICE}" ]; then
            ip link set dev "${device}" down 2>/dev/null || true
        fi
    done < <(fabric_devices)
}

configure_unmanaged_fabric()
{
    local device
    mkdir -p /etc/NetworkManager/conf.d
    cat > /etc/NetworkManager/conf.d/90-ds4-switched-fabric-unmanaged.conf <<'EOF'
[keyfile]
unmanaged-devices=interface-name:enp1s0f0np0;interface-name:enp1s0f1np1;interface-name:enP2p1s0f0np0;interface-name:enP2p1s0f1np1;interface-name:enP2p1;interface-name:enP2p2
EOF
    command -v nmcli >/dev/null 2>&1 || return 0
    while read -r device; do
        nmcli device disconnect "${device}" >/dev/null 2>&1 || true
        nmcli device set "${device}" managed no >/dev/null 2>&1 || true
    done < <(fabric_devices)
    nmcli general reload >/dev/null 2>&1 || true
}

remove_legacy_profiles()
{
    local row uuid
    command -v nmcli >/dev/null 2>&1 || return 0
    while IFS=: read -r row uuid; do
        [ -n "${uuid}" ] || continue
        nmcli connection delete uuid "${uuid}" >/dev/null 2>&1 || true
    done < <(nmcli -t -f NAME,UUID connection show | awk -F: '$1 ~ /^ds4-ring-/ || $1 == "ds4ring0" { print $1 ":" $2 }')
}

apply_switched_fabric()
{
    local rank address
    disable_cx7_hotplug_power_saving
    rank="$(node_rank)"
    if [ -z "${rank}" ] || ! [[ "${rank}" =~ ^[0-9]+$ ]] || [ "${rank}" -gt 15 ]; then
        printf 'unable to resolve node rank for %s\n' "${DS4_NODE_ID:-$(node_name)}" >&2
        return 2
    fi
    FABRIC_DEVICE="$(select_fabric_device)"
    address="${FABRIC_PREFIX}.$((10 + rank))/24"
    disable_legacy_ring
    remove_legacy_profiles
    configure_unmanaged_fabric
    remove_legacy_addresses
    ip link set dev "${FABRIC_DEVICE}" up
    ip link set dev "${FABRIC_DEVICE}" mtu "${FABRIC_MTU}" 2>/dev/null || true
    ip address replace "${address}" dev "${FABRIC_DEVICE}"
    printf 'switched_fabric node=%s rank=%s device=%s address=%s mtu=%s cx7_hotplug=disabled\n' \
        "${DS4_NODE_ID:-$(node_name)}" "${rank}" "${FABRIC_DEVICE}" "${address}" "${FABRIC_MTU}"
}

if [ "$(id -u)" -ne 0 ]; then
    exec sudo -- "$0" "$@"
fi

if [ "${1:-}" = "--install" ]; then
    install_service
fi
apply_switched_fabric
