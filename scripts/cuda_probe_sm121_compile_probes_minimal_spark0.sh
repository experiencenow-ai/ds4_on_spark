#!/usr/bin/env sh
set -eu

target="${1:-spark0@aitopatom-9ab9.local}"
SSH_OPTS="${SSH_OPTS:-"-o BatchMode=yes -o ConnectTimeout=10 -o ServerAliveInterval=0 -o StrictHostKeyChecking=accept-new -o UserKnownHostsFile=/private/tmp/ds4_spark_known_hosts"}"
remote_tag="${REMOTE_TAG:-"$(date -u +%Y%m%d-%H%M%S)-$$"}"
default_remote_dir="/tmp/ds4_cuda_probe_sm121_compile_probes_minimal_${remote_tag}"
REMOTE_DIR="${REMOTE_DIR:-${default_remote_dir}}"
log_path="${LOG_PATH:-}"

main() {
ssh $SSH_OPTS "$target" "set -eu
NVCC=\"\"
echo \"== nvcc ==\"
if [ -x /usr/local/cuda/bin/nvcc ]; then
	NVCC=\"/usr/local/cuda/bin/nvcc\"
elif command -v nvcc >/dev/null 2>&1; then
	NVCC=\"nvcc\"
else
	echo \"nvcc not found\" >&2
	exit 3
fi
\$NVCC --version

echo
echo \"== nvcc: --list-gpu-arch / --list-gpu-code (best-effort) ==\"
list_gpu_arch=\$(\$NVCC --list-gpu-arch 2>/dev/null || true)
if [ \"\${list_gpu_arch}\" = \"\" ]; then
	echo \"(nvcc --list-gpu-arch not supported)\"
else
	printf \"%s\n\" \"\${list_gpu_arch}\"
fi
list_gpu_code=\$(\$NVCC --list-gpu-code 2>/dev/null || true)
if [ \"\${list_gpu_code}\" = \"\" ]; then
	echo \"(nvcc --list-gpu-code not supported)\"
else
	printf \"%s\n\" \"\${list_gpu_code}\"
fi

echo
echo \"== build: sm_121 compile probes (compile-only; no link/run) ==\"
rm -rf \"$REMOTE_DIR\"
mkdir -p \"$REMOTE_DIR\"/bin

cat > \"$REMOTE_DIR\"/cuda_sm121_compile_probe_minimal.cu <<'EOF'
#include <stdint.h>

#if defined(__CUDA_ARCH__)
#if (__CUDA_ARCH__ != 1210)
#error \"sm_121 compile probe: expected __CUDA_ARCH__=1210 (sm_121)\"
#endif
#endif

__global__ void sm121_compile_probe(uint32_t *out)
{
	if ( ((int32_t)threadIdx.x) == 0 )
	{
#if defined(__CUDA_ARCH__)
		out[0] = (uint32_t)__CUDA_ARCH__;
#else
		out[0] = 0;
#endif
	}
}
EOF

cat > \"$REMOTE_DIR\"/cuda_compute121_compile_probe_minimal.cu <<'EOF'
#include <stdint.h>

#if defined(__CUDA_ARCH__)
#if (__CUDA_ARCH__ != 1210)
#error \"compute_121 compile probe: expected __CUDA_ARCH__=1210 (compute_121)\"
#endif
#endif

__global__ void compute121_compile_probe(uint32_t *out)
{
	if ( ((int32_t)threadIdx.x) == 0 )
	{
#if defined(__CUDA_ARCH__)
		out[0] = (uint32_t)__CUDA_ARCH__;
#else
		out[0] = 0;
#endif
	}
}
EOF

compile_probe() {
	tag=\"\$1\"
	src=\"\$2\"
	shift 2
	set +e
	\$NVCC -O2 -std=c++17 \"\$@\" -c -o \"$REMOTE_DIR\"/bin/\"\${tag}\".o \"$REMOTE_DIR\"/\"\${src}\" 2>\"$REMOTE_DIR\"/bin/\"\${tag}\".err
	rc=\$?
	set -e
	if [ \$rc -eq 0 ]; then
		echo \"\${tag}: OK\"
		return 0
	fi
	echo \"\${tag}: FAILED rc=\$rc\" >&2
	head -n 60 \"$REMOTE_DIR\"/bin/\"\${tag}\".err || true
	return 1
}

compile_probe sm121_arch_sm_121 cuda_sm121_compile_probe_minimal.cu -arch=sm_121
compile_probe sm121_gpuarch_sm_121 cuda_sm121_compile_probe_minimal.cu --gpu-architecture=sm_121
compile_probe sm121_gpuarchcode_sm_121 cuda_sm121_compile_probe_minimal.cu --gpu-architecture=compute_121 --gpu-code=sm_121

echo
echo \"== build: sm_121 variant alias compile probes (best-effort) ==\"
compile_probe sm121_arch_sm_121a cuda_sm121_compile_probe_minimal.cu -arch=sm_121a || true
compile_probe sm121_arch_sm_121f cuda_sm121_compile_probe_minimal.cu -arch=sm_121f || true
compile_probe sm121_gpuarch_sm_121a cuda_sm121_compile_probe_minimal.cu --gpu-architecture=sm_121a || true
compile_probe sm121_gpuarch_sm_121f cuda_sm121_compile_probe_minimal.cu --gpu-architecture=sm_121f || true

echo
echo \"== build: compute_121 compile probe (best-effort) ==\"
do_build_compute121=1
if [ \"\${list_gpu_arch}\" != \"\" ]; then
	if echo \"\${list_gpu_arch}\" | grep -q \"compute_121\"; then
		:
	else
		echo \"(nvcc --list-gpu-arch missing compute_121; skipping)\" >&2
		do_build_compute121=0
	fi
fi
if [ \"\${do_build_compute121}\" = \"1\" ]; then
	compile_probe compute121_arch_compute_121 cuda_compute121_compile_probe_minimal.cu -arch=compute_121 || true
	compile_probe compute121_gpuarch_compute_121 cuda_compute121_compile_probe_minimal.cu --gpu-architecture=compute_121 || true
	compile_probe compute121_gpuarchcode_sm_121 cuda_compute121_compile_probe_minimal.cu --gpu-architecture=compute_121 --gpu-code=sm_121 || true
fi
"
}

if [ "$log_path" = "" ]; then
	main
	exit 0
fi

mkdir -p "$(dirname "$log_path")"
printf "== cuda_probe_sm121_compile_probes_minimal_spark0 log: %s ==\n" "$(date -u +%Y-%m-%dT%H:%M:%SZ)" >> "$log_path"
tmp_out="$(mktemp "/private/tmp/ds4_cuda_probe_sm121_compile_probes_minimal_out.XXXXXX")"
set +e
main >"$tmp_out" 2>&1
rc=$?
set -e
cat "$tmp_out"
cat "$tmp_out" >> "$log_path"
rm -f "$tmp_out"
exit $rc

