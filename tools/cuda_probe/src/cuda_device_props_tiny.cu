#include <stdint.h>
#include <inttypes.h>
#include <stdio.h>

#include <cuda_runtime.h>

#include "cuda_probe_util.h"

int main(int argc,char **argv)
{
	int32_t count = 0,rc = 0;
	cudaDeviceProp prop;
	uint64_t mem_bytes = 0;
	(void)argc;
	(void)argv;
	cuda_probe_print_versions();
	rc = cuda_probe_check(cudaGetDeviceCount(&count),-1,"cudaGetDeviceCount");
	if ( rc != 0 )
		return(rc);
	printf("cudaGetDeviceCount=%d\n",count);
	if ( count <= 0 )
		return(0);
	rc = cuda_probe_check(cudaGetDeviceProperties(&prop,0),-2,"cudaGetDeviceProperties(0)");
	if ( rc != 0 )
		return(rc);
	mem_bytes = (uint64_t)prop.totalGlobalMem;
	printf("device[0]=%s cc=%d.%d mp=%d mem=%" PRIu64 "\n",prop.name,prop.major,prop.minor,prop.multiProcessorCount,mem_bytes);
	return(0);
}
