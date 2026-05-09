#include "ds4/cuda.h"
#include "ds4/log.h"

#if defined(DS4_HAS_CUDA)
#include <cuda_runtime.h>

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

const char *ds4_cuda_errstr(ds4_cuda_status_t st)
{
	cudaError_t err;
	if ( st.code == 0 )
		return("OK");
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

}
#else
#error "ds4_cuda.cu must only compile when DS4_HAS_CUDA is set"
#endif
