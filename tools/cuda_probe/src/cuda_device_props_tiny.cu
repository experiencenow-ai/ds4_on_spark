#include <stdint.h>
#include <inttypes.h>
#include <stdio.h>

#include <cuda_runtime.h>

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

int main(int argc,char **argv)
{
	int32_t count = 0,rc = 0,driver_v = -1,runtime_v = -1,clock_khz = -1,mem_clock_khz = -1;
	int32_t smem_optin = -1,l2_bytes = -1,max_threads_sm = -1,regs_sm = -1;
	int32_t max_threads_block = -1,max_blocks_sm = -1,smem_sm = -1,regs_block = -1,smem_block_max = -1;
	int32_t coop_launch = -1,cluster_launch = -1;
	int32_t smem_reserved_block = -1,mem_pools = -1;
	cudaDeviceProp prop;
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
		printf("cuda drv=%d rt=%d count=%d schema=1\n",driver_v,runtime_v,count);
		return(0);
	}
	rc = cuda_probe_check(cudaGetDeviceProperties(&prop,0),-2,"cudaGetDeviceProperties(0)");
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
	mem_bytes = (uint64_t)prop.totalGlobalMem;
	smem_block_bytes = (uint64_t)prop.sharedMemPerBlock;
	printf("cuda drv=%d rt=%d count=%d dev0=\"%s\" cc=%d.%d mp=%d warp=%d clock_khz=%d mem_clock_khz=%d mem=%" PRIu64 " smem_block=%" PRIu64 " smem_block_max=%d smem_optin=%d smem_sm=%d smem_reserved_block=%d l2=%d maxthr_block=%d maxthr_sm=%d maxblocks_sm=%d regs_block=%d regs_sm=%d mem_pools=%d coop_launch=%d cluster_launch=%d schema=1\n",driver_v,runtime_v,count,prop.name,prop.major,prop.minor,prop.multiProcessorCount,prop.warpSize,clock_khz,mem_clock_khz,mem_bytes,smem_block_bytes,smem_block_max,smem_optin,smem_sm,smem_reserved_block,l2_bytes,max_threads_block,max_threads_sm,max_blocks_sm,regs_block,regs_sm,mem_pools,coop_launch,cluster_launch);
	return(0);
}
