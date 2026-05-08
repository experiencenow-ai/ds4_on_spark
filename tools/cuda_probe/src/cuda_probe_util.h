#pragma once

#include <stdint.h>
#include <stdio.h>

#include <cuda_runtime.h>

static inline int32_t cuda_probe_check(cudaError_t err,int32_t code,const char *callsite)
{
	if ( err == cudaSuccess )
		return(0);
	fprintf(stderr,"CUDA error %s: %s\n",callsite,cudaGetErrorString(err));
	return(code);
}

static inline void cuda_probe_print_versions(void)
{
	int32_t driver_v = 0,runtime_v = 0;
	cudaDriverGetVersion(&driver_v);
	cudaRuntimeGetVersion(&runtime_v);
	printf("cudaDriverGetVersion=%d cudaRuntimeGetVersion=%d\n",driver_v,runtime_v);
}
