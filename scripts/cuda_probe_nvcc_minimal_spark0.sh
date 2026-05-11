#!/usr/bin/env sh
set -eu

target="${1:-spark0@aitopatom-9ab9.local}"
SSH_OPTS="${SSH_OPTS:-"-o BatchMode=yes -o ConnectTimeout=10 -o StrictHostKeyChecking=accept-new -o UserKnownHostsFile=/private/tmp/ds4_spark_known_hosts"}"
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
NVCC_PATH=\"\$NVCC\"
if [ \"\$NVCC\" = \"nvcc\" ]; then
	NVCC_PATH=\"\$(command -v nvcc)\"
fi
CUDA_BIN_DIR=\"\$(dirname \"\$NVCC_PATH\")\"
PTXAS=\"\$CUDA_BIN_DIR/ptxas\"
NVLINK=\"\$CUDA_BIN_DIR/nvlink\"
\$NVCC --version
echo
echo \"== ptxas / nvlink (best-effort) ==\"
if [ -x \"\$PTXAS\" ]; then
	\"\$PTXAS\" --version 2>&1 || true
else
	echo \"(ptxas not found)\"
fi
if [ -x \"\$NVLINK\" ]; then
	\"\$NVLINK\" --version 2>&1 || true
else
	echo \"(nvlink not found)\"
fi
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

cat > \"$REMOTE_DIR\"/cuda_nvcc_compile_only_cxx20_flags.cu <<'EOF'
#include <stdint.h>

#if defined(__CUDA_ARCH__)
#if (__CUDA_ARCH__ != 1210)
#error nvcc_compile_only_cxx20_flags_expected___CUDA_ARCH___1210
#endif
#endif

template <typename T>
__host__ __device__ constexpr T add_constexpr(T a,T b)
{
	return((T)(a + b));
}

__global__ void cuda_compile_only_cxx20_flags(uint32_t *out)
{
#if defined(__CUDA_ARCH__)
	auto lam = [] __host__ __device__ (uint32_t v) { return((uint32_t)(v + 1U)); };
	constexpr uint32_t k = add_constexpr<uint32_t>(7U,9U);
	if ( out != 0 )
		out[0] = (uint32_t)(lam((uint32_t)__CUDA_ARCH__) + k);
#else
	(void)out;
#endif
}
EOF

cat > \"$REMOTE_DIR\"/cuda_nvcc_compile_only_featureset_macros.cu <<'EOF'
#include <stdint.h>

#if defined(__CUDA_ARCH__)
#if (__CUDA_ARCH__ != 1210)
#error nvcc_featureset_macros_expected___CUDA_ARCH___1210
#endif

#if defined(EXPECT_SPECIFIC)
#if !defined(__CUDA_ARCH_SPECIFIC__)
#error nvcc_featureset_macros_expected___CUDA_ARCH_SPECIFIC___defined
#endif
#if (__CUDA_ARCH_SPECIFIC__ != 1210)
#error nvcc_featureset_macros_expected___CUDA_ARCH_SPECIFIC___1210
#endif
#else
#if defined(__CUDA_ARCH_SPECIFIC__)
#error nvcc_featureset_macros_unexpected___CUDA_ARCH_SPECIFIC___defined
#endif
#endif

#if defined(EXPECT_FAMILY)
#if !defined(__CUDA_ARCH_FAMILY_SPECIFIC__)
#error nvcc_featureset_macros_expected___CUDA_ARCH_FAMILY_SPECIFIC___defined
#endif
#if (__CUDA_ARCH_FAMILY_SPECIFIC__ != 1210)
#error nvcc_featureset_macros_expected___CUDA_ARCH_FAMILY_SPECIFIC___1210
#endif
#else
#if defined(__CUDA_ARCH_FAMILY_SPECIFIC__)
#error nvcc_featureset_macros_unexpected___CUDA_ARCH_FAMILY_SPECIFIC___defined
#endif
#endif
#endif

__global__ void cuda_featureset_macros_compile_only(uint32_t *out)
{
	(void)out;
}
EOF

cat > \"$REMOTE_DIR\"/cuda_nvcc_arch_list_probe.cu <<'EOF'
#define STR1(x) #x
#define STR(x) STR1(x)

#if defined(__CUDA_ARCH_LIST__)
#pragma message(\"CUDA_ARCH_LIST=\" STR(__CUDA_ARCH_LIST__))
#else
#pragma message(\"CUDA_ARCH_LIST=(missing)\")
#endif

int cuda_arch_list_probe_dummy(void)
{
	return(0);
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

	try_compile_only_gpuarch() {
		tag=\"\$1\"
		arch=\"\$2\"
		echo \"-- compile-only: \${tag} (--gpu-architecture=\${arch})\"
		err_path=\"$REMOTE_DIR\"/\"\${tag}\".err
		set +e
		\$NVCC -O2 -std=c++17 --gpu-architecture=\"\${arch}\" -c -o \"$REMOTE_DIR\"/\"\${tag}\".o \"$REMOTE_DIR\"/cuda_nvcc_compile_only.cu >\"$REMOTE_DIR\"/\"\${tag}\".out 2>\"\${err_path}\"
		rc=\$?
		set -e
		if [ \$rc -eq 0 ]; then
			echo \"\${tag}: OK\"
		else
			echo \"\${tag}: FAILED rc=\${rc}\"
			head -n 40 \"\${err_path}\" || true
		fi
	}

	try_compile_only_cxx20_flags() {
		tag=\"\$1\"
		arch=\"\$2\"
		echo \"-- compile-only: \${tag} (-arch=\${arch} -std=c++20 --extended-lambda --expt-relaxed-constexpr)\"
		err_path=\"$REMOTE_DIR\"/\"\${tag}\".err
		set +e
		\$NVCC -O2 -std=c++20 --extended-lambda --expt-relaxed-constexpr -arch=\"\${arch}\" -c -o \"$REMOTE_DIR\"/\"\${tag}\".o \"$REMOTE_DIR\"/cuda_nvcc_compile_only_cxx20_flags.cu >\"$REMOTE_DIR\"/\"\${tag}\".out 2>\"\${err_path}\"
		rc=\$?
		set -e
		if [ \$rc -eq 0 ]; then
			echo \"\${tag}: OK\"
		else
			echo \"\${tag}: FAILED rc=\${rc}\"
			head -n 40 \"\${err_path}\" || true
		fi
	}

	try_compile_only_featureset_macros() {
		tag=\"\$1\"
		arch=\"\$2\"
		defs=\"\$3\"
		echo \"-- compile-only: \${tag} (-arch=\${arch})\"
		err_path=\"$REMOTE_DIR\"/\"\${tag}\".err
		set +e
		\$NVCC -O2 -std=c++17 \${defs} -arch=\"\${arch}\" -c -o \"$REMOTE_DIR\"/\"\${tag}\".o \"$REMOTE_DIR\"/cuda_nvcc_compile_only_featureset_macros.cu >\"$REMOTE_DIR\"/\"\${tag}\".out 2>\"\${err_path}\"
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
	try_compile_only_gpuarch gpuarch_sm_121 sm_121
	try_compile_only_cxx20_flags arch_sm_121_cxx20_flags sm_121
	try_compile_only variant_sm_121a sm_121a
	try_compile_only variant_sm_121f sm_121f
	try_compile_only_featureset_macros featureset_compute_121a compute_121a \"-DEXPECT_SPECIFIC=1 -DEXPECT_FAMILY=1\"
	try_compile_only_featureset_macros featureset_compute_121f compute_121f \"-DEXPECT_FAMILY=1\"
	echo
	echo \"== nvcc: __CUDA_ARCH_LIST__ probe (best-effort) ==\"
	try_arch_list() {
		tag=\"\$1\"
		arch=\"\$2\"
		err_path=\"$REMOTE_DIR\"/\"\${tag}\".err
		echo \"-- compile-only: \${tag} (-arch=\${arch})\"
		set +e
		\$NVCC -O2 -std=c++17 -arch=\"\${arch}\" -c -o \"$REMOTE_DIR\"/\"\${tag}\".o \"$REMOTE_DIR\"/cuda_nvcc_arch_list_probe.cu >\"$REMOTE_DIR\"/\"\${tag}\".out 2>\"\${err_path}\"
		rc=\$?
		set -e
		if [ \$rc -eq 0 ]; then
			arch_list=\$(grep -E \"CUDA_ARCH_LIST=\" \"\${err_path}\" | head -n 1 | sed -E 's/^.*CUDA_ARCH_LIST=//' | tr -cd '0-9,')
			if [ \"\${arch_list}\" = \"\" ]; then
				arch_list=\"(missing)\"
			fi
			echo \"\${tag}: OK __CUDA_ARCH_LIST__=\${arch_list}\"
		else
			echo \"\${tag}: FAILED rc=\${rc}\"
			head -n 40 \"\${err_path}\" || true
		fi
	}

	try_arch_list arch_list_sm_121 sm_121
	try_arch_list arch_list_sm_121a sm_121a
	try_arch_list arch_list_sm_121f sm_121f
	echo
	echo \"== nvcc: ptxas -v (sm_121 compile-only, best-effort) ==\"
	if [ -x \"\$PTXAS\" ]; then
		set +e
		\$NVCC -O2 -std=c++17 -arch=sm_121 -Xptxas=-v -c -o \"$REMOTE_DIR\"/ptxas_verbose_sm_121.o \"$REMOTE_DIR\"/cuda_nvcc_compile_only.cu >\"$REMOTE_DIR\"/ptxas_verbose_sm_121.out 2>\"$REMOTE_DIR\"/ptxas_verbose_sm_121.err
		rc=\$?
		set -e
		if [ \$rc -eq 0 ]; then
			grep -E \"ptxas info\" \"$REMOTE_DIR\"/ptxas_verbose_sm_121.err | head -n 20 || true
		else
			echo \"ptxas_verbose_sm_121: FAILED rc=\${rc}\"
			head -n 60 \"$REMOTE_DIR\"/ptxas_verbose_sm_121.err || true
		fi
	else
		echo \"(ptxas not found; skipping)\"
	fi
	if [ \"\${list_gpu_arch}\" != \"\" ] && echo \"\${list_gpu_arch}\" | grep -q \"compute_121\"; then
		try_compile_only arch_compute_121 compute_121
		try_compile_only_cxx20_flags arch_compute_121_cxx20_flags compute_121
		try_compile_only arch_compute_121a compute_121a
		try_compile_only arch_compute_121f compute_121f
		try_gencode_only gencode_sm_121 compute_121 sm_121
		try_gencode_only gencode_compute_121 compute_121 compute_121
	fi

echo
echo \"== nvcc: __cluster_dims__ attribute compile (best-effort) ==\"
cat > \"$REMOTE_DIR\"/cuda_cluster_dims_attr_compile.cu <<'EOF'
#include <stdint.h>

#include <cuda_runtime.h>

__global__ void __cluster_dims__(2,1,1) cluster_dims_attr_probe(uint32_t *out)
{
	if ( ((int32_t)threadIdx.x) == 0 )
		out[(int32_t)blockIdx.x] = 0;
}
EOF
set +e
\$NVCC -O2 -std=c++17 -arch=sm_121 -c -o \"$REMOTE_DIR\"/cluster_dims_attr_compile.o \"$REMOTE_DIR\"/cuda_cluster_dims_attr_compile.cu >\"$REMOTE_DIR\"/cluster_dims_attr_compile.out 2>\"$REMOTE_DIR\"/cluster_dims_attr_compile.err
rc=\$?
set -e
if [ \$rc -eq 0 ]; then
	echo \"cluster_dims_attr_compile: OK\"
else
	echo \"cluster_dims_attr_compile: FAILED rc=\$rc\"
	head -n 40 \"$REMOTE_DIR\"/cluster_dims_attr_compile.err || true
fi

echo
echo \"== nvcc: -gencode PTX embed behavior (best-effort) ==\"
CUOBJDUMP=\"\"
if [ -x /usr/local/cuda/bin/cuobjdump ]; then
	CUOBJDUMP=\"/usr/local/cuda/bin/cuobjdump\"
elif command -v cuobjdump >/dev/null 2>&1; then
	CUOBJDUMP=\"cuobjdump\"
fi
if [ \"\${CUOBJDUMP}\" = \"\" ]; then
	echo \"(cuobjdump not found; skipping)\"
elif [ \"\${list_gpu_arch}\" = \"\" ]; then
	echo \"(nvcc --list-gpu-arch not supported; skipping)\"
elif echo \"\${list_gpu_arch}\" | grep -q \"compute_121\"; then
	set +e
	\$NVCC -O2 -std=c++17 -gencode \"arch=compute_121,code=sm_121\" -fatbin -o \"$REMOTE_DIR\"/cuda_gencode_sm_121_only.fatbin \"$REMOTE_DIR\"/cuda_nvcc_compile_only.cu 2>\"$REMOTE_DIR\"/cuda_gencode_sm_121_only.err
	rc=\$?
	set -e
	if [ \$rc -ne 0 ]; then
		echo \"(nvcc -fatbin -gencode code=sm_121 failed rc=\$rc)\" >&2
		head -n 40 \"$REMOTE_DIR\"/cuda_gencode_sm_121_only.err || true
	else
		if \$CUOBJDUMP --dump-ptx \"$REMOTE_DIR\"/cuda_gencode_sm_121_only.fatbin 2>/dev/null | grep -q \"^\\\\.target\"; then
			echo \"ptx_embed_gencode_sm_only: PRESENT (unexpected)\"
		else
			echo \"ptx_embed_gencode_sm_only: MISSING (expected)\"
		fi
	fi

	set +e
	\$NVCC -O2 -std=c++17 -gencode \"arch=compute_121,code=compute_121\" -fatbin -o \"$REMOTE_DIR\"/cuda_gencode_compute_121_only.fatbin \"$REMOTE_DIR\"/cuda_nvcc_compile_only.cu 2>\"$REMOTE_DIR\"/cuda_gencode_compute_121_only.err
	rc=\$?
	set -e
	if [ \$rc -ne 0 ]; then
		echo \"(nvcc -fatbin -gencode code=compute_121 failed rc=\$rc)\" >&2
		head -n 40 \"$REMOTE_DIR\"/cuda_gencode_compute_121_only.err || true
	else
		if \$CUOBJDUMP --dump-ptx \"$REMOTE_DIR\"/cuda_gencode_compute_121_only.fatbin 2>/dev/null | grep -q \"^\\\\.target\"; then
			echo \"ptx_embed_gencode_ptx_only: PRESENT (expected)\"
		else
			echo \"ptx_embed_gencode_ptx_only: MISSING\" >&2
		fi
	fi

	set +e
	\$NVCC -O2 -std=c++17 -gencode \"arch=compute_121,code=sm_121\" -gencode \"arch=compute_121,code=compute_121\" -fatbin -o \"$REMOTE_DIR\"/cuda_gencode_sm_plus_ptx.fatbin \"$REMOTE_DIR\"/cuda_nvcc_compile_only.cu 2>\"$REMOTE_DIR\"/cuda_gencode_sm_plus_ptx.err
	rc=\$?
	set -e
	if [ \$rc -ne 0 ]; then
		echo \"(nvcc -fatbin -gencode sm_121+compute_121 failed rc=\$rc)\" >&2
		head -n 40 \"$REMOTE_DIR\"/cuda_gencode_sm_plus_ptx.err || true
	else
		if \$CUOBJDUMP --dump-ptx \"$REMOTE_DIR\"/cuda_gencode_sm_plus_ptx.fatbin 2>/dev/null | grep -q \"^\\\\.target\"; then
			echo \"ptx_embed_gencode_sm_plus_ptx: PRESENT (expected)\"
		else
			echo \"ptx_embed_gencode_sm_plus_ptx: MISSING\" >&2
		fi
	fi
else
	echo \"(nvcc --list-gpu-arch missing compute_121; skipping)\"
fi

echo
echo \"== nvcc: minimal compile/run (sm_121 + --gpu-architecture=sm_121 + native + compute_121/variants best-effort) ==\"
rm -rf \"$REMOTE_DIR\"
mkdir -p \"$REMOTE_DIR\"
cat > \"$REMOTE_DIR\"/cuda_nvcc_minimal.cu <<'EOF'
#include <stdint.h>
#include <inttypes.h>
#include <stdio.h>

#include <cuda_runtime.h>
#include <cuda.h>

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
	int32_t v = -1;
	cudaError_t err;
	if ( out == 0 )
		return(-1001);
	err = cudaDeviceGetAttribute(&v,attr,dev);
	if ( err != cudaSuccess )
	{
		*out = -1;
		return(-1002);
	}
	*out = v;
	return(0);
}

static int32_t get_cu_attr_i32(int32_t *out,int32_t dev,CUdevice_attribute attr)
{
	CUdevice cu_dev;
	int32_t v = -1;
	CUresult err;
	if ( out == 0 )
		return(-1011);
	*out = -1;
	err = cuInit(0);
	if ( err != CUDA_SUCCESS )
		return(-1012);
	err = cuDeviceGet(&cu_dev,dev);
	if ( err != CUDA_SUCCESS )
		return(-1013);
	err = cuDeviceGetAttribute(&v,attr,cu_dev);
	if ( err != CUDA_SUCCESS )
	{
		*out = -1;
		return(-1014);
	}
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
	int32_t count = 0,driver_v = -1,runtime_v = -1,rc = 0,clock_khz = -1,mem_clock_khz = -1;
	int32_t smem_optin = -1,l2_bytes = -1,max_threads_sm = -1,regs_sm = -1;
	int32_t max_threads_block = -1,max_blocks_sm = -1,smem_sm = -1,regs_block = -1,smem_block_max = -1;
	int32_t coop_launch = -1,cluster_launch = -1;
	int32_t smem_reserved_block = -1,mem_pools = -1;
	int32_t tma_map = -1;
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
		printf(\"cuda drv=%d rt=%d count=%d tma_map=%d schema=2\\n\",driver_v,runtime_v,count,tma_map);
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
	(void)get_attr_i32(&coop_launch,0,cudaDevAttrCooperativeLaunch);
	(void)get_attr_i32(&cluster_launch,0,cudaDevAttrClusterLaunch);
	(void)get_attr_i32(&smem_reserved_block,0,cudaDevAttrReservedSharedMemoryPerBlock);
	(void)get_attr_i32(&mem_pools,0,cudaDevAttrMemoryPoolsSupported);
	(void)get_cu_attr_i32(&tma_map,0,CU_DEVICE_ATTRIBUTE_TENSOR_MAP_ACCESS_SUPPORTED);
	mem_bytes = (uint64_t)prop.totalGlobalMem;
	smem_block_bytes = (uint64_t)prop.sharedMemPerBlock;
	printf(\"cuda drv=%d rt=%d count=%d dev0=\\\"%s\\\" cc=%d.%d mp=%d warp=%d clock_khz=%d mem_clock_khz=%d mem=%\" PRIu64 \" smem_block=%\" PRIu64 \" smem_block_max=%d smem_optin=%d smem_sm=%d smem_reserved_block=%d l2=%d maxthr_block=%d maxthr_sm=%d maxblocks_sm=%d regs_block=%d regs_sm=%d mem_pools=%d coop_launch=%d cluster_launch=%d tma_map=%d schema=2\\n\",driver_v,runtime_v,count,prop.name,prop.major,prop.minor,prop.multiProcessorCount,prop.warpSize,clock_khz,mem_clock_khz,mem_bytes,smem_block_bytes,smem_block_max,smem_optin,smem_sm,smem_reserved_block,l2_bytes,max_threads_block,max_threads_sm,max_blocks_sm,regs_block,regs_sm,mem_pools,coop_launch,cluster_launch,tma_map);

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
\$NVCC -O2 -std=c++17 -arch=sm_121 -o \"$REMOTE_DIR\"/nvcc_sm121_minimal \"$REMOTE_DIR\"/cuda_nvcc_minimal.cu -lcuda
echo \"-- run: nvcc_sm121_minimal\"
\"$REMOTE_DIR\"/nvcc_sm121_minimal
echo
echo \"-- build: --gpu-architecture=sm_121\"
\$NVCC -O2 -std=c++17 --gpu-architecture=sm_121 -o \"$REMOTE_DIR\"/nvcc_gpuarch_sm121_minimal \"$REMOTE_DIR\"/cuda_nvcc_minimal.cu -lcuda
echo \"-- run: nvcc_gpuarch_sm121_minimal\"
\"$REMOTE_DIR\"/nvcc_gpuarch_sm121_minimal
echo
echo \"-- build: -arch=native\"
\$NVCC -O2 -std=c++17 -arch=native -o \"$REMOTE_DIR\"/nvcc_native_minimal \"$REMOTE_DIR\"/cuda_nvcc_minimal.cu -lcuda
echo \"-- run: nvcc_native_minimal\"
\"$REMOTE_DIR\"/nvcc_native_minimal

if [ \"\${list_gpu_arch}\" != \"\" ] && echo \"\${list_gpu_arch}\" | grep -q \"compute_121\"; then
	echo
	echo \"-- build: -arch=compute_121 (PTX; JIT at runtime)\"
	\$NVCC -O2 -std=c++17 -arch=compute_121 -o \"$REMOTE_DIR\"/nvcc_compute121_minimal \"$REMOTE_DIR\"/cuda_nvcc_minimal.cu -lcuda
	echo \"-- run: nvcc_compute121_minimal\"
	\"$REMOTE_DIR\"/nvcc_compute121_minimal
fi

try_gencode_build_run() {
	tag=\"\$1\"
	gencode=\"\$2\"
	echo
	echo \"-- build+run (best-effort): \${tag} (-gencode \${gencode})\"
	set +e
	\$NVCC -O2 -std=c++17 -gencode \"\${gencode}\" -o \"$REMOTE_DIR\"/\"nvcc_\${tag}_minimal\" \"$REMOTE_DIR\"/cuda_nvcc_minimal.cu -lcuda >\"$REMOTE_DIR\"/\"nvcc_\${tag}_minimal.out\" 2>\"$REMOTE_DIR\"/\"nvcc_\${tag}_minimal.err\"
	rc=\$?
	if [ \$rc -ne 0 ]; then
		echo \"\${tag}: build FAILED rc=\${rc}\"
		head -n 60 \"$REMOTE_DIR\"/\"nvcc_\${tag}_minimal.err\" || true
		set -e
		return 0
	fi
	\"$REMOTE_DIR\"/\"nvcc_\${tag}_minimal\"
	rc=\$?
	if [ \$rc -ne 0 ]; then
		echo \"\${tag}: run FAILED rc=\${rc}\"
	fi
	set -e
	return 0
}

if [ \"\${list_gpu_arch}\" != \"\" ] && echo \"\${list_gpu_arch}\" | grep -q \"compute_121\"; then
	try_gencode_build_run gencode_sm_plus_ptx_list \"arch=compute_121,code=[sm_121,compute_121]\"
fi

	try_variant_build_run() {
		tag=\"\$1\"
		arch=\"\$2\"
		advertised=\"\${3:-unknown}\"
		echo
		echo \"-- build+run (best-effort): \${tag} (-arch=\${arch}; advertised=\${advertised})\"
		set +e
		\$NVCC -O2 -std=c++17 -arch=\"\${arch}\" -o \"$REMOTE_DIR\"/\"nvcc_\${tag}_minimal\" \"$REMOTE_DIR\"/cuda_nvcc_minimal.cu -lcuda >\"$REMOTE_DIR\"/\"nvcc_\${tag}_minimal.out\" 2>\"$REMOTE_DIR\"/\"nvcc_\${tag}_minimal.err\"
		rc=\$?
		if [ \$rc -ne 0 ]; then
			echo \"\${tag}: build FAILED rc=\${rc}\"
		head -n 60 \"$REMOTE_DIR\"/\"nvcc_\${tag}_minimal.err\" || true
		set -e
		return 0
	fi
	\"$REMOTE_DIR\"/\"nvcc_\${tag}_minimal\"
	rc=\$?
	if [ \$rc -ne 0 ]; then
		echo \"\${tag}: run FAILED rc=\${rc}\"
	fi
	set -e
		return 0
	}

	adv_sm121a=\"unknown\"
	adv_sm121f=\"unknown\"
	if [ \"\${list_gpu_code}\" != \"\" ]; then
		if echo \"\${list_gpu_code}\" | grep -q \"sm_121a\"; then
			adv_sm121a=\"yes\"
		else
			adv_sm121a=\"no\"
		fi
		if echo \"\${list_gpu_code}\" | grep -q \"sm_121f\"; then
			adv_sm121f=\"yes\"
		else
			adv_sm121f=\"no\"
		fi
	fi
	try_variant_build_run sm_121a sm_121a \"\${adv_sm121a}\"
	try_variant_build_run sm_121f sm_121f \"\${adv_sm121f}\"

	echo
	echo \"== nvcc: CUDA 13 static-global-template-stub cross-TU (best-effort) ==\"
	cat > \"$REMOTE_DIR\"/cuda_nvcc_template_stub_first.cu <<'EOF'
#include <stdint.h>

template <typename T>
__global__ void cuda_template_stub_kernel(uint32_t *out)
{
#if defined(__CUDA_ARCH__)
	if ( ((int32_t)threadIdx.x) == 0 )
		out[0] = (uint32_t)(T)0x12345678;
#else
	(void)out;
#endif
}

template __global__ void cuda_template_stub_kernel<int>(uint32_t *out);
EOF

	cat > \"$REMOTE_DIR\"/cuda_nvcc_template_stub_second.cu <<'EOF'
#include <stdint.h>
#include <stdio.h>

#include <cuda_runtime.h>

template <typename T>
__global__ void cuda_template_stub_kernel(uint32_t *out);

int main(int argc,char **argv)
{
	uint32_t *dout = 0,hout = 0;
	cudaError_t err;
	(void)argc;
	(void)argv;
	err = cudaMalloc((void **)&dout,(size_t)sizeof(uint32_t));
	if ( err != cudaSuccess )
		return(11);
	err = cudaMemset(dout,0,(size_t)sizeof(uint32_t));
	if ( err != cudaSuccess )
	{
		cudaFree(dout);
		return(12);
	}
	cuda_template_stub_kernel<int><<<1,32>>>(dout);
	err = cudaGetLastError();
	if ( err != cudaSuccess )
	{
		cudaFree(dout);
		return(13);
	}
	err = cudaDeviceSynchronize();
	if ( err != cudaSuccess )
	{
		cudaFree(dout);
		return(14);
	}
	err = cudaMemcpy(&hout,dout,(size_t)sizeof(uint32_t),cudaMemcpyDeviceToHost);
	cudaFree(dout);
	if ( err != cudaSuccess )
		return(15);
	printf(\"template_stub ok out=0x%08x\\n\",hout);
	return(0);
}
EOF

	try_template_stub_build_run() {
		tag=\"\$1\"
		extra_flags=\"\$2\"
		out_bin=\"$REMOTE_DIR\"/\"nvcc_\${tag}_template_stub\"
		echo \"-- template_stub: \${tag} (\${extra_flags})\"
		set +e
		\$NVCC -O2 -std=c++17 -arch=sm_121 \${extra_flags} -o \"\${out_bin}\" \"$REMOTE_DIR\"/cuda_nvcc_template_stub_first.cu \"$REMOTE_DIR\"/cuda_nvcc_template_stub_second.cu >\"$REMOTE_DIR\"/\"nvcc_\${tag}_template_stub.out\" 2>\"$REMOTE_DIR\"/\"nvcc_\${tag}_template_stub.err\"
		rc=\$?
		if [ \$rc -ne 0 ]; then
			echo \"template_stub_\${tag}: BUILD FAILED rc=\${rc}\"
			head -n 60 \"$REMOTE_DIR\"/\"nvcc_\${tag}_template_stub.err\" || true
			set -e
			return 0
		fi
		\"\${out_bin}\"
		rc=\$?
		if [ \$rc -eq 0 ]; then
			echo \"template_stub_\${tag}: OK\"
		else
			echo \"template_stub_\${tag}: RUN FAILED rc=\${rc}\"
		fi
		set -e
		return 0
	}

	try_template_stub_build_run default \"\"
	try_template_stub_build_run stubfalse \"-static-global-template-stub=false\"
	try_template_stub_build_run rdc \"-rdc=true\"

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
		ptx_target_line=\$(\$CUOBJDUMP --dump-ptx \"\${path}\" 2>/dev/null | grep \"^\\\\.target\" | head -n 1 || true)
		if [ \"\${ptx_target_line}\" != \"\" ]; then
			echo \"ptx_embed(\${name}): PRESENT\"
			echo \"ptx_target(\${name}): \${ptx_target_line}\"
		else
			echo \"ptx_embed(\${name}): MISSING\"
		fi
	}
	check_ptx sm_121 \"$REMOTE_DIR\"/nvcc_sm121_minimal
	check_ptx gpuarch_sm_121 \"$REMOTE_DIR\"/nvcc_gpuarch_sm121_minimal
	check_ptx native \"$REMOTE_DIR\"/nvcc_native_minimal
	if [ -x \"$REMOTE_DIR\"/nvcc_compute121_minimal ]; then
		check_ptx compute_121 \"$REMOTE_DIR\"/nvcc_compute121_minimal
	fi
	if [ -x \"$REMOTE_DIR\"/nvcc_gencode_sm_plus_ptx_list_minimal ]; then
		check_ptx gencode_sm_plus_ptx_list \"$REMOTE_DIR\"/nvcc_gencode_sm_plus_ptx_list_minimal
	fi
	if [ -x \"$REMOTE_DIR\"/nvcc_sm_121a_minimal ]; then
		check_ptx sm_121a \"$REMOTE_DIR\"/nvcc_sm_121a_minimal
	fi
	if [ -x \"$REMOTE_DIR\"/nvcc_sm_121f_minimal ]; then
		check_ptx sm_121f \"$REMOTE_DIR\"/nvcc_sm_121f_minimal
	fi
fi
"
