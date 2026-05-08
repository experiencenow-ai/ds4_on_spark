#!/usr/bin/env sh
set -eu

target="${1:-spark0@aitopatom-9ab9.local}"
SSH_OPTS="${SSH_OPTS:--o BatchMode=yes -o ConnectTimeout=10 -o StrictHostKeyChecking=accept-new -o UserKnownHostsFile=/private/tmp/ds4_spark_known_hosts}"

ssh $SSH_OPTS "$target" 'set -eu
echo "== identity =="
hostname
id
uname -a
echo
echo "== os =="
if [ -r /etc/os-release ]; then
    cat /etc/os-release
fi
echo
echo "== cpu =="
lscpu || true
echo
echo "== memory =="
free -h || true
echo
echo "== pci nvidia =="
lspci | grep -i nvidia || true
echo
echo "== nvidia-smi =="
nvidia-smi || true
echo
echo "== cuda =="
command -v nvcc >/dev/null 2>&1 && nvcc --version || true
[ -x /usr/local/cuda/bin/nvcc ] && /usr/local/cuda/bin/nvcc --version || true
command -v python3 >/dev/null 2>&1 && python3 - <<'"'"'PY'"'"' || true
try:
    import torch
    print("torch", torch.__version__)
    print("cuda available", torch.cuda.is_available())
    if torch.cuda.is_available():
        print("device", torch.cuda.get_device_name(0))
        print("capability", torch.cuda.get_device_capability(0))
except Exception as e:
    print("torch probe failed:", e)
PY
echo
echo "== network =="
ip addr || true
ip route || true
echo
echo "== storage =="
df -h / /home || true
lsblk -o NAME,SIZE,TYPE,MOUNTPOINTS || true
'
