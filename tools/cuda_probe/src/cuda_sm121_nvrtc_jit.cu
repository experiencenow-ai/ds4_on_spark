#include <stdint.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>

#include <cuda.h>
#include <nvrtc.h>

static inline int32_t nvrtc_check(nvrtcResult r,int32_t code,const char *callsite)
{
	if ( r == NVRTC_SUCCESS )
		return(0);
	fprintf(stderr,"NVRTC error %s: %s\n",callsite,nvrtcGetErrorString(r));
	return(code);
}

static inline int32_t cu_check(CUresult r,int32_t code,const char *callsite)
{
	const char *name = 0,*str = 0;
	if ( r == CUDA_SUCCESS )
		return(0);
	cuGetErrorName(r,&name);
	cuGetErrorString(r,&str);
	fprintf(stderr,"CU error %s: %s (%s)\n",callsite,(name != 0) ? name : "unknown",(str != 0) ? str : "");
	return(code);
}

int main(int argc,char **argv)
{
	static const char *src =
	"extern \"C\" __global__ void nvrtc_add1_u32(unsigned int *out)\n"
	"{\n"
	"    int i = (int)threadIdx.x + ((int)blockIdx.x * (int)blockDim.x);\n"
	"    if ( i == 0 ) out[0] = 0x12345678u + 1u;\n"
	"}\n";
	const char *opts[8];
	char ptx_header[160];
	nvrtcProgram prog = 0;
	size_t ptx_size = 0,log_size = 0;
	char *ptx = 0,*log = 0;
	int32_t major = 0,minor = 0,num_opts = 0,rc = 0;
	int32_t driver_v = 0;
	int32_t num_arch = 0,i = 0;
	int32_t *archs = 0;
	CUdevice dev = 0;
	CUcontext ctx = 0;
	CUmodule mod = 0;
	CUfunction fn = 0;
	CUdeviceptr d_out = 0;
	uint32_t out = 0;
	(void)argc;
	(void)argv;

	nvrtcVersion(&major,&minor);
	printf("nvrtcVersion=%d.%d\n",major,minor);
	rc = nvrtc_check(nvrtcGetNumSupportedArchs(&num_arch),-1,"nvrtcGetNumSupportedArchs");
	if ( rc != 0 )
		return(rc);
	archs = (int32_t *)malloc((size_t)num_arch * sizeof(int32_t));
	if ( archs != 0 )
	{
		rc = nvrtc_check(nvrtcGetSupportedArchs((int *)archs),-2,"nvrtcGetSupportedArchs");
		if ( rc == 0 )
		{
			printf("nvrtc supportedArchs:");
			for (i=0; i<num_arch; i++)
				printf(" %d",archs[i]);
			printf("\n");
		}
		free(archs);
	}

	opts[num_opts++] = "--std=c++17";
	opts[num_opts++] = "--gpu-architecture=compute_121";
	opts[num_opts++] = "--fmad=false";

	rc = nvrtc_check(nvrtcCreateProgram(&prog,src,"cuda_sm121_nvrtc_jit.cu",0,0,0),-3,"nvrtcCreateProgram");
	if ( rc != 0 )
		return(rc);
	rc = nvrtc_check(nvrtcCompileProgram(prog,num_opts,opts),-4,"nvrtcCompileProgram");
	(void)nvrtcGetProgramLogSize(prog,&log_size);
	if ( log_size > 1 )
	{
		log = (char *)malloc(log_size);
		if ( log != 0 )
		{
			(void)nvrtcGetProgramLog(prog,log);
			printf("nvrtc log:\n%s\n",log);
			free(log);
		}
	}
	if ( rc != 0 )
	{
		nvrtcDestroyProgram(&prog);
		return(rc);
	}

	rc = nvrtc_check(nvrtcGetPTXSize(prog,&ptx_size),-5,"nvrtcGetPTXSize");
	if ( rc != 0 )
	{
		nvrtcDestroyProgram(&prog);
		return(rc);
	}
	ptx = (char *)malloc(ptx_size);
	if ( ptx == 0 )
	{
		nvrtcDestroyProgram(&prog);
		return(-6);
	}
	rc = nvrtc_check(nvrtcGetPTX(prog,ptx),-7,"nvrtcGetPTX");
	nvrtcDestroyProgram(&prog);
	if ( rc != 0 )
	{
		free(ptx);
		return(rc);
	}

	memset(ptx_header,0,sizeof(ptx_header));
	memcpy(ptx_header,ptx,(ptx_size < (sizeof(ptx_header) - 1)) ? ptx_size : (sizeof(ptx_header) - 1));
	printf("nvrtc ptx bytes=%zu head=%.80s\n",ptx_size,ptx_header);

	rc = cu_check(cuInit(0),-8,"cuInit");
	if ( rc != 0 )
	{
		free(ptx);
		return(rc);
	}
	rc = cu_check(cuDriverGetVersion(&driver_v),-9,"cuDriverGetVersion");
	if ( rc != 0 )
	{
		free(ptx);
		return(rc);
	}
	printf("cuDriverGetVersion=%d\n",driver_v);
	rc = cu_check(cuDeviceGet(&dev,0),-10,"cuDeviceGet(0)");
	if ( rc != 0 )
	{
		free(ptx);
		return(rc);
	}
	rc = cu_check(cuCtxCreate(&ctx,0,0,dev),-11,"cuCtxCreate");
	if ( rc != 0 )
	{
		free(ptx);
		return(rc);
	}
	rc = cu_check(cuModuleLoadDataEx(&mod,ptx,0,0,0),-12,"cuModuleLoadDataEx");
	free(ptx);
	if ( rc != 0 )
	{
		cuCtxDestroy(ctx);
		return(rc);
	}
	rc = cu_check(cuModuleGetFunction(&fn,mod,"nvrtc_add1_u32"),-13,"cuModuleGetFunction");
	if ( rc != 0 )
	{
		cuModuleUnload(mod);
		cuCtxDestroy(ctx);
		return(rc);
	}
	rc = cu_check(cuMemAlloc(&d_out,(size_t)sizeof(uint32_t)),-14,"cuMemAlloc(d_out)");
	if ( rc != 0 )
	{
		cuModuleUnload(mod);
		cuCtxDestroy(ctx);
		return(rc);
	}
	rc = cu_check(cuMemsetD32(d_out,0,1),-15,"cuMemsetD32");
	if ( rc != 0 )
	{
		cuMemFree(d_out);
		cuModuleUnload(mod);
		cuCtxDestroy(ctx);
		return(rc);
	}

	{
		void *args[] = {&d_out};
		rc = cu_check(cuLaunchKernel(fn,1,1,1,32,1,1,0,0,args,0),-16,"cuLaunchKernel");
		if ( rc != 0 )
		{
			cuMemFree(d_out);
			cuModuleUnload(mod);
			cuCtxDestroy(ctx);
			return(rc);
		}
	}
	rc = cu_check(cuCtxSynchronize(),-17,"cuCtxSynchronize");
	if ( rc != 0 )
	{
		cuMemFree(d_out);
		cuModuleUnload(mod);
		cuCtxDestroy(ctx);
		return(rc);
	}
	rc = cu_check(cuMemcpyDtoH(&out,d_out,(size_t)sizeof(uint32_t)),-18,"cuMemcpyDtoH");
	cuMemFree(d_out);
	cuModuleUnload(mod);
	cuCtxDestroy(ctx);
	if ( rc != 0 )
		return(rc);

	printf("nvrtc_jit ok out=0x%08x\n",out);
	return(0);
}
