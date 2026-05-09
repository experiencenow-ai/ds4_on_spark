#include <stdint.h>
#include <stdio.h>

#include <cooperative_groups.h>
#include <cuda/barrier>
#include <cuda_runtime.h>

#include "cuda_probe_util.h"

__global__ void barrier_memcpy_async_u32(const uint32_t *in,uint32_t *out)
{
	__shared__ uint32_t sh[32];
#pragma nv_diag_suppress static_var_with_dynamic_init
	__shared__ cuda::barrier<cuda::thread_scope_block> barrier;
	cooperative_groups::thread_block block = cooperative_groups::this_thread_block();
	uint32_t i;
	if ( blockIdx.x != 0 )
		return;
	i = (uint32_t)block.thread_rank();
	if ( i >= 32 )
		return;
	if ( i == 0 )
		init(&barrier,block.size());
	block.sync();
	cuda::memcpy_async(&sh[i],&in[i],cuda::aligned_size_t<4>((size_t)sizeof(uint32_t)),barrier);
	barrier.arrive_and_wait();
	out[i] = sh[i];
}

int main(int argc,char **argv)
{
	uint32_t *d_in = 0,*d_out = 0;
	uint32_t h_in[32],h_out[32];
	int32_t rc = 0,i;
	(void)argc;
	(void)argv;
	cuda_probe_print_versions();
	for (i=0; i<32; i++)
	{
		h_in[i] = (uint32_t)(0xdecaf000u + (uint32_t)i);
		h_out[i] = 0;
	}
	rc = cuda_probe_check(cudaMalloc((void **)&d_in,(size_t)(32 * (int32_t)sizeof(uint32_t))),-1,"cudaMalloc(d_in)");
	if ( rc != 0 )
		return(rc);
	rc = cuda_probe_check(cudaMalloc((void **)&d_out,(size_t)(32 * (int32_t)sizeof(uint32_t))),-2,"cudaMalloc(d_out)");
	if ( rc != 0 )
	{
		cudaFree(d_in);
		return(rc);
	}
	rc = cuda_probe_check(cudaMemcpy(d_in,h_in,(size_t)(32 * (int32_t)sizeof(uint32_t)),cudaMemcpyHostToDevice),-3,"cudaMemcpy(H2D)");
	if ( rc != 0 )
	{
		cudaFree(d_out);
		cudaFree(d_in);
		return(rc);
	}
	rc = cuda_probe_check(cudaMemset(d_out,0,(size_t)(32 * (int32_t)sizeof(uint32_t))),-4,"cudaMemset(d_out)");
	if ( rc != 0 )
	{
		cudaFree(d_out);
		cudaFree(d_in);
		return(rc);
	}
	barrier_memcpy_async_u32<<<1,32>>>(d_in,d_out);
	rc = cuda_probe_check(cudaGetLastError(),-5,"kernel launch");
	if ( rc != 0 )
	{
		cudaFree(d_out);
		cudaFree(d_in);
		return(rc);
	}
	rc = cuda_probe_check(cudaDeviceSynchronize(),-6,"cudaDeviceSynchronize");
	if ( rc != 0 )
	{
		cudaFree(d_out);
		cudaFree(d_in);
		return(rc);
	}
	rc = cuda_probe_check(cudaMemcpy(h_out,d_out,(size_t)(32 * (int32_t)sizeof(uint32_t)),cudaMemcpyDeviceToHost),-7,"cudaMemcpy(D2H)");
	if ( rc != 0 )
	{
		cudaFree(d_out);
		cudaFree(d_in);
		return(rc);
	}
	cudaFree(d_out);
	cudaFree(d_in);
	for (i=0; i<32; i++)
	{
		if ( h_out[i] != h_in[i] )
		{
			fprintf(stderr,"barrier_memcpy_async mismatch i=%d got=%08x want=%08x\n",i,h_out[i],h_in[i]);
			return(-8);
		}
	}
	printf("barrier_memcpy_async ok first=%08x last=%08x\n",h_out[0],h_out[31]);
	return(0);
}
