#include <stdint.h>
#include <stdio.h>

#include <cuda_runtime.h>

#include "cuda_probe_util.h"

__device__ __constant__ uint32_t ds4_sm121_arch_report_arch =
#if defined(__CUDA_ARCH__)
	(uint32_t)__CUDA_ARCH__;
#else
	0U;
#endif

__global__ void write_arch_report(uint32_t *out)
{
	int32_t tid = ((int32_t)threadIdx.x) + (((int32_t)blockIdx.x) * ((int32_t)blockDim.x));
	if ( tid == 0 )
	{
		out[0] = 0xC0D3CAFEu;
#if defined(__CUDA_ARCH__)
		out[1] = (uint32_t)__CUDA_ARCH__;
#else
		out[1] = 0;
#endif
	}
}

int main(int argc,char **argv)
{
	uint32_t *d_out = 0,h_out[2] = {0,0},const_arch = 0;
	cudaDeviceProp prop;
	int32_t rc = 0;
	(void)argc;
	(void)argv;
	cuda_probe_print_versions();
	rc = cuda_probe_check(cudaGetDeviceProperties(&prop,0),-1,"cudaGetDeviceProperties(0)");
	if ( rc != 0 )
		return(rc);
	printf("device[0]=%s cc=%d.%d\n",prop.name,prop.major,prop.minor);
	if ( cudaMemcpyFromSymbol(&const_arch,ds4_sm121_arch_report_arch,sizeof(const_arch),0,cudaMemcpyDeviceToHost) == cudaSuccess )
	{
		h_out[0] = 0xC0D3CAFEu;
		h_out[1] = const_arch;
	}
	else
	{
		rc = cuda_probe_check(cudaMalloc((void **)&d_out,(size_t)(2U * sizeof(uint32_t))),-2,"cudaMalloc");
		if ( rc != 0 )
			return(rc);
		rc = cuda_probe_check(cudaMemset(d_out,0,(size_t)(2U * sizeof(uint32_t))),-3,"cudaMemset");
		if ( rc != 0 )
		{
			cudaFree(d_out);
			return(rc);
		}
		write_arch_report<<<1,32>>>(d_out);
		rc = cuda_probe_check(cudaGetLastError(),-4,"kernel launch");
		if ( rc != 0 )
		{
			cudaFree(d_out);
			return(rc);
		}
		rc = cuda_probe_check(cudaDeviceSynchronize(),-5,"cudaDeviceSynchronize");
		if ( rc != 0 )
		{
			cudaFree(d_out);
			return(rc);
		}
		rc = cuda_probe_check(cudaMemcpy(&h_out[0],d_out,(size_t)(2U * sizeof(uint32_t)),cudaMemcpyDeviceToHost),-6,"cudaMemcpy(D2H)");
		if ( rc != 0 )
		{
			cudaFree(d_out);
			return(rc);
		}
		cudaFree(d_out);
	}
	printf("kernel wrote magic=0x%08x __CUDA_ARCH__=%u\n",h_out[0],h_out[1]);
	if ( h_out[0] != 0xC0D3CAFEu )
		return(-7);
	if ( h_out[1] == 0 )
		return(-8);
	if ( h_out[1] != 1210U )
		return(-9);
	return(0);
}
