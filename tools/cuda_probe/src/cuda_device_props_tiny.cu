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
	int32_t count = 0,rc = 0,driver_v = 0,runtime_v = 0,clock_khz = 0;
	cudaDeviceProp prop;
	uint64_t mem_bytes = 0;
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
	mem_bytes = (uint64_t)prop.totalGlobalMem;
	printf("cuda drv=%d rt=%d count=%d dev0=\"%s\" cc=%d.%d mp=%d clock_khz=%d mem=%" PRIu64 "\n",driver_v,runtime_v,count,prop.name,prop.major,prop.minor,prop.multiProcessorCount,clock_khz,mem_bytes);
	return(0);
}
