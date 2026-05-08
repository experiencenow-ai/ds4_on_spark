# Spark0 Initial Probe

Date: 2026-05-08 from the Mac Studio workspace.

Host:

- mDNS name: `aitopatom-9ab9.local`
- Linux hostname: `aitopatom-9ab9`
- Login user used for probes: `spark0`
- SSH key auth: working from the Mac with `/Users/mac/.ssh/id_rsa`

Operating system:

- Ubuntu 24.04.4 LTS
- Kernel: `6.17.0-1014-nvidia`
- Architecture: `aarch64`

CPU and memory:

- 20 CPU cores total
- 10x Cortex-X925, max 3.9 GHz
- 10x Cortex-A725, max 2.808 GHz
- 119 GiB system memory visible to Linux
- 15 GiB swap

GPU:

- `NVIDIA GB10`
- CUDA compute capability: `12.1`
- Driver: `580.142`
- CUDA runtime reported by `nvidia-smi`: `13.0`
- Idle probe: 47 C, 0% utilization, about 12 W
- CUDA toolkit packages are installed, including `cuda-toolkit-13-0`
- `/usr/local/cuda/bin/nvcc` exists
- PyTorch is not installed in the default Python environment

Storage:

- Root filesystem: 3.7 TiB NVMe partition
- Used during probe: 38 GiB
- Available during probe: 3.5 TiB

Network:

- Wired interface: `enP7s7`
- Wired IPv4: `10.0.0.2/24`
- Wired MTU: 9000
- Wi-Fi interface: `wlP9s9`
- Wi-Fi IPv4 during probe: `172.16.11.228/24`
- Default route currently uses Wi-Fi

Immediate implications:

- The Spark is ready for CUDA compile/probe work.
- Direct Mac-to-Spark wired IPv4 still needs the Mac to have a `10.0.0.0/24`
  address, for example `10.0.0.1/24` on the Mac wired port.
- Until that alias is set, SSH by hostname may route over Wi-Fi/link-local.
- The next useful probe is a tiny CUDA device property binary compiled with
  `/usr/local/cuda/bin/nvcc`, because `torch.cuda` is unavailable.
