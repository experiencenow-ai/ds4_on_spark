#include <stdint.h>
#include <stdio.h>

#include <cuda_runtime.h>

#include "cuda_probe_util.h"

static int32_t get_attr_i32(int32_t *out,int32_t dev,cudaDeviceAttr attr)
{
	int32_t v = 0;
	cudaError_t err;
	if ( out == 0 )
		return(-1001);
	err = cudaDeviceGetAttribute(&v,attr,dev);
	if ( err != cudaSuccess )
		return(-1002);
	*out = v;
	return(0);
}

static int32_t print_attr_i32(const char *name,int32_t v)
{
	if ( name == 0 )
		return(-1010);
	printf("%s=%d\n",name,v);
	return(0);
}

__global__ void smem_probe(uint32_t *out)
{
	extern __shared__ uint8_t smem[];
	int32_t tid = (int32_t)threadIdx.x;
	if ( tid == 0 )
	{
		smem[0] = 0xA5;
		out[0] = (uint32_t)smem[0];
	}
}

static int32_t run_smem_optin(int32_t dev)
{
	int32_t optin_max = 0,rc = 0;
	uint32_t *d_out = 0,h_out = 0;
	rc = get_attr_i32(&optin_max,dev,cudaDevAttrMaxSharedMemoryPerBlockOptin);
	if ( rc != 0 )
		return(-2001);
	print_attr_i32("max_smem_per_block_optin_bytes",optin_max);
	if ( optin_max <= 0 )
		return(0);
	rc = cuda_probe_check(cudaMalloc((void **)&d_out,(size_t)sizeof(uint32_t)),-2002,"cudaMalloc");
	if ( rc != 0 )
		return(rc);
	rc = cuda_probe_check(cudaMemset(d_out,0,(size_t)sizeof(uint32_t)),-2003,"cudaMemset");
	if ( rc != 0 )
	{
		cudaFree(d_out);
		return(rc);
	}
	rc = cuda_probe_check(cudaFuncSetAttribute((const void *)smem_probe,cudaFuncAttributeMaxDynamicSharedMemorySize,optin_max),-2004,"cudaFuncSetAttribute(MaxDynamicSharedMemorySize)");
	if ( rc != 0 )
	{
		cudaFree(d_out);
		return(rc);
	}
	smem_probe<<<1,32,(size_t)optin_max>>>(d_out);
	rc = cuda_probe_check(cudaGetLastError(),-2005,"kernel launch");
	if ( rc != 0 )
	{
		cudaFree(d_out);
		return(rc);
	}
	rc = cuda_probe_check(cudaDeviceSynchronize(),-2006,"cudaDeviceSynchronize");
	if ( rc != 0 )
	{
		cudaFree(d_out);
		return(rc);
	}
	rc = cuda_probe_check(cudaMemcpy(&h_out,d_out,(size_t)sizeof(uint32_t),cudaMemcpyDeviceToHost),-2007,"cudaMemcpy(D2H)");
	if ( rc != 0 )
	{
		cudaFree(d_out);
		return(rc);
	}
	cudaFree(d_out);
	printf("smem probe wrote 0x%08x\n",h_out);
	if ( h_out != 0xA5u )
		return(-2008);
	return(0);
}

int main(int argc,char **argv)
{
	int32_t count = 0,dev = 0,rc = 0;
	(void)argc;
	(void)argv;
	cuda_probe_print_versions();
	rc = cuda_probe_check(cudaGetDeviceCount(&count),-1,"cudaGetDeviceCount");
	if ( rc != 0 )
		return(rc);
	printf("cudaGetDeviceCount=%d\n",count);
	for (dev=0; dev<count; dev++)
	{
		printf("== device[%d] ==\n",dev);
		rc = cuda_probe_check(cudaSetDevice(dev),-10 - dev,"cudaSetDevice");
		if ( rc != 0 )
			return(rc);
		rc = run_smem_optin(dev);
		if ( rc != 0 )
			return(rc);
	}
	return(0);
}
