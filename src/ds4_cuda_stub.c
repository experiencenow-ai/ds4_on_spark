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

int32_t ds4_cuda_is_enabled_build(void)
{
	return(0);
}

ds4_cuda_status_t ds4_cuda_init(void)
{
	return(ds4_cuda_fail(DS4_CUDA_ERR_DISABLED));
}

const char *ds4_cuda_errstr(ds4_cuda_status_t st)
{
	if ( st.code == 0 )
		return("OK");
	if ( st.code == DS4_CUDA_ERR_DISABLED )
		return("CUDA disabled");
	if ( st.code == DS4_CUDA_ERR_NO_DEVICE )
		return("No CUDA device");
	if ( st.code < 0 )
		return("DS4 CUDA internal error");
	return("CUDA error (disabled build)");
}

ds4_cuda_status_t ds4_cuda_last_error(void)
{
	return(ds4_cuda_fail(DS4_CUDA_ERR_DISABLED));
}

ds4_cuda_status_t ds4_cuda_peek_last_error(void)
{
	return(ds4_cuda_fail(DS4_CUDA_ERR_DISABLED));
}

ds4_cuda_status_t ds4_cuda_device_synchronize(void)
{
	return(ds4_cuda_fail(DS4_CUDA_ERR_DISABLED));
}

ds4_cuda_status_t ds4_cuda_check_i32(int32_t cuda_err,const char *expr,const char *file,int32_t line)
{
	DS4_UNUSED(expr);
	DS4_UNUSED(file);
	DS4_UNUSED(line);
	if ( cuda_err == 0 )
		return(ds4_cuda_ok());
	return(ds4_cuda_fail(cuda_err));
}
