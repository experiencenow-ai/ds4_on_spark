#include "ds4/cuda.h"
#include "ds4/common.h"

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
	if ( st.code == 0 )
		return("OK");
	if ( st.code == DS4_CUDA_ERR_DISABLED )
		return("CUDA disabled");
	return("CUDA error (disabled build)");
}

ds4_cuda_status_t ds4_cuda_last_error(void)
{
	return(ds4_cuda_fail(DS4_CUDA_ERR_DISABLED));
}
