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
	if ( st.code == DS4_CUDA_ERR_INVALID_ARG )
		return("Invalid argument");
	if ( st.code == DS4_CUDA_ERR_SIZE_OVERFLOW )
		return("Size overflow");
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

ds4_cuda_status_t ds4_cuda_check_last_error(const char *file,int32_t line)
{
	DS4_UNUSED(file);
	DS4_UNUSED(line);
	return(ds4_cuda_last_error());
}

ds4_cuda_status_t ds4_cuda_check_peek_last_error(const char *file,int32_t line)
{
	DS4_UNUSED(file);
	DS4_UNUSED(line);
	return(ds4_cuda_peek_last_error());
}

ds4_cuda_status_t ds4_cuda_device_count(int32_t *out_count)
{
	if ( out_count == 0 )
		return(ds4_cuda_fail(DS4_CUDA_ERR_INVALID_ARG));
	*out_count = 0;
	return(ds4_cuda_fail(DS4_CUDA_ERR_DISABLED));
}

ds4_cuda_status_t ds4_cuda_device_info(ds4_cuda_device_info_t *out,int32_t dev_index)
{
	int32_t i;
	if ( out == 0 )
		return(ds4_cuda_fail(DS4_CUDA_ERR_INVALID_ARG));
	out->dev = dev_index;
	out->major = 0;
	out->minor = 0;
	out->multiprocessor_count = 0;
	out->total_global_mem = 0;
	for (i=0; i<(int32_t)sizeof(out->name); i++)
		out->name[i] = 0;
	return(ds4_cuda_fail(DS4_CUDA_ERR_DISABLED));
}

ds4_cuda_status_t ds4_cuda_malloc(void **out,int64_t bytes)
{
	DS4_UNUSED(bytes);
	if ( out == 0 )
		return(ds4_cuda_fail(DS4_CUDA_ERR_INVALID_ARG));
	*out = 0;
	return(ds4_cuda_fail(DS4_CUDA_ERR_DISABLED));
}

ds4_cuda_status_t ds4_cuda_free(void *ptr)
{
	DS4_UNUSED(ptr);
	return(ds4_cuda_fail(DS4_CUDA_ERR_DISABLED));
}

ds4_cuda_status_t ds4_cuda_malloc_host(void **out,int64_t bytes)
{
	DS4_UNUSED(bytes);
	if ( out == 0 )
		return(ds4_cuda_fail(DS4_CUDA_ERR_INVALID_ARG));
	*out = 0;
	return(ds4_cuda_fail(DS4_CUDA_ERR_DISABLED));
}

ds4_cuda_status_t ds4_cuda_free_host(void *ptr)
{
	DS4_UNUSED(ptr);
	return(ds4_cuda_fail(DS4_CUDA_ERR_DISABLED));
}

ds4_cuda_status_t ds4_cuda_memset(void *dst,int32_t value,int64_t bytes)
{
	DS4_UNUSED(dst);
	DS4_UNUSED(value);
	DS4_UNUSED(bytes);
	return(ds4_cuda_fail(DS4_CUDA_ERR_DISABLED));
}

ds4_cuda_status_t ds4_cuda_memcpy_h2d(void *dst,const void *src,int64_t bytes)
{
	DS4_UNUSED(dst);
	DS4_UNUSED(src);
	DS4_UNUSED(bytes);
	return(ds4_cuda_fail(DS4_CUDA_ERR_DISABLED));
}

ds4_cuda_status_t ds4_cuda_memcpy_d2h(void *dst,const void *src,int64_t bytes)
{
	DS4_UNUSED(dst);
	DS4_UNUSED(src);
	DS4_UNUSED(bytes);
	return(ds4_cuda_fail(DS4_CUDA_ERR_DISABLED));
}
