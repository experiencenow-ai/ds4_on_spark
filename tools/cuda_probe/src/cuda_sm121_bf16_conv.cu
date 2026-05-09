#include <stdint.h>
#include <stdio.h>

#include <cuda_bf16.h>
#include <cuda_runtime.h>

#include "cuda_probe_util.h"

typedef struct
{
	uint16_t x_raw,y_raw;
	float x_back,y_back;
	float2 v_back;
} bf16_conv_out_t;

static __global__ void bf16_conv_kernel(bf16_conv_out_t *out,float x,float y)
{
	__nv_bfloat16 bx,by;
	__nv_bfloat162 v;
	if ( out == 0 )
		return;
	bx = __float2bfloat16_rn(x);
	by = __float2bfloat16_rn(y);
	out->x_raw = (uint16_t)__bfloat16_as_ushort(bx);
	out->y_raw = (uint16_t)__bfloat16_as_ushort(by);
	out->x_back = __bfloat162float(bx);
	out->y_back = __bfloat162float(by);
	v = __floats2bfloat162_rn(x,y);
	out->v_back = __bfloat1622float2(v);
}

int main(int argc,char **argv)
{
	int32_t rc = 0;
	float x = 1.25f,y = -2.5f;
	bf16_conv_out_t host_out;
	bf16_conv_out_t *dev_out = 0;
	(void)argc;
	(void)argv;
	cuda_probe_print_versions();
	rc = cuda_probe_check(cudaMalloc((void **)&dev_out,sizeof(*dev_out)),-1,"cudaMalloc(dev_out)");
	if ( rc != 0 )
		return(rc);
	rc = cuda_probe_check(cudaMemset(dev_out,0,sizeof(*dev_out)),-2,"cudaMemset(dev_out)");
	if ( rc != 0 )
		return(rc);
	bf16_conv_kernel<<<1,1>>>(dev_out,x,y);
	rc = cuda_probe_check(cudaGetLastError(),-3,"bf16_conv_kernel launch");
	if ( rc != 0 )
		return(rc);
	rc = cuda_probe_check(cudaDeviceSynchronize(),-4,"cudaDeviceSynchronize");
	if ( rc != 0 )
		return(rc);
	rc = cuda_probe_check(cudaMemcpy(&host_out,dev_out,sizeof(host_out),cudaMemcpyDeviceToHost),-5,"cudaMemcpy(dev_out->host)");
	if ( rc != 0 )
		return(rc);
	printf("bf16_conv x=%f raw_x=0x%04x x_back=%f y=%f raw_y=0x%04x y_back=%f v_back=(%f,%f)\n",x,host_out.x_raw,host_out.x_back,y,host_out.y_raw,host_out.y_back,host_out.v_back.x,host_out.v_back.y);
	rc = cuda_probe_check(cudaFree(dev_out),-6,"cudaFree(dev_out)");
	if ( rc != 0 )
		return(rc);
	return(0);
}

