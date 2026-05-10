#include <stdint.h>
#include <stdio.h>

#include <cuda_fp4.h>
#include <cuda_runtime.h>

#include "cuda_probe_util.h"

typedef struct
{
	uint8_t fp4_storage;
	uint16_t halfraw_e2m1;
} fp4_conv_out_t;

static __global__ void fp4_conv_kernel(fp4_conv_out_t *out,float x)
{
	__nv_fp4_storage_t e2m1;
	__half_raw hr;
	if ( out == 0 )
		return;
	e2m1 = __nv_cvt_float_to_fp4(x,__NV_E2M1,cudaRoundNearest);
	hr = __nv_cvt_fp4_to_halfraw(e2m1,__NV_E2M1);
	out->fp4_storage = (uint8_t)e2m1;
	out->halfraw_e2m1 = (uint16_t)hr.x;
}

int main(int argc,char **argv)
{
	int32_t rc = 0;
	float x = 1.25f;
	fp4_conv_out_t host_out;
	fp4_conv_out_t *dev_out = 0;
	(void)argc;
	(void)argv;
	cuda_probe_print_versions();
	do
	{
		rc = cuda_probe_check(cudaMalloc((void **)&dev_out,sizeof(*dev_out)),-1,"cudaMalloc(dev_out)");
		if ( rc != 0 )
			break;
		rc = cuda_probe_check(cudaMemset(dev_out,0,sizeof(*dev_out)),-2,"cudaMemset(dev_out)");
		if ( rc != 0 )
			break;
		fp4_conv_kernel<<<1,1>>>(dev_out,x);
		rc = cuda_probe_check(cudaGetLastError(),-3,"fp4_conv_kernel launch");
		if ( rc != 0 )
			break;
		rc = cuda_probe_check(cudaDeviceSynchronize(),-4,"cudaDeviceSynchronize");
		if ( rc != 0 )
			break;
		rc = cuda_probe_check(cudaMemcpy(&host_out,dev_out,sizeof(host_out),cudaMemcpyDeviceToHost),-5,"cudaMemcpy(dev_out->host)");
		if ( rc != 0 )
			break;
	} while (0);
	if ( dev_out != 0 )
		cudaFree(dev_out);
	if ( rc != 0 )
		return(rc);
	printf("fp4_conv x=%f e2m1_storage=0x%02x e2m1_nibble=0x%01x halfraw_e2m1=0x%04x\n",x,host_out.fp4_storage,(uint32_t)(host_out.fp4_storage & 0x0fu),host_out.halfraw_e2m1);
	return(0);
}
