#include <stdint.h>
#include <stdio.h>

#include <cuda_fp8.h>
#include <cuda_runtime.h>

#include "cuda_probe_util.h"

typedef struct
{
	uint8_t e4m3_storage,e5m2_storage;
	uint16_t e4m3_halfraw,e5m2_halfraw;
} fp8_conv_out_t;

static __global__ void fp8_conv_kernel(fp8_conv_out_t *out,float x)
{
	__nv_fp8_storage_t e4m3,e5m2;
	__half_raw h4,h5;
	if ( out == 0 )
		return;
	e4m3 = __nv_cvt_float_to_fp8(x,__NV_SATFINITE,__NV_E4M3);
	e5m2 = __nv_cvt_float_to_fp8(x,__NV_SATFINITE,__NV_E5M2);
	h4 = __nv_cvt_fp8_to_halfraw(e4m3,__NV_E4M3);
	h5 = __nv_cvt_fp8_to_halfraw(e5m2,__NV_E5M2);
	out->e4m3_storage = (uint8_t)e4m3;
	out->e5m2_storage = (uint8_t)e5m2;
	out->e4m3_halfraw = (uint16_t)h4.x;
	out->e5m2_halfraw = (uint16_t)h5.x;
}

int main(int argc,char **argv)
{
	int32_t rc = 0;
	float x = 1.25f;
	fp8_conv_out_t host_out;
	fp8_conv_out_t *dev_out = 0;
	(void)argc;
	(void)argv;
	cuda_probe_print_versions();
	rc = cuda_probe_check(cudaMalloc((void **)&dev_out,sizeof(*dev_out)),-1,"cudaMalloc(dev_out)");
	if ( rc != 0 )
		return(rc);
	rc = cuda_probe_check(cudaMemset(dev_out,0,sizeof(*dev_out)),-2,"cudaMemset(dev_out)");
	if ( rc != 0 )
		return(rc);
	fp8_conv_kernel<<<1,1>>>(dev_out,x);
	rc = cuda_probe_check(cudaGetLastError(),-3,"fp8_conv_kernel launch");
	if ( rc != 0 )
		return(rc);
	rc = cuda_probe_check(cudaDeviceSynchronize(),-4,"cudaDeviceSynchronize");
	if ( rc != 0 )
		return(rc);
	rc = cuda_probe_check(cudaMemcpy(&host_out,dev_out,sizeof(host_out),cudaMemcpyDeviceToHost),-5,"cudaMemcpy(dev_out->host)");
	if ( rc != 0 )
		return(rc);
	printf("fp8_conv x=%f e4m3=0x%02x e5m2=0x%02x halfraw_e4m3=0x%04x halfraw_e5m2=0x%04x\n",x,host_out.e4m3_storage,host_out.e5m2_storage,host_out.e4m3_halfraw,host_out.e5m2_halfraw);
	rc = cuda_probe_check(cudaFree(dev_out),-6,"cudaFree(dev_out)");
	if ( rc != 0 )
		return(rc);
	return(0);
}

