#!/usr/bin/env bash
set -euo pipefail

TARGET_VERSION="${DS4_NVIDIA_DRIVER_VERSION:-580.159.03-0ubuntu0.24.04.1}"
APPLY=0
PRUNE_VISUAL=0
PRUNE_STATION_APPS=0
REBOOT=0

usage()
{
    cat <<USAGE
usage: $0 [--check] [--apply] [--prune-visual-tools] [--prune-station-apps] [--reboot]

Align this Spark node to the DS4 NVIDIA driver baseline:
  ${TARGET_VERSION}

Default mode is --check. Use --apply under sudo to install the pinned driver
package family. Use --prune-visual-tools to remove CUDA visual/profiling tools
that are not needed for inference. Use --prune-station-apps only if this node
does not need desktop station apps.

Environment:
  DS4_NVIDIA_DRIVER_VERSION   override target package version
USAGE
}

while [ "$#" -gt 0 ]; do
    case "$1" in
        --check)
            APPLY=0
            ;;
        --apply)
            APPLY=1
            ;;
        --prune-visual-tools)
            PRUNE_VISUAL=1
            ;;
        --prune-station-apps)
            PRUNE_STATION_APPS=1
            ;;
        --reboot)
            REBOOT=1
            ;;
        -h|--help)
            usage
            exit 0
            ;;
        *)
            echo "unknown argument: $1" >&2
            usage >&2
            exit 2
            ;;
    esac
    shift
done

current_driver()
{
    nvidia-smi --query-gpu=driver_version --format=csv,noheader 2>/dev/null | head -n 1 || true
}

pkg_has_version()
{
    apt-cache policy "$1" 2>/dev/null | awk -v target="${TARGET_VERSION}" '$1 == target || $2 == target { found=1 } END { exit(found == 1 ? 0 : 1) }'
}

require_root()
{
    if [ "$(id -u)" -ne 0 ]; then
        echo "error: --apply/--prune/--reboot requires sudo/root" >&2
        exit 1
    fi
}

mark_installed_manual()
{
    manual_pkgs=()
    for pkg in "$@"; do
        status="$(dpkg-query -W -f='${Status}' "$pkg" 2>/dev/null || true)"
        if [ "$status" = "install ok installed" ]; then
            manual_pkgs+=("$pkg")
        fi
    done
    if [ "${#manual_pkgs[@]}" -ne 0 ]; then
        apt-mark manual "${manual_pkgs[@]}"
    fi
}

driver_upstream="${TARGET_VERSION%%-*}"
firmware_pkg="nvidia-firmware-580-${driver_upstream}"
driver_pkgs=(
    nvidia-driver-580-open
    nvidia-kernel-source-580-open
    nvidia-kernel-common-580
    nvidia-compute-utils-580
    nvidia-firmware-580-"${driver_upstream}"
    libnvidia-cfg1-580
    libnvidia-common-580
    libnvidia-compute-580
    libnvidia-decode-580
    libnvidia-encode-580
    libnvidia-extra-580
    libnvidia-fbc1-580
    libnvidia-gl-580
)
visual_pkgs=(
    cuda-visual-tools-13-0
    cuda-nsight-compute-13-0
    cuda-nsight-systems-13-0
    cuda-documentation-13-0
)
cuda_keep_pkgs=(
    cuda-cccl-13-0
    cuda-command-line-tools-13-0
    cuda-compiler-13-0
    cuda-crt-13-0
    cuda-cudart-13-0
    cuda-cudart-dev-13-0
    cuda-culibos-dev-13-0
    cuda-cuobjdump-13-0
    cuda-cupti-13-0
    cuda-cupti-dev-13-0
    cuda-cuxxfilt-13-0
    cuda-driver-dev-13-0
    cuda-gdb-13-0
    cuda-libraries-13-0
    cuda-libraries-dev-13-0
    cuda-nvcc-13-0
    cuda-nvdisasm-13-0
    cuda-nvml-dev-13-0
    cuda-nvprune-13-0
    cuda-nvrtc-13-0
    cuda-nvrtc-dev-13-0
    cuda-nvtx-13-0
    cuda-profiler-api-13-0
    cuda-sanitizer-13-0
    gds-tools-13-0
    libcublas-13-0
    libcublas-dev-13-0
    libcufft-13-0
    libcufft-dev-13-0
    libcufile-13-0
    libcufile-dev-13-0
    libcurand-13-0
    libcurand-dev-13-0
    libcusolver-13-0
    libcusolver-dev-13-0
    libcusparse-13-0
    libcusparse-dev-13-0
    libnpp-13-0
    libnpp-dev-13-0
    libnvfatbin-13-0
    libnvfatbin-dev-13-0
    libnvjitlink-13-0
    libnvjitlink-dev-13-0
    libnvjpeg-13-0
    libnvjpeg-dev-13-0
    libnvptxcompiler-13-0
    libnvvm-13-0
)
station_pkgs=(
    nvidia-system-station-games
    nvidia-system-station-apps
)
install_specs=()
missing=0

echo "node=$(hostname)"
echo "kernel=$(uname -r)"
echo "current_driver=$(current_driver)"
echo "target_driver_package_version=${TARGET_VERSION}"

if [ "$APPLY" -ne 0 ]; then
    require_root
    apt-get update
fi

for pkg in "${driver_pkgs[@]}"; do
    if pkg_has_version "$pkg"; then
        install_specs+=("${pkg}=${TARGET_VERSION}")
        installed="$(dpkg-query -W -f='${Version}' "$pkg" 2>/dev/null || true)"
        echo "pkg ${pkg} installed=${installed:-none} target=${TARGET_VERSION}"
    else
        echo "missing target version for package: ${pkg}" >&2
        missing=1
    fi
done

if [ "$missing" -ne 0 ]; then
    echo "error: one or more pinned packages are unavailable from apt sources" >&2
    exit 1
fi

if [ "$APPLY" -eq 0 ]; then
    echo "dry_run=1"
    echo "install command:"
    printf '  apt-get install -y'
    printf ' %q' "${install_specs[@]}"
    printf '\n'
    if [ "$PRUNE_VISUAL" -ne 0 ]; then
        echo "visual prune command:"
        printf '  apt-get purge -y'
        printf ' %q' "${visual_pkgs[@]}"
        printf '\n'
        echo "cuda keep command:"
        printf '  apt-mark manual'
        printf ' %q' "${cuda_keep_pkgs[@]}"
        printf '\n'
    fi
    if [ "$PRUNE_STATION_APPS" -ne 0 ]; then
        echo "station app prune command:"
        printf '  apt-get purge -y'
        printf ' %q' "${station_pkgs[@]}"
        printf '\n'
    fi
    exit 0
fi

apt-get install -y "${install_specs[@]}"
if [ "$PRUNE_VISUAL" -ne 0 ]; then
    apt-get purge -y "${visual_pkgs[@]}"
    mark_installed_manual "${cuda_keep_pkgs[@]}"
fi
if [ "$PRUNE_STATION_APPS" -ne 0 ]; then
    apt-get purge -y "${station_pkgs[@]}"
fi

echo "post_install_driver=$(current_driver)"
echo "reboot_required=1"
if [ "$REBOOT" -ne 0 ]; then
    systemctl reboot
fi
