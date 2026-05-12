#include <stdint.h>
#include <inttypes.h>
#include <stdio.h>

#include <cuda_runtime.h>
#include <cuda.h>

#include "cuda_probe_util.h"

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
	rc = cuda_probe_check(cudaGetDeviceCount(&count),-1,"cudaGetDeviceCount");
	if ( rc != 0 )
		return(rc);
	if ( count <= 0 )
	{
		printf("cuda drv=%d rt=%d count=%d bus_width_bits=%d async_engines=%d max_persisting_l2=%d max_apw=%d tma_map=%d cuda_arch=%u schema=4\n",driver_v,runtime_v,count,bus_width_bits,async_engines,max_persisting_l2,max_apw_bytes,tma_map,cuda_arch);
		return(0);
	}
	rc = cuda_probe_check(cudaGetDeviceProperties(&prop,0),-2,"cudaGetDeviceProperties(0)");
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
	if ( cudaMalloc((void **)&d_arch,(size_t)sizeof(uint32_t)) == cudaSuccess )
	{
		if ( cudaMemset(d_arch,0,(size_t)sizeof(uint32_t)) == cudaSuccess )
		{
			write_cuda_arch<<<1,1>>>(d_arch);
			if ( cudaGetLastError() == cudaSuccess )
				(void)cudaMemcpy(&cuda_arch,d_arch,(size_t)sizeof(uint32_t),cudaMemcpyDeviceToHost);
		}
		cudaFree(d_arch);
		d_arch = 0;
	}
	mem_bytes = (uint64_t)prop.totalGlobalMem;
	smem_block_bytes = (uint64_t)prop.sharedMemPerBlock;
	printf("cuda drv=%d rt=%d count=%d dev0=\"%s\" cc=%d.%d mp=%d warp=%d clock_khz=%d mem_clock_khz=%d bus_width_bits=%d async_engines=%d mem=%" PRIu64 " smem_block=%" PRIu64 " smem_block_max=%d smem_optin=%d smem_sm=%d smem_reserved_block=%d l2=%d max_persisting_l2=%d max_apw=%d maxthr_block=%d maxthr_sm=%d maxblocks_sm=%d regs_block=%d regs_sm=%d mem_pools=%d coop_launch=%d cluster_launch=%d tma_map=%d cuda_arch=%u schema=4\n",driver_v,runtime_v,count,prop.name,prop.major,prop.minor,prop.multiProcessorCount,prop.warpSize,clock_khz,mem_clock_khz,bus_width_bits,async_engines,mem_bytes,smem_block_bytes,smem_block_max,smem_optin,smem_sm,smem_reserved_block,l2_bytes,max_persisting_l2,max_apw_bytes,max_threads_block,max_threads_sm,max_blocks_sm,regs_block,regs_sm,mem_pools,coop_launch,cluster_launch,tma_map,cuda_arch);
	return(0);
}
