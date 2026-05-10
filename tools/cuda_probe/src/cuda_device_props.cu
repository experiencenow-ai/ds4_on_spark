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

static void print_device_props(const cudaDeviceProp *p,int32_t idx)
{
	int32_t clock_khz = 0,mem_clock_khz = 0,smem_per_sm = 0;
	uint64_t mem_bytes = 0,smem_per_block_bytes = 0;
	if ( p == 0 )
		return;
	get_attr_i32(&clock_khz,idx,cudaDevAttrClockRate);
	get_attr_i32(&mem_clock_khz,idx,cudaDevAttrMemoryClockRate);
	get_attr_i32(&smem_per_sm,idx,cudaDevAttrMaxSharedMemoryPerMultiprocessor);
	mem_bytes = (uint64_t)p->totalGlobalMem;
	smem_per_block_bytes = (uint64_t)p->sharedMemPerBlock;
	printf("device[%d]=%s cc=%d.%d clock_khz=%d mem=%" PRIu64 "\n",idx,p->name,p->major,p->minor,clock_khz,mem_bytes);
	printf("  mp=%d warp=%d regsPerBlock=%d sharedPerBlock=%" PRIu64 " sharedPerSM=%d mem_clock_khz=%d\n",p->multiProcessorCount,p->warpSize,p->regsPerBlock,smem_per_block_bytes,smem_per_sm,mem_clock_khz);
	printf("  maxThreadsPerBlock=%d maxThreadsDim=%d,%d,%d maxGridSize=%d,%d,%d\n",p->maxThreadsPerBlock,p->maxThreadsDim[0],p->maxThreadsDim[1],p->maxThreadsDim[2],p->maxGridSize[0],p->maxGridSize[1],p->maxGridSize[2]);
}

int main(int argc,char **argv)
{
	int32_t count = 0,dev = 0,rc = 0;
	cudaDeviceProp prop;
	(void)argc;
	(void)argv;
	cuda_probe_print_versions();
	rc = cuda_probe_check(cudaGetDeviceCount(&count),-1,"cudaGetDeviceCount");
	if ( rc != 0 )
		return(rc);
	printf("cudaGetDeviceCount=%d\n",count);
	for (dev=0; dev<count; dev++)
	{
		rc = cuda_probe_check(cudaGetDeviceProperties(&prop,dev),-2 - dev,"cudaGetDeviceProperties");
		if ( rc != 0 )
			return(rc);
		print_device_props(&prop,dev);
	}
	{
		cudaError_t err = cudaFree(0);
		if ( err != cudaSuccess )
			fprintf(stderr,"CUDA warning cudaFree(0): %s\n",cudaGetErrorString(err));
	}
	return(0);
}
