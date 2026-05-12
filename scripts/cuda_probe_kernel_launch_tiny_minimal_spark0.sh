#!/usr/bin/env sh
set -eu

target="${1:-spark0@aitopatom-9ab9.local}"
SSH_OPTS="${SSH_OPTS:-"-o BatchMode=yes -o ConnectTimeout=10 -o ServerAliveInterval=0 -o StrictHostKeyChecking=accept-new -o UserKnownHostsFile=/private/tmp/ds4_spark_known_hosts"}"
remote_tag="${REMOTE_TAG:-"$(date -u +%Y%m%d-%H%M%S)-$$"}"
default_remote_dir="/tmp/ds4_cuda_probe_kernel_launch_tiny_minimal_${remote_tag}"
REMOTE_DIR="${REMOTE_DIR:-${default_remote_dir}}"
log_path="${LOG_PATH:-}"
nvcc_flags="${NVCC_FLAGS:-"-arch=sm_121"}"

main() {
nvcc_flags_escaped=$(printf "%s" "$nvcc_flags" | sed "s/'/'\\\\''/g")
ssh $SSH_OPTS "$target" "set -eu
NVCC_FLAGS='${nvcc_flags_escaped}'
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
echo \"== build: kernel launch tiny minimal (\${NVCC_FLAGS}) ==\"
rm -rf \"$REMOTE_DIR\"
mkdir -p \"$REMOTE_DIR\"

cat > \"$REMOTE_DIR\"/cuda_kernel_launch_tiny_minimal.cu <<'EOF'
#include <stdint.h>
#include <stdio.h>

#include <cuda_runtime.h>

__global__ void kernel_launch_tiny_minimal(void)
{
}

static int32_t ck(cudaError_t err,int32_t code,const char *what)
{
	if ( err != cudaSuccess )
	{
		fprintf(stderr,\"%s: %s\\n\",what,cudaGetErrorString(err));
		return(code);
	}
	return(0);
}

int main(int argc,char **argv)
{
	int32_t driver_v = -1,runtime_v = -1,rc = 0;
	cudaDeviceProp prop;
	(void)argc;
	(void)argv;
	(void)cudaDriverGetVersion(&driver_v);
	(void)cudaRuntimeGetVersion(&runtime_v);
	rc = ck(cudaGetDeviceProperties(&prop,0),-1,\"cudaGetDeviceProperties(0)\");
	if ( rc != 0 )
		return(rc);
	printf(\"cuda drv=%d rt=%d device[0]=%s cc=%d.%d\\n\",driver_v,runtime_v,prop.name,prop.major,prop.minor);
	kernel_launch_tiny_minimal<<<1,1>>>();
	rc = ck(cudaGetLastError(),-2,\"kernel launch\");
	if ( rc != 0 )
		return(rc);
	rc = ck(cudaDeviceSynchronize(),-3,\"cudaDeviceSynchronize\");
	if ( rc != 0 )
		return(rc);
	printf(\"kernel_launch_tiny_minimal ok\\n\");
	return(0);
}
EOF

\$NVCC -O2 -std=c++17 \${NVCC_FLAGS} -o \"$REMOTE_DIR\"/cuda_kernel_launch_tiny_minimal \"$REMOTE_DIR\"/cuda_kernel_launch_tiny_minimal.cu

echo
echo \"== run: cuda_kernel_launch_tiny_minimal ==\"
\"$REMOTE_DIR\"/cuda_kernel_launch_tiny_minimal
"
}

if [ "$log_path" = "" ]; then
	main
	exit 0
fi

mkdir -p "$(dirname "$log_path")"
printf "== cuda_probe_kernel_launch_tiny_minimal_spark0 log: %s ==\n" "$(date -u +%Y-%m-%dT%H:%M:%SZ)" >> "$log_path"
tmp_out="$(mktemp "/private/tmp/ds4_cuda_probe_kernel_launch_tiny_minimal_out.XXXXXX")"
set +e
main >"$tmp_out" 2>&1
rc=$?
set -e
cat "$tmp_out"
cat "$tmp_out" >> "$log_path"
rm -f "$tmp_out"
exit $rc
