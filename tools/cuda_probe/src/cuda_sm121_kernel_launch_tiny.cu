#include <stdint.h>
#include <stdio.h>

#include <cuda_runtime.h>

#include "cuda_probe_util.h"

__global__ void kernel_launch_tiny(void)
{
}

int main(int argc,char **argv)
{
	cudaDeviceProp prop;
	int32_t rc = 0;
	(void)argc;
	(void)argv;
	cuda_probe_print_versions();
	rc = cuda_probe_check(cudaGetDeviceProperties(&prop,0),-1,"cudaGetDeviceProperties(0)");
	if ( rc != 0 )
		return(rc);
	printf("device[0]=%s cc=%d.%d\n",prop.name,prop.major,prop.minor);
	kernel_launch_tiny<<<1,1>>>();
	rc = cuda_probe_check(cudaGetLastError(),-2,"kernel launch");
	if ( rc != 0 )
		return(rc);
	rc = cuda_probe_check(cudaDeviceSynchronize(),-3,"cudaDeviceSynchronize");
	if ( rc != 0 )
		return(rc);
	printf("kernel_launch_tiny ok\n");
	return(0);
}

