#include <stdint.h>
#include <stdio.h>

#include <cuda_fp16.h>
#include <cuda_runtime.h>
#include <mma.h>

#include "cuda_probe_util.h"

static __global__ void wmma_smoke_kernel(const half *A,const half *B,float *C)
{
	nvcuda::wmma::fragment<nvcuda::wmma::matrix_a,16,16,16,half,nvcuda::wmma::row_major> a_frag;
	nvcuda::wmma::fragment<nvcuda::wmma::matrix_b,16,16,16,half,nvcuda::wmma::col_major> b_frag;
	nvcuda::wmma::fragment<nvcuda::wmma::accumulator,16,16,16,float> c_frag;
	if ( A == 0 || B == 0 || C == 0 )
		return;
	if ( blockIdx.x != 0 || threadIdx.x >= 32 )
		return;
	nvcuda::wmma::load_matrix_sync(a_frag,A,16);
	nvcuda::wmma::load_matrix_sync(b_frag,B,16);
	nvcuda::wmma::fill_fragment(c_frag,0.0f);
	nvcuda::wmma::mma_sync(c_frag,a_frag,b_frag,c_frag);
	nvcuda::wmma::store_matrix_sync(C,c_frag,16,nvcuda::wmma::mem_row_major);
}

int main(int argc,char **argv)
{
	half *d_A = 0,*d_B = 0;
	float *d_C = 0;
	half h_A[16 * 16],h_B[16 * 16];
	float h_C[16 * 16];
	int32_t i = 0,rc = 0;
	float max_abs_err = 0.0f;
	(void)argc;
	(void)argv;
	cuda_probe_print_versions();
	for (i=0; i<16*16; i++)
	{
		h_A[i] = __float2half_rn(1.0f);
		h_B[i] = __float2half_rn(1.0f);
		h_C[i] = 0.0f;
	}
	rc = cuda_probe_check(cudaMalloc((void **)&d_A,(size_t)sizeof(h_A)),-1,"cudaMalloc(d_A)");
	if ( rc != 0 )
		return(rc);
	rc = cuda_probe_check(cudaMalloc((void **)&d_B,(size_t)sizeof(h_B)),-2,"cudaMalloc(d_B)");
	if ( rc != 0 )
	{
		cudaFree(d_A);
		return(rc);
	}
	rc = cuda_probe_check(cudaMalloc((void **)&d_C,(size_t)sizeof(h_C)),-3,"cudaMalloc(d_C)");
	if ( rc != 0 )
	{
		cudaFree(d_B);
		cudaFree(d_A);
		return(rc);
	}
	rc = cuda_probe_check(cudaMemcpy(d_A,h_A,(size_t)sizeof(h_A),cudaMemcpyHostToDevice),-4,"cudaMemcpy(d_A H2D)");
	if ( rc != 0 )
	{
		cudaFree(d_C);
		cudaFree(d_B);
		cudaFree(d_A);
		return(rc);
	}
	rc = cuda_probe_check(cudaMemcpy(d_B,h_B,(size_t)sizeof(h_B),cudaMemcpyHostToDevice),-5,"cudaMemcpy(d_B H2D)");
	if ( rc != 0 )
	{
		cudaFree(d_C);
		cudaFree(d_B);
		cudaFree(d_A);
		return(rc);
	}
	rc = cuda_probe_check(cudaMemset(d_C,0,(size_t)sizeof(h_C)),-6,"cudaMemset(d_C)");
	if ( rc != 0 )
	{
		cudaFree(d_C);
		cudaFree(d_B);
		cudaFree(d_A);
		return(rc);
	}
	wmma_smoke_kernel<<<1,32>>>(d_A,d_B,d_C);
	rc = cuda_probe_check(cudaGetLastError(),-7,"wmma_smoke_kernel launch");
	if ( rc != 0 )
	{
		cudaFree(d_C);
		cudaFree(d_B);
		cudaFree(d_A);
		return(rc);
	}
	rc = cuda_probe_check(cudaDeviceSynchronize(),-8,"cudaDeviceSynchronize");
	if ( rc != 0 )
	{
		cudaFree(d_C);
		cudaFree(d_B);
		cudaFree(d_A);
		return(rc);
	}
	rc = cuda_probe_check(cudaMemcpy(h_C,d_C,(size_t)sizeof(h_C),cudaMemcpyDeviceToHost),-9,"cudaMemcpy(d_C D2H)");
	if ( rc != 0 )
	{
		cudaFree(d_C);
		cudaFree(d_B);
		cudaFree(d_A);
		return(rc);
	}
	for (i=0; i<16*16; i++)
	{
		float err = h_C[i] - 16.0f;
		if ( err < 0.0f )
			err = -err;
		if ( err > max_abs_err )
			max_abs_err = err;
	}
	printf("wmma_smoke C00=%f C255=%f max_abs_err=%f\n",h_C[0],h_C[(16*16)-1],max_abs_err);
	if ( max_abs_err > 0.001f )
		rc = -10;
	cudaFree(d_C);
	cudaFree(d_B);
	cudaFree(d_A);
	return(rc);
}
