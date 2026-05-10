#include <stdint.h>

#include <cuda_runtime.h>

__global__ void __cluster_dims__(2,1,1) cluster_dims_attr_probe(uint32_t *out)
{
	if ( ((int32_t)threadIdx.x) == 0 )
		out[(int32_t)blockIdx.x] = 0;
}

