#include <stdint.h>
#include <stdio.h>

#include <cuda_runtime.h>

#include "cuda_probe_util.h"

int main(int argc,char **argv)
{
	int32_t count = 0,rc = 0;
	cudaDeviceProp prop;
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
	printf("device[0]=%s cc=%d.%d mp=%d mem=%zu\n",prop.name,prop.major,prop.minor,prop.multiProcessorCount,(size_t)prop.totalGlobalMem);
	return(0);
}

