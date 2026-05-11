#include <stdint.h>
#include <stdio.h>

#include <cuda_runtime.h>

#include "cuda_probe_util.h"

static void print_attr_i32(int32_t dev,const char *name,cudaDeviceAttr attr)
{
	int32_t v = 0;
	cudaError_t err;
	if ( name == 0 )
		return;
	err = cudaDeviceGetAttribute(&v,attr,dev);
	if ( err != cudaSuccess )
	{
		printf("%s=ERR(%d:%s)\n",name,(int32_t)err,cudaGetErrorString(err));
		return;
	}
	printf("%s=%d\n",name,v);
}

static int32_t print_device(int32_t dev)
{
	int32_t rc = 0;
	cudaDeviceProp prop;
	rc = cuda_probe_check(cudaGetDeviceProperties(&prop,dev),-200 - dev,"cudaGetDeviceProperties");
	if ( rc != 0 )
		return(rc);
	printf("device[%d]=%s cc=%d.%d\n",dev,prop.name,prop.major,prop.minor);
	print_attr_i32(dev,"cudaDevAttrClockRate_khz",cudaDevAttrClockRate);
	print_attr_i32(dev,"cudaDevAttrMemoryClockRate_khz",cudaDevAttrMemoryClockRate);
	print_attr_i32(dev,"cudaDevAttrWarpSize",cudaDevAttrWarpSize);
	print_attr_i32(dev,"cudaDevAttrMultiProcessorCount",cudaDevAttrMultiProcessorCount);
	print_attr_i32(dev,"cudaDevAttrMaxThreadsPerBlock",cudaDevAttrMaxThreadsPerBlock);
	print_attr_i32(dev,"cudaDevAttrMaxThreadsPerMultiProcessor",cudaDevAttrMaxThreadsPerMultiProcessor);
	print_attr_i32(dev,"cudaDevAttrMaxBlocksPerMultiprocessor",cudaDevAttrMaxBlocksPerMultiprocessor);
	print_attr_i32(dev,"cudaDevAttrMaxSharedMemoryPerBlock",cudaDevAttrMaxSharedMemoryPerBlock);
	print_attr_i32(dev,"cudaDevAttrMaxSharedMemoryPerBlockOptin",cudaDevAttrMaxSharedMemoryPerBlockOptin);
	print_attr_i32(dev,"cudaDevAttrMaxSharedMemoryPerMultiprocessor",cudaDevAttrMaxSharedMemoryPerMultiprocessor);
	print_attr_i32(dev,"cudaDevAttrMaxRegistersPerBlock",cudaDevAttrMaxRegistersPerBlock);
	print_attr_i32(dev,"cudaDevAttrMaxRegistersPerMultiprocessor",cudaDevAttrMaxRegistersPerMultiprocessor);
	print_attr_i32(dev,"cudaDevAttrL2CacheSize_bytes",cudaDevAttrL2CacheSize);
	print_attr_i32(dev,"cudaDevAttrReservedSharedMemoryPerBlock_bytes",cudaDevAttrReservedSharedMemoryPerBlock);
	print_attr_i32(dev,"cudaDevAttrMemoryPoolsSupported",cudaDevAttrMemoryPoolsSupported);
	print_attr_i32(dev,"cudaDevAttrConcurrentKernels",cudaDevAttrConcurrentKernels);
	print_attr_i32(dev,"cudaDevAttrCooperativeLaunch",cudaDevAttrCooperativeLaunch);
	print_attr_i32(dev,"cudaDevAttrClusterLaunch",cudaDevAttrClusterLaunch);
	return(0);
}

int main(int argc,char **argv)
{
	int32_t count = 0,dev = 0,rc = 0;
	(void)argc;
	(void)argv;
	cuda_probe_print_versions();
	rc = cuda_probe_check(cudaGetDeviceCount(&count),-1,"cudaGetDeviceCount");
	if ( rc != 0 )
		return(rc);
	printf("cudaGetDeviceCount=%d\n",count);
	for (dev=0; dev<count; dev++)
	{
		printf("== device[%d] ==\n",dev);
		rc = cuda_probe_check(cudaSetDevice(dev),-10 - dev,"cudaSetDevice");
		if ( rc != 0 )
			return(rc);
		rc = print_device(dev);
		if ( rc != 0 )
			return(rc);
	}
	return(0);
}
