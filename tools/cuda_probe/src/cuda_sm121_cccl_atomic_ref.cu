#include <stdint.h>
#include <stdio.h>

#include <cuda/atomic>
#include <cuda_runtime.h>

#include "cuda_probe_util.h"

__global__ void cccl_atomic_ref_device_add(uint32_t *counter)
{
	cuda::atomic_ref<uint32_t,cuda::thread_scope_device> a(*counter);
	a.fetch_add(1u,cuda::memory_order_relaxed);
}

__global__ void cccl_atomic_ref_block_add(uint32_t *out)
{
	__shared__ uint32_t counter;
	cuda::atomic_ref<uint32_t,cuda::thread_scope_block> a(counter);
	if ( threadIdx.x == 0 )
		counter = 0;
	__syncthreads();
	a.fetch_add(1u,cuda::memory_order_relaxed);
	__syncthreads();
	if ( threadIdx.x == 0 )
		out[0] = counter;
}

int main(int argc,char **argv)
{
	uint32_t *d_counter = 0,*d_out = 0;
	uint32_t h_counter = 0,h_out = 0;
	int32_t rc = 0;
	(void)argc;
	(void)argv;
	cuda_probe_print_versions();
	rc = cuda_probe_check(cudaMalloc((void **)&d_counter,(size_t)sizeof(uint32_t)),-1,"cudaMalloc(d_counter)");
	if ( rc != 0 )
		return(rc);
	rc = cuda_probe_check(cudaMalloc((void **)&d_out,(size_t)sizeof(uint32_t)),-2,"cudaMalloc(d_out)");
	if ( rc != 0 )
	{
		cudaFree(d_counter);
		return(rc);
	}
	rc = cuda_probe_check(cudaMemset(d_counter,0,(size_t)sizeof(uint32_t)),-3,"cudaMemset(d_counter)");
	if ( rc != 0 )
	{
		cudaFree(d_out);
		cudaFree(d_counter);
		return(rc);
	}
	rc = cuda_probe_check(cudaMemset(d_out,0,(size_t)sizeof(uint32_t)),-4,"cudaMemset(d_out)");
	if ( rc != 0 )
	{
		cudaFree(d_out);
		cudaFree(d_counter);
		return(rc);
	}

	cccl_atomic_ref_device_add<<<32,256>>>(d_counter);
	rc = cuda_probe_check(cudaGetLastError(),-5,"device atomic_ref kernel launch");
	if ( rc != 0 )
	{
		cudaFree(d_out);
		cudaFree(d_counter);
		return(rc);
	}
	cccl_atomic_ref_block_add<<<1,256>>>(d_out);
	rc = cuda_probe_check(cudaGetLastError(),-6,"block atomic_ref kernel launch");
	if ( rc != 0 )
	{
		cudaFree(d_out);
		cudaFree(d_counter);
		return(rc);
	}
	rc = cuda_probe_check(cudaDeviceSynchronize(),-7,"cudaDeviceSynchronize");
	if ( rc != 0 )
	{
		cudaFree(d_out);
		cudaFree(d_counter);
		return(rc);
	}
	rc = cuda_probe_check(cudaMemcpy(&h_counter,d_counter,(size_t)sizeof(uint32_t),cudaMemcpyDeviceToHost),-8,"cudaMemcpy(d_counter D2H)");
	if ( rc != 0 )
	{
		cudaFree(d_out);
		cudaFree(d_counter);
		return(rc);
	}
	rc = cuda_probe_check(cudaMemcpy(&h_out,d_out,(size_t)sizeof(uint32_t),cudaMemcpyDeviceToHost),-9,"cudaMemcpy(d_out D2H)");
	if ( rc != 0 )
	{
		cudaFree(d_out);
		cudaFree(d_counter);
		return(rc);
	}
	cudaFree(d_out);
	cudaFree(d_counter);

	if ( h_counter != (32u * 256u) )
	{
		fprintf(stderr,"cccl_atomic_ref device mismatch got=%u want=%u\n",h_counter,(32u * 256u));
		return(-10);
	}
	if ( h_out != 256u )
	{
		fprintf(stderr,"cccl_atomic_ref block mismatch got=%u want=%u\n",h_out,256u);
		return(-11);
	}
	printf("cccl_atomic_ref ok device=%u block=%u\n",h_counter,h_out);
	return(0);
}
