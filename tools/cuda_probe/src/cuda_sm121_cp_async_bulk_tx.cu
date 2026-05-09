#include <stdint.h>
#include <stddef.h>
#include <stdio.h>

#include <cuda/__barrier/barrier_expect_tx.h>
#include <cuda/__memcpy_async/memcpy_async_tx.h>
#include <cuda/barrier>
#include <cuda_runtime.h>

#include "cuda_probe_util.h"

__global__ void cp_async_bulk_tx_u4(const uint4 *in,uint4 *out)
{
	__shared__ uint4 sh[4];
#pragma nv_diag_suppress static_var_with_dynamic_init
	__shared__ cuda::barrier<cuda::thread_scope_block> barrier;
	int32_t i;
	if ( blockIdx.x != 0 || threadIdx.x != 0 )
		return;
	init(&barrier,(uint32_t)1);
	cuda::device::barrier_expect_tx(barrier,(ptrdiff_t)(4 * (int32_t)sizeof(uint4)));
	cuda::device::memcpy_async_tx(sh,in,cuda::aligned_size_t<16>((size_t)(4 * (int32_t)sizeof(uint4))),barrier);
	barrier.arrive_and_wait();
	for (i=0; i<4; i++)
		out[i] = sh[i];
}

int main(int argc,char **argv)
{
	uint4 *d_in = 0,*d_out = 0;
	uint4 h_in[4],h_out[4];
	int32_t rc = 0,i;
	(void)argc;
	(void)argv;
	cuda_probe_print_versions();
	for (i=0; i<4; i++)
	{
		h_in[i] = make_uint4((uint32_t)(0x11111111u + (uint32_t)i),(uint32_t)(0x22222222u + (uint32_t)i),(uint32_t)(0x33333333u + (uint32_t)i),(uint32_t)(0x44444444u + (uint32_t)i));
		h_out[i] = make_uint4(0,0,0,0);
	}
	rc = cuda_probe_check(cudaMalloc((void **)&d_in,(size_t)(4 * (int32_t)sizeof(uint4))),-1,"cudaMalloc(d_in)");
	if ( rc != 0 )
		return(rc);
	rc = cuda_probe_check(cudaMalloc((void **)&d_out,(size_t)(4 * (int32_t)sizeof(uint4))),-2,"cudaMalloc(d_out)");
	if ( rc != 0 )
	{
		cudaFree(d_in);
		return(rc);
	}
	rc = cuda_probe_check(cudaMemcpy(d_in,h_in,(size_t)(4 * (int32_t)sizeof(uint4)),cudaMemcpyHostToDevice),-3,"cudaMemcpy(H2D)");
	if ( rc != 0 )
	{
		cudaFree(d_out);
		cudaFree(d_in);
		return(rc);
	}
	rc = cuda_probe_check(cudaMemset(d_out,0,(size_t)(4 * (int32_t)sizeof(uint4))),-4,"cudaMemset(d_out)");
	if ( rc != 0 )
	{
		cudaFree(d_out);
		cudaFree(d_in);
		return(rc);
	}
	cp_async_bulk_tx_u4<<<1,32>>>(d_in,d_out);
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
	rc = cuda_probe_check(cudaMemcpy(h_out,d_out,(size_t)(4 * (int32_t)sizeof(uint4)),cudaMemcpyDeviceToHost),-7,"cudaMemcpy(D2H)");
	if ( rc != 0 )
	{
		cudaFree(d_out);
		cudaFree(d_in);
		return(rc);
	}
	cudaFree(d_out);
	cudaFree(d_in);
	printf("cp_async_bulk_tx out0=%08x %08x %08x %08x\n",h_out[0].x,h_out[0].y,h_out[0].z,h_out[0].w);
	if ( (h_out[0].x != h_in[0].x) || (h_out[0].y != h_in[0].y) || (h_out[0].z != h_in[0].z) || (h_out[0].w != h_in[0].w) )
		return(-8);
	if ( (h_out[3].x != h_in[3].x) || (h_out[3].y != h_in[3].y) || (h_out[3].z != h_in[3].z) || (h_out[3].w != h_in[3].w) )
		return(-9);
	return(0);
}
