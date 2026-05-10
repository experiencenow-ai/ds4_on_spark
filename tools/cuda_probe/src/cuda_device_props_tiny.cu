#include <stdint.h>
#include <inttypes.h>
#include <stdio.h>

#include <cuda_runtime.h>

#include "cuda_probe_util.h"

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

int main(int argc,char **argv)
{
	int32_t count = 0,rc = 0,driver_v = 0,runtime_v = 0,clock_khz = 0,mem_clock_khz = 0;
	int32_t smem_optin = 0,l2_bytes = 0,max_threads_sm = 0,regs_sm = 0;
	int32_t max_threads_block = 0,max_blocks_sm = 0,smem_sm = 0,regs_block = 0,smem_block_max = 0;
	cudaDeviceProp prop;
	uint64_t mem_bytes = 0,smem_block_bytes = 0;
	(void)argc;
	(void)argv;
	cudaDriverGetVersion(&driver_v);
	cudaRuntimeGetVersion(&runtime_v);
	rc = cuda_probe_check(cudaGetDeviceCount(&count),-1,"cudaGetDeviceCount");
	if ( rc != 0 )
		return(rc);
	if ( count <= 0 )
	{
		printf("cuda drv=%d rt=%d count=%d\n",driver_v,runtime_v,count);
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
	mem_bytes = (uint64_t)prop.totalGlobalMem;
	smem_block_bytes = (uint64_t)prop.sharedMemPerBlock;
	printf("cuda drv=%d rt=%d count=%d dev0=\"%s\" cc=%d.%d mp=%d warp=%d clock_khz=%d mem_clock_khz=%d mem=%" PRIu64 " smem_block=%" PRIu64 " smem_block_max=%d smem_optin=%d smem_sm=%d l2=%d maxthr_block=%d maxthr_sm=%d maxblocks_sm=%d regs_block=%d regs_sm=%d\n",driver_v,runtime_v,count,prop.name,prop.major,prop.minor,prop.multiProcessorCount,prop.warpSize,clock_khz,mem_clock_khz,mem_bytes,smem_block_bytes,smem_block_max,smem_optin,smem_sm,l2_bytes,max_threads_block,max_threads_sm,max_blocks_sm,regs_block,regs_sm);
	return(0);
}
