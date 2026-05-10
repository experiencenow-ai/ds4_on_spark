#!/usr/bin/env sh
set -eu

target="${1:-spark0@aitopatom-9ab9.local}"
SSH_OPTS="${SSH_OPTS:--o BatchMode=yes -o ConnectTimeout=10 -o StrictHostKeyChecking=accept-new -o UserKnownHostsFile=/private/tmp/ds4_spark_known_hosts}"
REMOTE_DIR="${REMOTE_DIR:-/tmp/ds4_cuda_probe_nvcc_minimal}"

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
echo \"== nvcc: --list-gpu-arch (if supported) ==\"
list_gpu_arch=\$(\$NVCC --list-gpu-arch 2>/dev/null || true)
if [ \"\${list_gpu_arch}\" = \"\" ]; then
	echo \"(nvcc --list-gpu-arch not supported)\"
else
	printf \"%s\n\" \"\${list_gpu_arch}\"
	if echo \"\${list_gpu_arch}\" | grep -q \"compute_121\"; then
		:
	else
		echo \"(nvcc --list-gpu-arch missing compute_121)\" >&2
		exit 4
	fi
fi
echo
echo \"== nvcc: --list-gpu-code (if supported) ==\"
list_gpu_code=\$(\$NVCC --list-gpu-code 2>/dev/null || true)
if [ \"\${list_gpu_code}\" = \"\" ]; then
	echo \"(nvcc --list-gpu-code not supported)\"
else
	printf \"%s\n\" \"\${list_gpu_code}\"
	if echo \"\${list_gpu_code}\" | grep -q \"sm_121\"; then
		:
	else
		echo \"(nvcc --list-gpu-code missing sm_121)\" >&2
		exit 5
	fi
fi

echo
echo \"== nvcc: compile-only probes (best-effort) ==\"
rm -rf \"$REMOTE_DIR\"
mkdir -p \"$REMOTE_DIR\"
cat > \"$REMOTE_DIR\"/cuda_nvcc_compile_only.cu <<'EOF'
#include <stdint.h>

#if defined(__CUDA_ARCH__)
#if (__CUDA_ARCH__ != 1210)
#error nvcc_compile_only_expected___CUDA_ARCH___1210
#endif
#endif

__global__ void cuda_compile_only(uint32_t *out)
{
#if defined(__CUDA_ARCH__)
	if ( out != 0 )
		out[0] = (uint32_t)__CUDA_ARCH__;
#else
	(void)out;
#endif
}
EOF

try_compile_only() {
	tag=\"\$1\"
	arch=\"\$2\"
	echo \"-- compile-only: \${tag} (-arch=\${arch})\"
	err_path=\"$REMOTE_DIR\"/\"\${tag}\".err
	set +e
	\$NVCC -O2 -std=c++17 -arch=\"\${arch}\" -c -o \"$REMOTE_DIR\"/\"\${tag}\".o \"$REMOTE_DIR\"/cuda_nvcc_compile_only.cu >\"$REMOTE_DIR\"/\"\${tag}\".out 2>\"\${err_path}\"
	rc=\$?
	set -e
	if [ \$rc -eq 0 ]; then
		echo \"\${tag}: OK\"
	else
		echo \"\${tag}: FAILED rc=\${rc}\"
		head -n 40 \"\${err_path}\" || true
	fi
}

try_gencode_only() {
	tag=\"\$1\"
	gencode_arch=\"\$2\"
	gencode_code=\"\$3\"
	echo \"-- compile-only: \${tag} (-gencode arch=\${gencode_arch},code=\${gencode_code})\"
	err_path=\"$REMOTE_DIR\"/\"\${tag}\".err
	set +e
	\$NVCC -O2 -std=c++17 -gencode \"arch=\${gencode_arch},code=\${gencode_code}\" -c -o \"$REMOTE_DIR\"/\"\${tag}\".o \"$REMOTE_DIR\"/cuda_nvcc_compile_only.cu >\"$REMOTE_DIR\"/\"\${tag}\".out 2>\"\${err_path}\"
	rc=\$?
	set -e
	if [ \$rc -eq 0 ]; then
		echo \"\${tag}: OK\"
	else
		echo \"\${tag}: FAILED rc=\${rc}\"
		head -n 40 \"\${err_path}\" || true
	fi
}

try_compile_only arch_sm_121 sm_121
if [ \"\${list_gpu_arch}\" != \"\" ] && echo \"\${list_gpu_arch}\" | grep -q \"compute_121\"; then
	try_compile_only arch_compute_121 compute_121
	try_gencode_only gencode_sm_121 compute_121 sm_121
	try_gencode_only gencode_compute_121 compute_121 compute_121
fi
if [ \"\${list_gpu_code}\" != \"\" ] && echo \"\${list_gpu_code}\" | grep -q \"sm_121a\"; then
	try_compile_only variant_sm_121a sm_121a
fi
if [ \"\${list_gpu_code}\" != \"\" ] && echo \"\${list_gpu_code}\" | grep -q \"sm_121f\"; then
	try_compile_only variant_sm_121f sm_121f
fi

echo
echo \"== nvcc: minimal compile/run (sm_121 + native) ==\"
rm -rf \"$REMOTE_DIR\"
mkdir -p \"$REMOTE_DIR\"
cat > \"$REMOTE_DIR\"/cuda_nvcc_minimal.cu <<'EOF'
#include <stdint.h>
#include <inttypes.h>
#include <stdio.h>

#include <cuda_runtime.h>

#if defined(__CUDA_ARCH__)
#if (__CUDA_ARCH__ != 1210)
#error nvcc_minimal_probe_expected___CUDA_ARCH___1210
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

static int32_t get_attr_i32(int32_t *out,int32_t dev,cudaDeviceAttr attr)
{
	int32_t v = 0;
	cudaError_t err;
	if ( out == 0 )
		return(-1001);
	err = cudaDeviceGetAttribute(&v,attr,dev);
	if ( err != cudaSuccess )
		return(-1002);
	*out = v;
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
	int32_t count = 0,driver_v = 0,runtime_v = 0,rc = 0,clock_khz = 0,mem_clock_khz = 0;
	int32_t smem_optin = 0,l2_bytes = 0,max_threads_sm = 0,regs_sm = 0;
	int32_t max_threads_block = 0,max_blocks_sm = 0,smem_sm = 0,regs_block = 0,smem_block_max = 0;
	cudaDeviceProp prop;
	uint32_t out = 0;
	uint32_t *dout = 0;
	uint64_t mem_bytes = 0,smem_block_bytes = 0;
	(void)argc;
	(void)argv;

	(void)cudaDriverGetVersion(&driver_v);
	(void)cudaRuntimeGetVersion(&runtime_v);
	rc = ck(cudaGetDeviceCount(&count),-1,\"cudaGetDeviceCount\");
	if ( rc != 0 )
		return(rc);
	if ( count <= 0 )
	{
		printf(\"cuda drv=%d rt=%d count=%d\\n\",driver_v,runtime_v,count);
		return(0);
	}
	rc = ck(cudaGetDeviceProperties(&prop,0),-3,\"cudaGetDeviceProperties(0)\");
	if ( rc != 0 )
		return(rc);
	(void)get_attr_i32(&clock_khz,0,cudaDevAttrClockRate);
	(void)get_attr_i32(&mem_clock_khz,0,cudaDevAttrMemoryClockRate);
	(void)get_attr_i32(&smem_optin,0,cudaDevAttrMaxSharedMemoryPerBlockOptin);
	(void)get_attr_i32(&l2_bytes,0,cudaDevAttrL2CacheSize);
	(void)get_attr_i32(&max_threads_sm,0,cudaDevAttrMaxThreadsPerMultiProcessor);
	(void)get_attr_i32(&regs_sm,0,cudaDevAttrMaxRegistersPerMultiprocessor);
	(void)get_attr_i32(&max_threads_block,0,cudaDevAttrMaxThreadsPerBlock);
	(void)get_attr_i32(&max_blocks_sm,0,cudaDevAttrMaxBlocksPerMultiprocessor);
	(void)get_attr_i32(&smem_sm,0,cudaDevAttrMaxSharedMemoryPerMultiprocessor);
	(void)get_attr_i32(&regs_block,0,cudaDevAttrMaxRegistersPerBlock);
	(void)get_attr_i32(&smem_block_max,0,cudaDevAttrMaxSharedMemoryPerBlock);
	mem_bytes = (uint64_t)prop.totalGlobalMem;
	smem_block_bytes = (uint64_t)prop.sharedMemPerBlock;
	printf(\"cuda drv=%d rt=%d count=%d dev0=\\\"%s\\\" cc=%d.%d mp=%d warp=%d clock_khz=%d mem_clock_khz=%d mem=%\" PRIu64 \" smem_block=%\" PRIu64 \" smem_block_max=%d smem_optin=%d smem_sm=%d l2=%d maxthr_block=%d maxthr_sm=%d maxblocks_sm=%d regs_block=%d regs_sm=%d\\n\",driver_v,runtime_v,count,prop.name,prop.major,prop.minor,prop.multiProcessorCount,prop.warpSize,clock_khz,mem_clock_khz,mem_bytes,smem_block_bytes,smem_block_max,smem_optin,smem_sm,l2_bytes,max_threads_block,max_threads_sm,max_blocks_sm,regs_block,regs_sm);

	rc = ck(cudaMalloc((void **)&dout,sizeof(out)),-4,\"cudaMalloc\");
	if ( rc != 0 )
		return(rc);
	cuda_arch_probe<<<1,1>>>(dout);
	rc = ck(cudaGetLastError(),-5,\"kernel launch\");
	if ( rc != 0 )
		return(rc);
	rc = ck(cudaMemcpy(&out,dout,sizeof(out),cudaMemcpyDeviceToHost),-6,\"cudaMemcpy\");
	if ( rc != 0 )
		return(rc);
	printf(\"__CUDA_ARCH__=%u\\n\",out);
	(void)cudaFree(dout);
	return(0);
}
EOF

echo \"-- build: -arch=sm_121\"
\$NVCC -O2 -std=c++17 -arch=sm_121 -o \"$REMOTE_DIR\"/nvcc_sm121_minimal \"$REMOTE_DIR\"/cuda_nvcc_minimal.cu
echo \"-- run: nvcc_sm121_minimal\"
\"$REMOTE_DIR\"/nvcc_sm121_minimal
echo
echo \"-- build: -arch=native\"
\$NVCC -O2 -std=c++17 -arch=native -o \"$REMOTE_DIR\"/nvcc_native_minimal \"$REMOTE_DIR\"/cuda_nvcc_minimal.cu
echo \"-- run: nvcc_native_minimal\"
\"$REMOTE_DIR\"/nvcc_native_minimal

echo
echo \"== cuobjdump: embedded PTX (best-effort) ==\"
CUOBJDUMP=\"\"
if [ -x /usr/local/cuda/bin/cuobjdump ]; then
	CUOBJDUMP=\"/usr/local/cuda/bin/cuobjdump\"
elif command -v cuobjdump >/dev/null 2>&1; then
	CUOBJDUMP=\"cuobjdump\"
fi
if [ \"\${CUOBJDUMP}\" = \"\" ]; then
	echo \"(cuobjdump not found; skipping)\"
else
	check_ptx() {
		name=\"\$1\"
		path=\"\$2\"
		if \$CUOBJDUMP --dump-ptx \"\${path}\" 2>/dev/null | grep -q \"^\\\\.target\"; then
			echo \"ptx_embed(\${name}): PRESENT\"
		else
			echo \"ptx_embed(\${name}): MISSING\"
		fi
	}
	check_ptx sm_121 \"$REMOTE_DIR\"/nvcc_sm121_minimal
	check_ptx native \"$REMOTE_DIR\"/nvcc_native_minimal
fi
"
