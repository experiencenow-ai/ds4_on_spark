#include <stdint.h>
#include <stdio.h>
#include <stdlib.h>

#include <cuda.h>
#include <nvJitLink.h>
#include <nvrtc.h>

#include "cuda_probe_util.h"

static inline int32_t nvrtc_check(nvrtcResult r,int32_t code,const char *callsite)
{
	if ( r == NVRTC_SUCCESS )
		return(0);
	fprintf(stderr,"NVRTC error %s: %s\n",callsite,nvrtcGetErrorString(r));
	return(code);
}

static inline int32_t nvjitlink_check(nvJitLinkResult r,int32_t code,const char *callsite,nvJitLinkHandle handle)
{
	size_t log_size = 0;
	char *log = 0;
	if ( r == NVJITLINK_SUCCESS )
		return(0);
	fprintf(stderr,"nvJitLink error %s: r=%d\n",callsite,(int32_t)r);
	if ( handle != 0 )
	{
		if ( nvJitLinkGetErrorLogSize(handle,&log_size) == NVJITLINK_SUCCESS && log_size > 1 )
		{
			log = (char *)malloc(log_size);
			if ( log != 0 )
			{
				if ( nvJitLinkGetErrorLog(handle,log) == NVJITLINK_SUCCESS )
					fprintf(stderr,"nvJitLink error log:\n%s\n",log);
				free(log);
			}
		}
	}
	return(code);
}

static inline void nvjitlink_print_info_log(nvJitLinkHandle handle)
{
	size_t log_size = 0;
	char *log = 0;
	if ( handle == 0 )
		return;
	if ( nvJitLinkGetInfoLogSize(handle,&log_size) != NVJITLINK_SUCCESS )
		return;
	if ( log_size <= 1 )
		return;
	log = (char *)malloc(log_size);
	if ( log == 0 )
		return;
	if ( nvJitLinkGetInfoLog(handle,log) == NVJITLINK_SUCCESS )
		printf("nvJitLink info log:\n%s\n",log);
	free(log);
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
	"extern \"C\" __global__ void nvjitlink_add1_u32(unsigned int *out)\n"
	"{\n"
	"    int i = (int)threadIdx.x + ((int)blockIdx.x * (int)blockDim.x);\n"
	"    if ( i == 0 ) out[0] = 0x12345678u + 1u;\n"
	"}\n";
	const char *nvrtc_opts[8];
	const char *link_opts[8];
	nvrtcProgram prog = 0;
	nvJitLinkHandle link = 0;
	uint32_t num_link_opts = 0;
	size_t ptx_size = 0,cubin_size = 0,log_size = 0;
	char *ptx = 0,*log = 0;
	void *cubin = 0;
	int32_t nvrtc_major = 0,nvrtc_minor = 0;
	uint32_t nvjitlink_major = 0,nvjitlink_minor = 0;
	int32_t num_nvrtc_opts = 0,rc = 0;
	CUdevice dev = 0;
	CUcontext ctx = 0;
	CUmodule mod = 0;
	CUfunction fn = 0;
	CUdeviceptr d_out = 0;
	uint32_t out = 0;
	(void)argc;
	(void)argv;
	cuda_probe_print_versions();
	nvrtcVersion(&nvrtc_major,&nvrtc_minor);
	printf("nvrtcVersion=%d.%d\n",nvrtc_major,nvrtc_minor);
	if ( nvJitLinkVersion(&nvjitlink_major,&nvjitlink_minor) == NVJITLINK_SUCCESS )
		printf("nvJitLinkVersion=%u.%u\n",nvjitlink_major,nvjitlink_minor);
	nvrtc_opts[num_nvrtc_opts++] = "--std=c++17";
	nvrtc_opts[num_nvrtc_opts++] = "--gpu-architecture=compute_121";
	nvrtc_opts[num_nvrtc_opts++] = "--fmad=false";
	rc = nvrtc_check(nvrtcCreateProgram(&prog,src,"cuda_sm121_nvjitlink_jit.cu",0,0,0),-1,"nvrtcCreateProgram");
	if ( rc != 0 )
		return(rc);
	rc = nvrtc_check(nvrtcCompileProgram(prog,num_nvrtc_opts,nvrtc_opts),-2,"nvrtcCompileProgram");
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
	rc = nvrtc_check(nvrtcGetPTXSize(prog,&ptx_size),-3,"nvrtcGetPTXSize");
	if ( rc != 0 )
	{
		nvrtcDestroyProgram(&prog);
		return(rc);
	}
	ptx = (char *)malloc(ptx_size);
	if ( ptx == 0 )
	{
		nvrtcDestroyProgram(&prog);
		return(-4);
	}
	rc = nvrtc_check(nvrtcGetPTX(prog,ptx),-5,"nvrtcGetPTX");
	nvrtcDestroyProgram(&prog);
	if ( rc != 0 )
	{
		free(ptx);
		return(rc);
	}
	printf("nvrtc ptx bytes=%zu\n",ptx_size);
	link_opts[num_link_opts++] = "-arch=sm_121";
	link_opts[num_link_opts++] = "-O3";
	rc = nvjitlink_check(nvJitLinkCreate(&link,num_link_opts,link_opts),-6,"nvJitLinkCreate",link);
	if ( rc != 0 )
	{
		free(ptx);
		return(rc);
	}
	rc = nvjitlink_check(nvJitLinkAddData(link,NVJITLINK_INPUT_PTX,ptx,ptx_size,"nvjitlink.ptx"),-7,"nvJitLinkAddData(PTX)",link);
	free(ptx);
	if ( rc != 0 )
	{
		(void)nvJitLinkDestroy(&link);
		return(rc);
	}
	rc = nvjitlink_check(nvJitLinkComplete(link),-8,"nvJitLinkComplete",link);
	if ( rc != 0 )
	{
		nvjitlink_print_info_log(link);
		(void)nvJitLinkDestroy(&link);
		return(rc);
	}
	nvjitlink_print_info_log(link);
	rc = nvjitlink_check(nvJitLinkGetLinkedCubinSize(link,&cubin_size),-9,"nvJitLinkGetLinkedCubinSize",link);
	if ( rc != 0 )
	{
		(void)nvJitLinkDestroy(&link);
		return(rc);
	}
	cubin = malloc(cubin_size);
	if ( cubin == 0 )
	{
		(void)nvJitLinkDestroy(&link);
		return(-10);
	}
	rc = nvjitlink_check(nvJitLinkGetLinkedCubin(link,cubin),-11,"nvJitLinkGetLinkedCubin",link);
	(void)nvJitLinkDestroy(&link);
	if ( rc != 0 )
	{
		free(cubin);
		return(rc);
	}
	rc = cu_check(cuInit(0),-12,"cuInit");
	if ( rc != 0 )
	{
		free(cubin);
		return(rc);
	}
	rc = cu_check(cuDeviceGet(&dev,0),-13,"cuDeviceGet(0)");
	if ( rc != 0 )
	{
		free(cubin);
		return(rc);
	}
	rc = cu_check(cuCtxCreate(&ctx,0,0,dev),-14,"cuCtxCreate");
	if ( rc != 0 )
	{
		free(cubin);
		return(rc);
	}
	rc = cu_check(cuModuleLoadDataEx(&mod,cubin,0,0,0),-15,"cuModuleLoadDataEx(cubin)");
	free(cubin);
	if ( rc != 0 )
	{
		cuCtxDestroy(ctx);
		return(rc);
	}
	rc = cu_check(cuModuleGetFunction(&fn,mod,"nvjitlink_add1_u32"),-16,"cuModuleGetFunction");
	if ( rc != 0 )
	{
		cuModuleUnload(mod);
		cuCtxDestroy(ctx);
		return(rc);
	}
	rc = cu_check(cuMemAlloc(&d_out,(size_t)sizeof(uint32_t)),-17,"cuMemAlloc(d_out)");
	if ( rc != 0 )
	{
		cuModuleUnload(mod);
		cuCtxDestroy(ctx);
		return(rc);
	}
	rc = cu_check(cuMemsetD32(d_out,0,1),-18,"cuMemsetD32");
	if ( rc != 0 )
	{
		cuMemFree(d_out);
		cuModuleUnload(mod);
		cuCtxDestroy(ctx);
		return(rc);
	}
	{
		void *args[] = {&d_out};
		rc = cu_check(cuLaunchKernel(fn,1,1,1,32,1,1,0,0,args,0),-19,"cuLaunchKernel");
		if ( rc != 0 )
		{
			cuMemFree(d_out);
			cuModuleUnload(mod);
			cuCtxDestroy(ctx);
			return(rc);
		}
	}
	rc = cu_check(cuCtxSynchronize(),-20,"cuCtxSynchronize");
	if ( rc != 0 )
	{
		cuMemFree(d_out);
		cuModuleUnload(mod);
		cuCtxDestroy(ctx);
		return(rc);
	}
	rc = cu_check(cuMemcpyDtoH(&out,d_out,(size_t)sizeof(uint32_t)),-21,"cuMemcpyDtoH");
	cuMemFree(d_out);
	cuModuleUnload(mod);
	cuCtxDestroy(ctx);
	if ( rc != 0 )
		return(rc);
	if ( out != 0x12345679u )
	{
		fprintf(stderr,"nvjitlink_jit bad out=0x%08x\n",out);
		return(-22);
	}
	printf("nvjitlink_jit ok out=0x%08x\n",out);
	return(0);
}
