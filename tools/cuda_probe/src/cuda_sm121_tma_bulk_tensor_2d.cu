#include <stdint.h>
#include <stddef.h>
#include <stdio.h>

#include <cuda.h>
#include <cuda/__barrier/barrier_expect_tx.h>
#include <cuda/barrier>
#include <cuda_runtime.h>

#include "cuda_probe_util.h"

__global__ void tma_bulk_tensor_2d_u8(const CUtensorMap *tensor_map,uint8_t *out)
{
	__shared__ __align__(128) uint8_t sh[128];
#pragma nv_diag_suppress static_var_with_dynamic_init
	__shared__ cuda::barrier<cuda::thread_scope_block> barrier;
	int32_t i;
	if ( blockIdx.x != 0 || threadIdx.x != 0 )
		return;
	init(&barrier,(uint32_t)1);
	cuda::device::experimental::fence_proxy_async_shared_cta();
	cuda::device::barrier_expect_tx(barrier,(ptrdiff_t)128);
	cuda::device::experimental::cp_async_bulk_tensor_2d_global_to_shared(sh,tensor_map,0,0,barrier);
	barrier.arrive_and_wait();
	for (i=0; i<128; i++)
		out[i] = sh[i];
}

static int32_t encode_tensor_map_2d_u8(CUtensorMap *out,void *global_addr,uint32_t dim0,uint32_t dim1)
{
	CUresult res;
	cuuint64_t global_dim[2],global_strides[1];
	cuuint32_t box_dim[2],element_strides[2];
	if ( out == 0 || global_addr == 0 )
		return(-1001);
	if ( dim0 == 0 || dim1 == 0 )
		return(-1002);
	global_dim[0] = (cuuint64_t)dim0;
	global_dim[1] = (cuuint64_t)dim1;
	global_strides[0] = (cuuint64_t)dim0;
	box_dim[0] = dim0;
	box_dim[1] = dim1;
	element_strides[0] = 1;
	element_strides[1] = 1;
	res = cuTensorMapEncodeTiled(out,CU_TENSOR_MAP_DATA_TYPE_UINT8,(cuuint32_t)2,global_addr,global_dim,global_strides,box_dim,element_strides,CU_TENSOR_MAP_INTERLEAVE_NONE,CU_TENSOR_MAP_SWIZZLE_NONE,CU_TENSOR_MAP_L2_PROMOTION_NONE,CU_TENSOR_MAP_FLOAT_OOB_FILL_NONE);
	if ( res != CUDA_SUCCESS )
	{
		fprintf(stderr,"cuTensorMapEncodeTiled failed: %d\n",(int32_t)res);
		return(-1003);
	}
	return(0);
}

static int32_t memeq_u8(const uint8_t *a,const uint8_t *b,int32_t n)
{
	int32_t i;
	if ( a == 0 || b == 0 )
		return(-2001);
	if ( n < 0 )
		return(-2002);
	for (i=0; i<n; i++)
	{
		if ( a[i] != b[i] )
			return(-2003);
	}
	return(0);
}

int main(int argc,char **argv)
{
	static const int32_t n = 128;
	static const uint32_t dim0 = 16,dim1 = 8;
	alignas(128) CUtensorMap h_map;
	uint8_t h_in[n],h_out[n];
	uint8_t *d_in = 0,*d_out = 0;
	CUtensorMap *d_map = 0;
	CUresult cres;
	int32_t rc = 0,i;
	(void)argc;
	(void)argv;
	cuda_probe_print_versions();
	cres = cuInit(0);
	if ( cres != CUDA_SUCCESS )
	{
		fprintf(stderr,"cuInit failed: %d\n",(int32_t)cres);
		return(-1);
	}
	for (i=0; i<n; i++)
	{
		h_in[i] = (uint8_t)i;
		h_out[i] = 0;
	}
	rc = cuda_probe_check(cudaMalloc((void **)&d_in,(size_t)n),-2,"cudaMalloc(d_in)");
	if ( rc != 0 )
		return(rc);
	rc = cuda_probe_check(cudaMalloc((void **)&d_out,(size_t)n),-3,"cudaMalloc(d_out)");
	if ( rc != 0 )
	{
		cudaFree(d_in);
		return(rc);
	}
	rc = cuda_probe_check(cudaMalloc((void **)&d_map,(size_t)sizeof(*d_map)),-4,"cudaMalloc(d_map)");
	if ( rc != 0 )
	{
		cudaFree(d_out);
		cudaFree(d_in);
		return(rc);
	}
	rc = cuda_probe_check(cudaMemcpy(d_in,h_in,(size_t)n,cudaMemcpyHostToDevice),-5,"cudaMemcpy(H2D in)");
	if ( rc != 0 )
	{
		cudaFree(d_map);
		cudaFree(d_out);
		cudaFree(d_in);
		return(rc);
	}
	rc = cuda_probe_check(cudaMemset(d_out,0,(size_t)n),-6,"cudaMemset(d_out)");
	if ( rc != 0 )
	{
		cudaFree(d_map);
		cudaFree(d_out);
		cudaFree(d_in);
		return(rc);
	}
	rc = encode_tensor_map_2d_u8(&h_map,(void *)d_in,dim0,dim1);
	if ( rc != 0 )
	{
		cudaFree(d_map);
		cudaFree(d_out);
		cudaFree(d_in);
		return(rc);
	}
	rc = cuda_probe_check(cudaMemcpy(d_map,&h_map,(size_t)sizeof(h_map),cudaMemcpyHostToDevice),-7,"cudaMemcpy(H2D map)");
	if ( rc != 0 )
	{
		cudaFree(d_map);
		cudaFree(d_out);
		cudaFree(d_in);
		return(rc);
	}
	tma_bulk_tensor_2d_u8<<<1,32>>>(d_map,d_out);
	rc = cuda_probe_check(cudaGetLastError(),-8,"kernel launch");
	if ( rc != 0 )
	{
		cudaFree(d_map);
		cudaFree(d_out);
		cudaFree(d_in);
		return(rc);
	}
	rc = cuda_probe_check(cudaDeviceSynchronize(),-9,"cudaDeviceSynchronize");
	if ( rc != 0 )
	{
		cudaFree(d_map);
		cudaFree(d_out);
		cudaFree(d_in);
		return(rc);
	}
	rc = cuda_probe_check(cudaMemcpy(h_out,d_out,(size_t)n,cudaMemcpyDeviceToHost),-10,"cudaMemcpy(D2H out)");
	if ( rc != 0 )
	{
		cudaFree(d_map);
		cudaFree(d_out);
		cudaFree(d_in);
		return(rc);
	}
	cudaFree(d_map);
	cudaFree(d_out);
	cudaFree(d_in);
	rc = memeq_u8(h_in,h_out,n);
	printf("tma_bulk_tensor_2d rc=%d out0=%02x out127=%02x\n",rc,h_out[0],h_out[127]);
	if ( rc != 0 )
		return(-11);
	return(0);
}
