#!/usr/bin/env sh
set -eu

target="${1:-spark0@aitopatom-9ab9.local}"
SSH_OPTS="${SSH_OPTS:-"-o BatchMode=yes -o ConnectTimeout=10 -o ServerAliveInterval=0 -o StrictHostKeyChecking=accept-new -o UserKnownHostsFile=/private/tmp/ds4_spark_known_hosts"}"
REMOTE_DIR="${REMOTE_DIR:-/tmp/ds4_cuda_probe_device_props_minimal}"
log_path="${LOG_PATH:-}"
with_sm121_run="${WITH_SM121_RUN:-0}"
with_compute121_run="${WITH_COMPUTE121_RUN:-0}"
with_gencode_run="${WITH_GENCODE_RUN:-0}"

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
echo \"== build: cuda_device_props_minimal (-arch=native) ==\"
rm -rf \"$REMOTE_DIR\"
mkdir -p \"$REMOTE_DIR\"
cat > \"$REMOTE_DIR\"/cuda_device_props_minimal.cu <<'EOF'
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
	rc = ck(cudaMalloc((void **)&d_arch,sizeof(uint32_t)),-3,\"cudaMalloc(d_arch)\");
	if ( rc == 0 )
	{
		rc = ck(cudaMemset(d_arch,0,sizeof(uint32_t)),-4,\"cudaMemset(d_arch)\");
		if ( rc == 0 )
		{
			write_cuda_arch<<<1,1>>>(d_arch);
			rc = ck(cudaGetLastError(),-5,\"write_cuda_arch launch\");
			if ( rc == 0 )
				(void)ck(cudaMemcpy(&cuda_arch,d_arch,sizeof(uint32_t),cudaMemcpyDeviceToHost),-6,\"cudaMemcpy(cuda_arch)\");
		}
		cudaFree(d_arch);
	}
	mem_bytes = (uint64_t)prop.totalGlobalMem;
	smem_block_bytes = (uint64_t)prop.sharedMemPerBlock;
	printf(\"cuda drv=%d rt=%d count=%d dev0=\\\"%s\\\" cc=%d.%d mp=%d warp=%d clock_khz=%d mem_clock_khz=%d bus_width_bits=%d async_engines=%d mem=%\" PRIu64 \" smem_block=%\" PRIu64 \" smem_block_max=%d smem_optin=%d smem_sm=%d smem_reserved_block=%d l2=%d max_persisting_l2=%d max_apw=%d maxthr_block=%d maxthr_sm=%d maxblocks_sm=%d regs_block=%d regs_sm=%d mem_pools=%d coop_launch=%d cluster_launch=%d tma_map=%d cuda_arch=%u schema=4\\n\",driver_v,runtime_v,count,prop.name,prop.major,prop.minor,prop.multiProcessorCount,prop.warpSize,clock_khz,mem_clock_khz,bus_width_bits,async_engines,mem_bytes,smem_block_bytes,smem_block_max,smem_optin,smem_sm,smem_reserved_block,l2_bytes,max_persisting_l2,max_apw_bytes,max_threads_block,max_threads_sm,max_blocks_sm,regs_block,regs_sm,mem_pools,coop_launch,cluster_launch,tma_map,cuda_arch);
	return(0);
}
EOF

\$NVCC -O2 -std=c++17 -arch=native -o \"$REMOTE_DIR\"/cuda_device_props_minimal \"$REMOTE_DIR\"/cuda_device_props_minimal.cu -lcuda

if [ \"${with_sm121_run}\" = \"1\" ]; then
	echo
	echo \"== build: cuda_device_props_minimal (-arch=sm_121) ==\"
	\$NVCC -O2 -std=c++17 -arch=sm_121 -o \"$REMOTE_DIR\"/cuda_device_props_minimal_sm121 \"$REMOTE_DIR\"/cuda_device_props_minimal.cu -lcuda

	echo
	echo \"== build: cuda_device_props_minimal (nvcc --gpu-architecture=sm_121) ==\"
	\$NVCC -O2 -std=c++17 --gpu-architecture=sm_121 -o \"$REMOTE_DIR\"/cuda_device_props_minimal_gpuarch_sm121 \"$REMOTE_DIR\"/cuda_device_props_minimal.cu -lcuda
fi

if [ \"${with_compute121_run}\" = \"1\" ]; then
	echo
	echo \"== build: cuda_device_props_minimal (-arch=compute_121; best-effort) ==\"
	do_build_compute121=1
	if [ \"\${list_gpu_arch}\" = \"\" ]; then
		echo \"(nvcc --list-gpu-arch not supported; attempting build anyway)\"
	else
		if echo \"\${list_gpu_arch}\" | grep -q \"compute_121\"; then
			:
		else
			echo \"(nvcc --list-gpu-arch missing compute_121; skipping)\" >&2
			do_build_compute121=0
		fi
	fi
	if [ \"\${do_build_compute121}\" = \"1\" ]; then
		set +e
		\$NVCC -O2 -std=c++17 -arch=compute_121 -o \"$REMOTE_DIR\"/cuda_device_props_minimal_compute121 \"$REMOTE_DIR\"/cuda_device_props_minimal.cu -lcuda 2>\"$REMOTE_DIR\"/cuda_device_props_minimal_compute121.err
		rc=\$?
		set -e
		if [ \$rc -eq 0 ]; then
			echo \"compute_121_build: OK\"
		else
			echo \"compute_121_build: FAILED rc=\$rc\" >&2
			head -n 60 \"$REMOTE_DIR\"/cuda_device_props_minimal_compute121.err || true
		fi
	fi
fi

if [ \"${with_gencode_run}\" = \"1\" ]; then
	echo
	echo \"== build: cuda_device_props_minimal (-gencode compute_121->[sm_121,compute_121]; best-effort) ==\"
	do_build_gencode=1
	if [ \"\${list_gpu_arch}\" = \"\" ]; then
		echo \"(nvcc --list-gpu-arch not supported; attempting build anyway)\"
	else
		if echo \"\${list_gpu_arch}\" | grep -q \"compute_121\"; then
			:
		else
			echo \"(nvcc --list-gpu-arch missing compute_121; skipping)\" >&2
			do_build_gencode=0
		fi
	fi
	if [ \"\${do_build_gencode}\" = \"1\" ]; then
		set +e
		\$NVCC -O2 -std=c++17 -gencode arch=compute_121,code=sm_121 -gencode arch=compute_121,code=compute_121 -o \"$REMOTE_DIR\"/cuda_device_props_minimal_gencode \"$REMOTE_DIR\"/cuda_device_props_minimal.cu -lcuda 2>\"$REMOTE_DIR\"/cuda_device_props_minimal_gencode.err
		rc=\$?
		set -e
		if [ \$rc -eq 0 ]; then
			echo \"gencode_build: OK\"
		else
			echo \"gencode_build: FAILED rc=\$rc\" >&2
			head -n 60 \"$REMOTE_DIR\"/cuda_device_props_minimal_gencode.err || true
		fi
	fi
fi

echo
echo \"== build: sm_121 compile-only gate ==\"
cat > \"$REMOTE_DIR\"/cuda_sm121_compile_only.cu <<'EOF'
#include <stdint.h>

#if defined(__CUDA_ARCH__)
#if (__CUDA_ARCH__ != 1210)
#error ds4_cuda_sm121_compile_only_expected___CUDA_ARCH___1210
#endif
#endif

__global__ void cuda_sm121_compile_only(uint32_t *out)
{
#if defined(__CUDA_ARCH__)
	if ( out != 0 )
		out[0] = (uint32_t)__CUDA_ARCH__;
#else
	(void)out;
#endif
}
EOF
set +e
\$NVCC -O2 -std=c++17 -arch=sm_121 -c -o \"$REMOTE_DIR\"/cuda_sm121_compile_only.o \"$REMOTE_DIR\"/cuda_sm121_compile_only.cu 2>\"$REMOTE_DIR\"/cuda_sm121_compile_only.err
rc=\$?
set -e
	if [ \$rc -eq 0 ]; then
		echo \"sm_121_compile_only: OK\"
	else
		echo \"sm_121_compile_only: FAILED rc=\$rc\" >&2
		head -n 60 \"$REMOTE_DIR\"/cuda_sm121_compile_only.err || true
		exit 4
	fi

	echo
	echo \"== build: sm_121 compile-only gate (nvcc --gpu-architecture) ==\"
	set +e
	\$NVCC -O2 -std=c++17 --gpu-architecture=sm_121 -c -o \"$REMOTE_DIR\"/cuda_sm121_gpuarch_compile_only.o \"$REMOTE_DIR\"/cuda_sm121_compile_only.cu 2>\"$REMOTE_DIR\"/cuda_sm121_gpuarch_compile_only.err
	rc=\$?
	set -e
	if [ \$rc -eq 0 ]; then
		echo \"sm_121_gpuarch_compile_only: OK\"
	else
		echo \"sm_121_gpuarch_compile_only: FAILED rc=\$rc\" >&2
		head -n 60 \"$REMOTE_DIR\"/cuda_sm121_gpuarch_compile_only.err || true
		exit 5
	fi
	
	echo
	echo \"== run: cuda_device_props_minimal ==\"
	\"$REMOTE_DIR\"/cuda_device_props_minimal
	if [ \"${with_sm121_run}\" = \"1\" ]; then
		echo
		echo \"== run: cuda_device_props_minimal_sm121 ==\"
		\"$REMOTE_DIR\"/cuda_device_props_minimal_sm121
		echo
		echo \"== run: cuda_device_props_minimal_gpuarch_sm121 ==\"
		\"$REMOTE_DIR\"/cuda_device_props_minimal_gpuarch_sm121
	fi
	if [ -x \"$REMOTE_DIR\"/cuda_device_props_minimal_compute121 ]; then
		echo
		echo \"== run: cuda_device_props_minimal_compute121 ==\"
		\"$REMOTE_DIR\"/cuda_device_props_minimal_compute121
	fi
	if [ -x \"$REMOTE_DIR\"/cuda_device_props_minimal_gencode ]; then
		echo
		echo \"== run: cuda_device_props_minimal_gencode ==\"
		\"$REMOTE_DIR\"/cuda_device_props_minimal_gencode
	fi
"
}

if [ "$log_path" = "" ]; then
	main
	exit 0
fi

mkdir -p "$(dirname "$log_path")"
printf "== cuda_probe_device_props_minimal_spark0 log: %s ==\n" "$(date -u +%Y-%m-%dT%H:%M:%SZ)" >> "$log_path"
tmp_out="$(mktemp "/private/tmp/ds4_cuda_probe_device_props_minimal_out.XXXXXX")"
set +e
main >"$tmp_out" 2>&1
rc=$?
set -e
cat "$tmp_out"
cat "$tmp_out" >> "$log_path"
rm -f "$tmp_out"
exit $rc
