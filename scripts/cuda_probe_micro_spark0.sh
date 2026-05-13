#!/usr/bin/env sh
set -eu

target="${1:-spark0@aitopatom-9ab9.local}"
SSH_OPTS="${SSH_OPTS:-"-o BatchMode=yes -o ConnectTimeout=10 -o ServerAliveInterval=0 -o StrictHostKeyChecking=accept-new -o UserKnownHostsFile=/private/tmp/ds4_spark_known_hosts"}"
remote_tag="${REMOTE_TAG:-"$(date -u +%Y%m%d-%H%M%S)-$$"}"
default_remote_dir="/tmp/ds4_cuda_probe_micro_${remote_tag}"
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
	if echo \"\${list_gpu_arch}\" | grep -q \"compute_121\"; then
		:
	else
		echo \"(nvcc --list-gpu-arch missing compute_121)\" >&2
		exit 4
	fi
fi
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
echo \"== build: sm_121 compile probes (compile-only; no link/run) ==\"
rm -rf \"$REMOTE_DIR\"
mkdir -p \"$REMOTE_DIR\"/bin

cat > \"$REMOTE_DIR\"/cuda_sm121_compile_probe_micro.cu <<'EOF'
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

cat > \"$REMOTE_DIR\"/cuda_sm121_cxx20_flags_compile_probe_micro.cu <<'EOF'
#include <stdint.h>

#if defined(__CUDA_ARCH__)
#if (__CUDA_ARCH__ != 1210)
#error \"sm_121 cxx20 flags compile probe: expected __CUDA_ARCH__=1210 (sm_121)\"
#endif
#if !defined(__CUDACC_EXTENDED_LAMBDA__)
#error \"sm_121 cxx20 flags compile probe: expected __CUDACC_EXTENDED_LAMBDA__ defined\"
#endif
#if !defined(__CUDACC_RELAXED_CONSTEXPR__)
#error \"sm_121 cxx20 flags compile probe: expected __CUDACC_RELAXED_CONSTEXPR__ defined\"
#endif
#endif

template <typename T>
__host__ __device__ constexpr T add_constexpr(T a,T b)
{
	return((T)(a + b));
}

__global__ void sm121_cxx20_flags_compile_probe(uint32_t *out)
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

cat > \"$REMOTE_DIR\"/cuda_sm121_cluster_dims_attr_compile_probe_micro.cu <<'EOF'
#include <stdint.h>

#include <cuda_runtime.h>

__global__ void __cluster_dims__(2,1,1) cluster_dims_attr_probe(uint32_t *out)
{
	if ( ((int32_t)threadIdx.x) == 0 )
		out[(int32_t)blockIdx.x] = 0;
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
	head -n 80 \"$REMOTE_DIR\"/bin/\"\${tag}\".err || true
	return 1
}

compile_probe sm121_arch_sm_121 cuda_sm121_compile_probe_micro.cu -arch=sm_121
compile_probe sm121_gpuarch_sm_121 cuda_sm121_compile_probe_micro.cu --gpu-architecture=sm_121
compile_probe sm121_gpuarchcode_sm_121 cuda_sm121_compile_probe_micro.cu --gpu-architecture=compute_121 --gpu-code=sm_121
compile_probe sm121_cxx20_flags_arch_sm_121 cuda_sm121_cxx20_flags_compile_probe_micro.cu -arch=sm_121 -std=c++20 --extended-lambda --expt-relaxed-constexpr

echo
echo \"== build: sm_121 variant alias compile probes (best-effort) ==\"
compile_probe sm121_arch_sm_121a cuda_sm121_compile_probe_micro.cu -arch=sm_121a || true
compile_probe sm121_arch_sm_121f cuda_sm121_compile_probe_micro.cu -arch=sm_121f || true
compile_probe sm121_gpuarch_sm_121a cuda_sm121_compile_probe_micro.cu --gpu-architecture=sm_121a || true
compile_probe sm121_gpuarch_sm_121f cuda_sm121_compile_probe_micro.cu --gpu-architecture=sm_121f || true

echo
echo \"== build: sm_121 cluster dims attr compile probes (best-effort) ==\"
compile_probe sm121_cluster_dims_attr_arch_sm_121 cuda_sm121_cluster_dims_attr_compile_probe_micro.cu -arch=sm_121 || true
compile_probe sm121_cluster_dims_attr_gpuarch_sm_121 cuda_sm121_cluster_dims_attr_compile_probe_micro.cu --gpu-architecture=sm_121 || true
compile_probe sm121_cluster_dims_attr_gpuarchcode_sm_121 cuda_sm121_cluster_dims_attr_compile_probe_micro.cu --gpu-architecture=compute_121 --gpu-code=sm_121 || true

echo
echo \"== nvcc: PTX .target probe (best-effort) ==\"
try_ptx_target() {
	tag=\"\$1\"
	arch=\"\$2\"
	echo \"-- ptx: \${tag} (-arch=\${arch})\"
	set +e
	\$NVCC -O2 -std=c++17 -arch=\"\${arch}\" -ptx -o \"$REMOTE_DIR\"/bin/\"\${tag}\".ptx \"$REMOTE_DIR\"/cuda_sm121_compile_probe_micro.cu 2>\"$REMOTE_DIR\"/bin/\"\${tag}\".err
	rc=\$?
	set -e
	if [ \$rc -eq 0 ]; then
		target_line=\$(grep \"^\\\\.target\" \"$REMOTE_DIR\"/bin/\"\${tag}\".ptx | head -n 1 || true)
		if [ \"\${target_line}\" = \"\" ]; then
			target_line=\"(missing)\"
		fi
		echo \"\${tag}: OK ptx_target=\${target_line}\"
		return 0
	fi
	echo \"\${tag}: FAILED rc=\${rc}\" >&2
	head -n 60 \"$REMOTE_DIR\"/bin/\"\${tag}\".err || true
	return 1
}
try_ptx_target ptx_target_sm_121 sm_121
try_ptx_target ptx_target_compute_121 compute_121

echo
echo \"== nvcc: gencode compile (best-effort) ==\"
set +e
\$NVCC -O2 -std=c++17 -gencode \"arch=compute_121,code=[sm_121,compute_121]\" -c -o \"$REMOTE_DIR\"/bin/gencode_sm121_plus_ptx.o \"$REMOTE_DIR\"/cuda_sm121_compile_probe_micro.cu 2>\"$REMOTE_DIR\"/bin/gencode_sm121_plus_ptx.err
rc=\$?
set -e
if [ \$rc -eq 0 ]; then
	echo \"gencode_sm121_plus_ptx: OK\"
else
	echo \"gencode_sm121_plus_ptx: FAILED rc=\$rc\" >&2
	head -n 60 \"$REMOTE_DIR\"/bin/gencode_sm121_plus_ptx.err || true
	exit \"\${rc}\"
fi

echo
echo \"== build+run: cuda_device_props_tiny (schema=4) ==\"
cat > \"$REMOTE_DIR\"/cuda_device_props_tiny_micro.cu <<'EOF'
#include <stdint.h>
#include <inttypes.h>
#include <stdio.h>

#include <cuda_runtime.h>
#include <cuda.h>

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

__global__ void write_cuda_arch(uint32_t *out)
{
#if defined(__CUDA_ARCH__)
	out[0] = (uint32_t)__CUDA_ARCH__;
#else
	out[0] = 0U;
#endif
}

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

int main(int argc,char **argv)
{
	int32_t count = 0,rc = 0,driver_v = -1,runtime_v = -1,clock_khz = -1,mem_clock_khz = -1;
	int32_t smem_optin = -1,l2_bytes = -1,max_threads_sm = -1,regs_sm = -1;
	int32_t max_threads_block = -1,max_blocks_sm = -1,smem_sm = -1,regs_block = -1,smem_block_max = -1;
	int32_t coop_launch = -1,cluster_launch = -1;
	int32_t smem_reserved_block = -1,mem_pools = -1;
	int32_t tma_map = -1;
	int32_t bus_width_bits = -1,async_engines = -1,max_persisting_l2 = -1,max_apw_bytes = -1;
	cudaDeviceProp prop;
	uint32_t cuda_arch = 0;
	uint32_t *d_arch = 0;
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
		printf(\"cuda drv=%d rt=%d count=%d bus_width_bits=%d async_engines=%d max_persisting_l2=%d max_apw=%d tma_map=%d cuda_arch=%u schema=4\\n\",driver_v,runtime_v,count,bus_width_bits,async_engines,max_persisting_l2,max_apw_bytes,tma_map,cuda_arch);
		return(0);
	}
	rc = ck(cudaGetDeviceProperties(&prop,0),-2,\"cudaGetDeviceProperties(0)\");
	if ( rc != 0 )
		return(rc);
	(void)get_attr_i32(&clock_khz,0,cudaDevAttrClockRate);
	(void)get_attr_i32(&mem_clock_khz,0,cudaDevAttrMemoryClockRate);
	(void)get_attr_i32(&bus_width_bits,0,cudaDevAttrGlobalMemoryBusWidth);
	(void)get_attr_i32(&async_engines,0,cudaDevAttrAsyncEngineCount);
	(void)get_attr_i32(&smem_optin,0,cudaDevAttrMaxSharedMemoryPerBlockOptin);
	(void)get_attr_i32(&l2_bytes,0,cudaDevAttrL2CacheSize);
	(void)get_attr_i32(&max_persisting_l2,0,cudaDevAttrMaxPersistingL2CacheSize);
	(void)get_attr_i32(&max_apw_bytes,0,cudaDevAttrMaxAccessPolicyWindowSize);
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
#if defined(CUDA_VERSION) && (CUDA_VERSION >= 12000)
	(void)get_cu_attr_i32(&tma_map,0,CU_DEVICE_ATTRIBUTE_TENSOR_MAP_ACCESS_SUPPORTED);
#else
	tma_map = -1;
#endif
	(void)cudaGetLastError();
	if ( cudaMemcpyFromSymbol(&cuda_arch,ds4_cuda_arch_const,sizeof(cuda_arch),0,cudaMemcpyDeviceToHost) != cudaSuccess )
	{
		(void)cudaGetLastError();
		cuda_arch = 0;
		if ( cudaMalloc((void **)&d_arch,sizeof(uint32_t)) == cudaSuccess )
		{
			if ( cudaMemset(d_arch,0,sizeof(uint32_t)) == cudaSuccess )
			{
				write_cuda_arch<<<1,1>>>(d_arch);
				if ( cudaGetLastError() == cudaSuccess )
				{
					(void)cudaDeviceSynchronize();
					(void)cudaGetLastError();
					(void)cudaMemcpy(&cuda_arch,d_arch,sizeof(uint32_t),cudaMemcpyDeviceToHost);
				}
			}
			cudaFree(d_arch);
			d_arch = 0;
		}
	}
	mem_bytes = (uint64_t)prop.totalGlobalMem;
	smem_block_bytes = (uint64_t)prop.sharedMemPerBlock;
	printf(\"cuda drv=%d rt=%d count=%d dev0=\\\"%s\\\" cc=%d.%d mp=%d warp=%d clock_khz=%d mem_clock_khz=%d bus_width_bits=%d async_engines=%d mem=%\" PRIu64 \" smem_block=%\" PRIu64 \" smem_block_max=%d smem_optin=%d smem_sm=%d smem_reserved_block=%d l2=%d max_persisting_l2=%d max_apw=%d maxthr_block=%d maxthr_sm=%d maxblocks_sm=%d regs_block=%d regs_sm=%d mem_pools=%d coop_launch=%d cluster_launch=%d tma_map=%d cuda_arch=%u schema=4\\n\",driver_v,runtime_v,count,prop.name,prop.major,prop.minor,prop.multiProcessorCount,prop.warpSize,clock_khz,mem_clock_khz,bus_width_bits,async_engines,mem_bytes,smem_block_bytes,smem_block_max,smem_optin,smem_sm,smem_reserved_block,l2_bytes,max_persisting_l2,max_apw_bytes,max_threads_block,max_threads_sm,max_blocks_sm,regs_block,regs_sm,mem_pools,coop_launch,cluster_launch,tma_map,cuda_arch);
	return(0);
}
EOF

\$NVCC -O2 -std=c++17 -arch=native -o \"$REMOTE_DIR\"/bin/cuda_device_props_tiny_micro \"$REMOTE_DIR\"/cuda_device_props_tiny_micro.cu -lcuda
\"$REMOTE_DIR\"/bin/cuda_device_props_tiny_micro

echo
echo \"== build+run: kernel launch tiny minimal (best-effort) ==\"
cat > \"$REMOTE_DIR\"/cuda_kernel_launch_tiny_micro.cu <<'EOF'
#include <stdint.h>
#include <stdio.h>

#include <cuda_runtime.h>

__global__ void kernel_launch_tiny_micro(void)
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
	kernel_launch_tiny_micro<<<1,1>>>();
	rc = ck(cudaGetLastError(),-2,\"kernel launch\");
	if ( rc != 0 )
		return(rc);
	rc = ck(cudaDeviceSynchronize(),-3,\"cudaDeviceSynchronize\");
	if ( rc != 0 )
		return(rc);
	printf(\"kernel_launch_tiny_micro ok\\n\");
	return(0);
}
EOF

\$NVCC -O2 -std=c++17 -arch=native -o \"$REMOTE_DIR\"/bin/cuda_kernel_launch_tiny_micro \"$REMOTE_DIR\"/cuda_kernel_launch_tiny_micro.cu

set +e
out=\$(\"$REMOTE_DIR\"/bin/cuda_kernel_launch_tiny_micro 2>&1)
rc=\$?
set -e
printf \"%s\\n\" \"\${out}\"
if [ \"\${rc}\" -eq 0 ]; then
	echo \"kernel_launch_tiny_micro: OK\"
	exit 0
fi
if printf \"%s\\n\" \"\${out}\" | grep -Eqi \"out of memory|busy or unavailable|device is busy\"; then
	echo \"kernel_launch_tiny_micro: SKIP rc=\${rc} (GPU OOM/busy)\" >&2
	exit 0
fi
echo \"kernel_launch_tiny_micro: FAILED rc=\${rc}\" >&2
exit \"\${rc}\"
"
}

if [ "$log_path" = "" ]; then
	main
	exit 0
fi

mkdir -p "$(dirname "$log_path")"
printf "== cuda_probe_micro_spark0 log: %s ==\n" "$(date -u +%Y-%m-%dT%H:%M:%SZ)" >> "$log_path"
tmp_out="$(mktemp "/private/tmp/ds4_cuda_probe_micro_out.XXXXXX")"
set +e
main >"$tmp_out" 2>&1
rc=$?
set -e
cat "$tmp_out"
cat "$tmp_out" >> "$log_path"
rm -f "$tmp_out"
exit $rc
