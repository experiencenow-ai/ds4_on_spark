#include "ds4/cuda.h"
#include "ds4/log.h"

#if defined(DS4_HAS_CUDA)
#include <cuda_runtime.h>
#include <stddef.h>

extern "C" {

ds4_cuda_status_t ds4_cuda_ok(void)
{
	ds4_cuda_status_t st;
	st.code = 0;
	return(st);
}

ds4_cuda_status_t ds4_cuda_fail(int32_t code)
{
	ds4_cuda_status_t st;
	st.code = code;
	return(st);
}

int32_t ds4_cuda_is_ok(ds4_cuda_status_t st)
{
	if ( st.code == 0 )
		return(1);
	return(0);
}

int32_t ds4_cuda_is_enabled_build(void)
{
	return(1);
}

ds4_cuda_status_t ds4_cuda_init(void)
{
	int dev_count;
	cudaError_t err;
	dev_count = 0;
	err = cudaGetDeviceCount(&dev_count);
	if ( err == cudaSuccess )
	{
		if ( dev_count <= 0 )
			return(ds4_cuda_fail(DS4_CUDA_ERR_NO_DEVICE));
		err = cudaSetDevice(0);
		if ( err != cudaSuccess )
			return(ds4_cuda_fail((int32_t)err));
		err = cudaFree(0);
		if ( err != cudaSuccess )
			return(ds4_cuda_fail((int32_t)err));
		return(ds4_cuda_ok());
	}
	if ( err == cudaErrorNoDevice )
		return(ds4_cuda_fail(DS4_CUDA_ERR_NO_DEVICE));
	return(ds4_cuda_fail((int32_t)err));
}

const char *ds4_cuda_errstr(ds4_cuda_status_t st)
{
	cudaError_t err;
	if ( st.code == 0 )
		return("OK");
	if ( st.code == DS4_CUDA_ERR_DISABLED )
		return("CUDA disabled");
	if ( st.code == DS4_CUDA_ERR_NO_DEVICE )
		return("No CUDA device");
	if ( st.code == DS4_CUDA_ERR_INVALID_ARG )
		return("Invalid argument");
	if ( st.code == DS4_CUDA_ERR_SIZE_OVERFLOW )
		return("Size overflow");
	if ( st.code < 0 )
		return("DS4 CUDA internal error");
	err = (cudaError_t)st.code;
	return(cudaGetErrorString(err));
}

ds4_cuda_status_t ds4_cuda_last_error(void)
{
	cudaError_t err;
	err = cudaGetLastError();
	if ( err == cudaSuccess )
		return(ds4_cuda_ok());
	return(ds4_cuda_fail((int32_t)err));
}

ds4_cuda_status_t ds4_cuda_peek_last_error(void)
{
	cudaError_t err;
	err = cudaPeekAtLastError();
	if ( err == cudaSuccess )
		return(ds4_cuda_ok());
	return(ds4_cuda_fail((int32_t)err));
}

ds4_cuda_status_t ds4_cuda_device_synchronize(void)
{
	cudaError_t err;
	err = cudaDeviceSynchronize();
	if ( err == cudaSuccess )
		return(ds4_cuda_ok());
	return(ds4_cuda_fail((int32_t)err));
}

ds4_cuda_status_t ds4_cuda_check_i32(int32_t cuda_err,const char *expr,const char *file,int32_t line)
{
	cudaError_t err;
	if ( cuda_err == 0 )
		return(ds4_cuda_ok());
	if ( cuda_err < 0 )
		return(ds4_cuda_fail(cuda_err));
	err = (cudaError_t)cuda_err;
	if ( expr == 0 )
		expr = "?";
	if ( file == 0 )
		file = "?";
	DS4_LOGE("cuda: %s:%d %s failed: %s",file,line,expr,cudaGetErrorString(err));
	return(ds4_cuda_fail(cuda_err));
}

ds4_cuda_status_t ds4_cuda_malloc(void **out,int64_t bytes)
{
	cudaError_t err;
	size_t n;
	if ( out == 0 )
		return(ds4_cuda_fail(DS4_CUDA_ERR_INVALID_ARG));
	*out = 0;
	if ( bytes < 0 )
		return(ds4_cuda_fail(DS4_CUDA_ERR_INVALID_ARG));
	if ( bytes == 0 )
		return(ds4_cuda_ok());
	if ( bytes > (int64_t)SIZE_MAX )
		return(ds4_cuda_fail(DS4_CUDA_ERR_SIZE_OVERFLOW));
	n = (size_t)bytes;
	err = cudaMalloc(out,n);
	if ( err != cudaSuccess )
		return(ds4_cuda_fail((int32_t)err));
	return(ds4_cuda_ok());
}

ds4_cuda_status_t ds4_cuda_free(void *ptr)
{
	cudaError_t err;
	err = cudaFree(ptr);
	if ( err != cudaSuccess )
		return(ds4_cuda_fail((int32_t)err));
	return(ds4_cuda_ok());
}

ds4_cuda_status_t ds4_cuda_memset(void *dst,int32_t value,int64_t bytes)
{
	cudaError_t err;
	size_t n;
	if ( bytes < 0 )
		return(ds4_cuda_fail(DS4_CUDA_ERR_INVALID_ARG));
	if ( bytes == 0 )
		return(ds4_cuda_ok());
	if ( dst == 0 )
		return(ds4_cuda_fail(DS4_CUDA_ERR_INVALID_ARG));
	if ( bytes > (int64_t)SIZE_MAX )
		return(ds4_cuda_fail(DS4_CUDA_ERR_SIZE_OVERFLOW));
	n = (size_t)bytes;
	err = cudaMemset(dst,value,n);
	if ( err != cudaSuccess )
		return(ds4_cuda_fail((int32_t)err));
	return(ds4_cuda_ok());
}

ds4_cuda_status_t ds4_cuda_memcpy_h2d(void *dst,const void *src,int64_t bytes)
{
	cudaError_t err;
	size_t n;
	if ( bytes < 0 )
		return(ds4_cuda_fail(DS4_CUDA_ERR_INVALID_ARG));
	if ( bytes == 0 )
		return(ds4_cuda_ok());
	if ( dst == 0 )
		return(ds4_cuda_fail(DS4_CUDA_ERR_INVALID_ARG));
	if ( src == 0 )
		return(ds4_cuda_fail(DS4_CUDA_ERR_INVALID_ARG));
	if ( bytes > (int64_t)SIZE_MAX )
		return(ds4_cuda_fail(DS4_CUDA_ERR_SIZE_OVERFLOW));
	n = (size_t)bytes;
	err = cudaMemcpy(dst,src,n,cudaMemcpyHostToDevice);
	if ( err != cudaSuccess )
		return(ds4_cuda_fail((int32_t)err));
	return(ds4_cuda_ok());
}

ds4_cuda_status_t ds4_cuda_memcpy_d2h(void *dst,const void *src,int64_t bytes)
{
	cudaError_t err;
	size_t n;
	if ( bytes < 0 )
		return(ds4_cuda_fail(DS4_CUDA_ERR_INVALID_ARG));
	if ( bytes == 0 )
		return(ds4_cuda_ok());
	if ( dst == 0 )
		return(ds4_cuda_fail(DS4_CUDA_ERR_INVALID_ARG));
	if ( src == 0 )
		return(ds4_cuda_fail(DS4_CUDA_ERR_INVALID_ARG));
	if ( bytes > (int64_t)SIZE_MAX )
		return(ds4_cuda_fail(DS4_CUDA_ERR_SIZE_OVERFLOW));
	n = (size_t)bytes;
	err = cudaMemcpy(dst,src,n,cudaMemcpyDeviceToHost);
	if ( err != cudaSuccess )
		return(ds4_cuda_fail((int32_t)err));
	return(ds4_cuda_ok());
}

}
#else
#error "ds4_cuda.cu must only compile when DS4_HAS_CUDA is set"
#endif
