#include <stdint.h>
#include <stdio.h>

#include <cuda_runtime.h>

#include "cuda_probe_util.h"

static __global__ void ldmatrix_smoke_kernel(uint32_t *out)
{
	__shared__ __align__(16) uint16_t smem[64];
	int32_t tid = (int32_t)threadIdx.x;
	if ( out == 0 )
		return;
	if ( tid < 64 )
		smem[tid] = (uint16_t)(tid + 1);
	__syncthreads();
	if ( tid >= 32 )
		return;
	uint32_t r0 = 0,r1 = 0,r2 = 0,r3 = 0;
	uint64_t smem_addr = 0,smem_ptr = (uint64_t)(uintptr_t)smem;
	asm volatile("cvta.to.shared.u64 %0, %1;" : "=l"(smem_addr) : "l"(smem_ptr));
	asm volatile("ldmatrix.sync.aligned.m8n8.x4.shared.b16 {%0,%1,%2,%3}, [%4];" : "=r"(r0), "=r"(r1), "=r"(r2), "=r"(r3) : "l"(smem_addr));
	out[(tid * 4) + 0] = r0;
	out[(tid * 4) + 1] = r1;
	out[(tid * 4) + 2] = r2;
	out[(tid * 4) + 3] = r3;
}

int main(int argc,char **argv)
{
	uint32_t *d_out = 0;
	uint32_t h_out[32 * 4];
	int32_t i = 0,rc = 0,nonzero = 0;
	(void)argc;
	(void)argv;
	cuda_probe_print_versions();
	for (i=0; i<(int32_t)(sizeof(h_out) / sizeof(h_out[0])); i++)
		h_out[i] = 0;
	rc = cuda_probe_check(cudaMalloc((void **)&d_out,(size_t)sizeof(h_out)),-1,"cudaMalloc(d_out)");
	if ( rc != 0 )
		return(rc);
	rc = cuda_probe_check(cudaMemset(d_out,0,(size_t)sizeof(h_out)),-2,"cudaMemset(d_out)");
	if ( rc != 0 )
	{
		cudaFree(d_out);
		return(rc);
	}
	ldmatrix_smoke_kernel<<<1,32>>>(d_out);
	rc = cuda_probe_check(cudaGetLastError(),-3,"ldmatrix_smoke_kernel launch");
	if ( rc != 0 )
	{
		cudaFree(d_out);
		return(rc);
	}
	rc = cuda_probe_check(cudaDeviceSynchronize(),-4,"cudaDeviceSynchronize");
	if ( rc != 0 )
	{
		cudaFree(d_out);
		return(rc);
	}
	rc = cuda_probe_check(cudaMemcpy(h_out,d_out,(size_t)sizeof(h_out),cudaMemcpyDeviceToHost),-5,"cudaMemcpy(d_out D2H)");
	if ( rc != 0 )
	{
		cudaFree(d_out);
		return(rc);
	}
	for (i=0; i<(int32_t)(sizeof(h_out) / sizeof(h_out[0])); i++)
	{
		if ( h_out[i] != 0 )
			nonzero++;
	}
	printf("ldmatrix_smoke nonzero=%d out0=%08x out127=%08x\n",nonzero,h_out[0],h_out[(int32_t)(sizeof(h_out) / sizeof(h_out[0])) - 1]);
	if ( nonzero <= 0 )
		rc = -6;
	cudaFree(d_out);
	return(rc);
}
