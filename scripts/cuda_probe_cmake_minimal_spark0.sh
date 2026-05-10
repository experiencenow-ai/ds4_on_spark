#!/usr/bin/env sh
set -eu

target="${1:-spark0@aitopatom-9ab9.local}"
SSH_OPTS="${SSH_OPTS:-"-o BatchMode=yes -o ConnectTimeout=10 -o StrictHostKeyChecking=accept-new -o UserKnownHostsFile=/private/tmp/ds4_spark_known_hosts"}"
REMOTE_DIR="${REMOTE_DIR:-/tmp/ds4_cuda_probe_cmake_minimal}"

ssh $SSH_OPTS "$target" "set -eu
CMAKE=\"\"
echo \"== cmake ==\"
if command -v cmake >/dev/null 2>&1; then
	CMAKE=\"cmake\"
else
	echo \"cmake not found\" >&2
	exit 3
fi
\$CMAKE --version | head -n 1

ver=\$(\$CMAKE --version | head -n 1 | awk '{print \$3}')
major=\$(printf \"%s\" \"\$ver\" | cut -d. -f1)
minor=\$(printf \"%s\" \"\$ver\" | cut -d. -f2)
if [ \"\$major\" -lt 3 ] || { [ \"\$major\" -eq 3 ] && [ \"\$minor\" -lt 18 ]; }; then
	echo \"cmake too old (\$ver); need >= 3.18 for CMAKE_CUDA_ARCHITECTURES\" >&2
	exit 4
fi

NVCC=\"\"
echo
echo \"== nvcc ==\"
if [ -x /usr/local/cuda/bin/nvcc ]; then
	NVCC=\"/usr/local/cuda/bin/nvcc\"
elif command -v nvcc >/dev/null 2>&1; then
	NVCC=\"nvcc\"
else
	echo \"nvcc not found\" >&2
	exit 5
fi
\$NVCC --version

echo
echo \"== cmake: minimal configure/build/run (CMAKE_CUDA_ARCHITECTURES=121) ==\"
rm -rf \"$REMOTE_DIR\"
mkdir -p \"$REMOTE_DIR\"
cat > \"$REMOTE_DIR\"/CMakeLists.txt <<'EOF'
cmake_minimum_required(VERSION 3.18)
project(ds4_cuda_probe_cmake_minimal LANGUAGES CUDA CXX)

set(CMAKE_CUDA_STANDARD 17)
set(CMAKE_CUDA_STANDARD_REQUIRED ON)
set(CMAKE_CXX_STANDARD 17)
set(CMAKE_CXX_STANDARD_REQUIRED ON)

add_executable(ds4_cuda_probe_cmake_sm121 main.cu)
set_property(TARGET ds4_cuda_probe_cmake_sm121 PROPERTY CUDA_ARCHITECTURES 121)
EOF

cat > \"$REMOTE_DIR\"/main.cu <<'EOF'
#include <stdint.h>
#include <stdio.h>

#include <cuda_runtime.h>

#if defined(__CUDA_ARCH__)
#if (__CUDA_ARCH__ != 1210)
#error cmake_cuda_sm121_probe_expected___CUDA_ARCH___1210
#endif
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

__global__ void cuda_arch_probe(uint32_t *out)
{
#if defined(__CUDA_ARCH__)
	out[0] = (uint32_t)__CUDA_ARCH__;
#else
	out[0] = 0;
#endif
}

int main(int argc,char **argv)
{
	int32_t rc = 0;
	uint32_t out = 0;
	uint32_t *dout = 0;
	(void)argc;
	(void)argv;
	rc = ck(cudaMalloc((void **)&dout,sizeof(out)),-1,\"cudaMalloc\");
	if ( rc != 0 )
		return(rc);
	cuda_arch_probe<<<1,1>>>(dout);
	rc = ck(cudaGetLastError(),-2,\"kernel launch\");
	if ( rc != 0 )
		return(rc);
	rc = ck(cudaMemcpy(&out,dout,sizeof(out),cudaMemcpyDeviceToHost),-3,\"cudaMemcpy\");
	if ( rc != 0 )
		return(rc);
	printf(\"__CUDA_ARCH__=%u\\n\",out);
	(void)cudaFree(dout);
	return(0);
}
EOF

\$CMAKE -S \"$REMOTE_DIR\" -B \"$REMOTE_DIR\"/build -DCMAKE_BUILD_TYPE=Release -DCMAKE_CUDA_COMPILER=\"\$NVCC\" -DCMAKE_CUDA_ARCHITECTURES=\"121\"
\$CMAKE --build \"$REMOTE_DIR\"/build
\"$REMOTE_DIR\"/build/ds4_cuda_probe_cmake_sm121
" 
