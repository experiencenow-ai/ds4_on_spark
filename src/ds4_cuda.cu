#include "ds4/cuda.h"

#if defined(DS4_HAS_CUDA)
#include <cuda_runtime.h>

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
#else
#error "ds4_cuda.cu must only compile when DS4_HAS_CUDA is set"
#endif
