#!/usr/bin/env sh
set -eu

target="${1:-spark0@aitopatom-9ab9.local}"
SSH_OPTS="${SSH_OPTS:-"-o BatchMode=yes -o ConnectTimeout=10 -o ServerAliveInterval=0 -o StrictHostKeyChecking=accept-new -o UserKnownHostsFile=/private/tmp/ds4_spark_known_hosts"}"
remote_tag="${REMOTE_TAG:-"$(date -u +%Y%m%d-%H%M%S)-$$"}"
default_remote_dir="/tmp/ds4_cuda_probe_sm121_compile_report_tiny_minimal_${remote_tag}"
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
echo \"== build: sm_121 compile report tiny minimal (\${NVCC_FLAGS}) ==\"
rm -rf \"$REMOTE_DIR\"
mkdir -p \"$REMOTE_DIR\"

cat > \"$REMOTE_DIR\"/cuda_sm121_compile_report_tiny_minimal.cu <<'EOF'
#include <stdint.h>
#include <stdio.h>

#include <cuda_runtime.h>

#define STR1(x) #x
#define STR(x) STR1(x)

__device__ __constant__ uint32_t ds4_cuda_arch_const =
#if defined(__CUDA_ARCH__)
	(uint32_t)__CUDA_ARCH__;
#else
	0U;
#endif

static int32_t ck(cudaError_t err,int32_t code,const char *what)
{
	if ( err != cudaSuccess )
	{
		fprintf(stderr,\"%s: %s\\n\",what,cudaGetErrorString(err));
		return(code);
	}
	return(0);
}

static const char *macro_arch_list(void)
{
#if defined(__CUDA_ARCH_LIST__)
	return(STR(__CUDA_ARCH_LIST__));
#else
	return(\"(missing)\");
#endif
}

static const char *macro_arch_specific(void)
{
#if defined(__CUDA_ARCH_SPECIFIC__)
	return(STR(__CUDA_ARCH_SPECIFIC__));
#else
	return(\"(missing)\");
#endif
}

static const char *macro_arch_family_specific(void)
{
#if defined(__CUDA_ARCH_FAMILY_SPECIFIC__)
	return(STR(__CUDA_ARCH_FAMILY_SPECIFIC__));
#else
	return(\"(missing)\");
#endif
}

static void print_versions(void)
{
#if defined(__CUDACC_VER_MAJOR__) && defined(__CUDACC_VER_MINOR__) && defined(__CUDACC_VER_BUILD__)
	printf(\"nvcc_ver=%d.%d.%d \",__CUDACC_VER_MAJOR__,__CUDACC_VER_MINOR__,__CUDACC_VER_BUILD__);
#else
	printf(\"nvcc_ver=(missing) \");
#endif
#if defined(CUDART_VERSION)
	printf(\"cudart_ver=%d \",(int32_t)CUDART_VERSION);
#else
	printf(\"cudart_ver=(missing) \");
#endif
}

int main(int argc,char **argv)
{
	int32_t count = 0,driver_v = -1,runtime_v = -1;
	cudaDeviceProp prop;
	uint32_t cuda_arch = 0;
	(void)argc;
	(void)argv;
	(void)cudaDriverGetVersion(&driver_v);
	(void)cudaRuntimeGetVersion(&runtime_v);
	if ( cudaGetDeviceCount(&count) != cudaSuccess )
	{
		(void)cudaGetLastError();
		count = 0;
	}
	if ( count <= 0 )
	{
		print_versions();
		printf(\"cuda_drv=%d cuda_rt=%d count=%d __CUDA_ARCH__=%u __CUDA_ARCH_LIST__=%s __CUDA_ARCH_SPECIFIC__=%s __CUDA_ARCH_FAMILY_SPECIFIC__=%s\\n\",driver_v,runtime_v,count,cuda_arch,macro_arch_list(),macro_arch_specific(),macro_arch_family_specific());
		return(0);
	}
	if ( ck(cudaGetDeviceProperties(&prop,0),-1,\"cudaGetDeviceProperties(0)\") != 0 )
		return(-1);
	if ( cudaMemcpyFromSymbol(&cuda_arch,ds4_cuda_arch_const,sizeof(cuda_arch),0,cudaMemcpyDeviceToHost) != cudaSuccess )
	{
		(void)cudaGetLastError();
		cuda_arch = 0;
	}
	print_versions();
	printf(\"cuda_drv=%d cuda_rt=%d dev0=\\\"%s\\\" cc=%d.%d __CUDA_ARCH__=%u __CUDA_ARCH_LIST__=%s __CUDA_ARCH_SPECIFIC__=%s __CUDA_ARCH_FAMILY_SPECIFIC__=%s\\n\",driver_v,runtime_v,prop.name,prop.major,prop.minor,cuda_arch,macro_arch_list(),macro_arch_specific(),macro_arch_family_specific());
	return(0);
}
EOF

\$NVCC -O2 -std=c++17 \${NVCC_FLAGS} -o \"$REMOTE_DIR\"/cuda_sm121_compile_report_tiny_minimal \"$REMOTE_DIR\"/cuda_sm121_compile_report_tiny_minimal.cu

echo
echo \"== run: cuda_sm121_compile_report_tiny_minimal ==\"
\"$REMOTE_DIR\"/cuda_sm121_compile_report_tiny_minimal
"
}

if [ "$log_path" = "" ]; then
	main
	exit 0
fi

mkdir -p "$(dirname "$log_path")"
printf "== cuda_probe_sm121_compile_report_tiny_minimal_spark0 log: %s ==\n" "$(date -u +%Y-%m-%dT%H:%M:%SZ)" >> "$log_path"
tmp_out="$(mktemp "/private/tmp/ds4_cuda_probe_sm121_compile_report_tiny_minimal_out.XXXXXX")"
set +e
main >"$tmp_out" 2>&1
rc=$?
set -e
cat "$tmp_out"
cat "$tmp_out" >> "$log_path"
rm -f "$tmp_out"
exit $rc

