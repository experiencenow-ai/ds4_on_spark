#include <stdint.h>
#include <stdio.h>

#include <cuda_runtime.h>

#include "cuda_probe_util.h"

#define STR1(x) #x
#define STR(x) STR1(x)

__device__ __constant__ uint32_t ds4_cuda_arch_const =
#if defined(__CUDA_ARCH__)
	(uint32_t)__CUDA_ARCH__;
#else
	0U;
#endif

static const char *macro_arch_list(void)
{
#if defined(__CUDA_ARCH_LIST__)
	return(STR(__CUDA_ARCH_LIST__));
#else
	return("(missing)");
#endif
}

static const char *macro_arch_specific(void)
{
#if defined(__CUDA_ARCH_SPECIFIC__)
	return(STR(__CUDA_ARCH_SPECIFIC__));
#else
	return("(missing)");
#endif
}

static const char *macro_arch_family_specific(void)
{
#if defined(__CUDA_ARCH_FAMILY_SPECIFIC__)
	return(STR(__CUDA_ARCH_FAMILY_SPECIFIC__));
#else
	return("(missing)");
#endif
}

static void print_versions(void)
{
#if defined(__CUDACC_VER_MAJOR__) && defined(__CUDACC_VER_MINOR__) && defined(__CUDACC_VER_BUILD__)
	printf("nvcc_ver=%d.%d.%d ",__CUDACC_VER_MAJOR__,__CUDACC_VER_MINOR__,__CUDACC_VER_BUILD__);
#else
	printf("nvcc_ver=(missing) ");
#endif
#if defined(CUDART_VERSION)
	printf("cudart_ver=%d ",(int32_t)CUDART_VERSION);
#else
	printf("cudart_ver=(missing) ");
#endif
}

int main(int argc,char **argv)
{
	int32_t count = 0,rc = 0,driver_v = -1,runtime_v = -1;
	cudaDeviceProp prop;
	uint32_t cuda_arch = 0;
	(void)argc;
	(void)argv;
	(void)cudaDriverGetVersion(&driver_v);
	(void)cudaRuntimeGetVersion(&runtime_v);
	rc = cuda_probe_check(cudaGetDeviceCount(&count),-1,"cudaGetDeviceCount");
	if ( rc != 0 )
		return(rc);
	if ( count <= 0 )
	{
		print_versions();
		printf("cuda_drv=%d cuda_rt=%d count=%d __CUDA_ARCH__=%u __CUDA_ARCH_LIST__=%s __CUDA_ARCH_SPECIFIC__=%s __CUDA_ARCH_FAMILY_SPECIFIC__=%s\n",driver_v,runtime_v,count,cuda_arch,macro_arch_list(),macro_arch_specific(),macro_arch_family_specific());
		return(0);
	}
	rc = cuda_probe_check(cudaGetDeviceProperties(&prop,0),-2,"cudaGetDeviceProperties(0)");
	if ( rc != 0 )
		return(rc);
	if ( cudaMemcpyFromSymbol(&cuda_arch,ds4_cuda_arch_const,sizeof(cuda_arch),0,cudaMemcpyDeviceToHost) != cudaSuccess )
	{
		(void)cudaGetLastError();
		cuda_arch = 0;
	}
	print_versions();
	printf("cuda_drv=%d cuda_rt=%d dev0=\"%s\" cc=%d.%d __CUDA_ARCH__=%u __CUDA_ARCH_LIST__=%s __CUDA_ARCH_SPECIFIC__=%s __CUDA_ARCH_FAMILY_SPECIFIC__=%s\n",driver_v,runtime_v,prop.name,prop.major,prop.minor,cuda_arch,macro_arch_list(),macro_arch_specific(),macro_arch_family_specific());
	return(0);
}
