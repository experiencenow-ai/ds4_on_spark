#include "ds4/cuda.h"
#include "ds4/log.h"

#if defined(DS4_HAS_CUDA)
#include <cuda_runtime.h>
#include <limits.h>
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

ds4_cuda_status_t ds4_cuda_get_device(int32_t *out_dev)
{
	int dev;
	cudaError_t err;
	if ( out_dev == 0 )
		return(ds4_cuda_fail(DS4_CUDA_ERR_INVALID_ARG));
	*out_dev = -1;
	dev = -1;
	err = cudaGetDevice(&dev);
	if ( err != cudaSuccess )
		return(ds4_cuda_fail((int32_t)err));
	*out_dev = (int32_t)dev;
	return(ds4_cuda_ok());
}

ds4_cuda_status_t ds4_cuda_set_device(int32_t dev)
{
	cudaError_t err;
	if ( dev < 0 )
		return(ds4_cuda_fail(DS4_CUDA_ERR_INVALID_ARG));
	err = cudaSetDevice((int)dev);
	if ( err != cudaSuccess )
	{
		if ( err == cudaErrorInvalidDevice || err == cudaErrorNoDevice )
			return(ds4_cuda_fail(DS4_CUDA_ERR_NO_DEVICE));
		return(ds4_cuda_fail((int32_t)err));
	}
	return(ds4_cuda_ok());
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

ds4_cuda_status_t ds4_cuda_check_last_error(const char *file,int32_t line)
{
	cudaError_t err;
	err = cudaGetLastError();
	return(ds4_cuda_check_i32((int32_t)err,"cudaGetLastError()",file,line));
}

ds4_cuda_status_t ds4_cuda_check_peek_last_error(const char *file,int32_t line)
{
	cudaError_t err;
	err = cudaPeekAtLastError();
	return(ds4_cuda_check_i32((int32_t)err,"cudaPeekAtLastError()",file,line));
}

ds4_cuda_status_t ds4_cuda_device_count(int32_t *out_count)
{
	int dev_count;
	cudaError_t err;
	if ( out_count == 0 )
		return(ds4_cuda_fail(DS4_CUDA_ERR_INVALID_ARG));
	*out_count = 0;
	dev_count = 0;
	err = cudaGetDeviceCount(&dev_count);
	if ( err == cudaSuccess )
	{
		if ( dev_count <= 0 )
			return(ds4_cuda_fail(DS4_CUDA_ERR_NO_DEVICE));
		*out_count = dev_count;
		return(ds4_cuda_ok());
	}
	if ( err == cudaErrorNoDevice )
		return(ds4_cuda_fail(DS4_CUDA_ERR_NO_DEVICE));
	return(ds4_cuda_fail((int32_t)err));
}

ds4_cuda_status_t ds4_cuda_device_info(ds4_cuda_device_info_t *out,int32_t dev_index)
{
	cudaDeviceProp prop;
	cudaError_t err;
	int32_t i,cap;
	if ( out == 0 )
		return(ds4_cuda_fail(DS4_CUDA_ERR_INVALID_ARG));
	if ( dev_index < 0 )
		return(ds4_cuda_fail(DS4_CUDA_ERR_INVALID_ARG));
	out->dev = dev_index;
	out->major = 0;
	out->minor = 0;
	out->multiprocessor_count = 0;
	out->total_global_mem = 0;
	for (i=0; i<(int32_t)sizeof(out->name); i++)
		out->name[i] = 0;
	err = cudaGetDeviceProperties(&prop,dev_index);
	if ( err != cudaSuccess )
	{
		if ( err == cudaErrorInvalidDevice || err == cudaErrorNoDevice )
			return(ds4_cuda_fail(DS4_CUDA_ERR_NO_DEVICE));
		return(ds4_cuda_fail((int32_t)err));
	}
	out->major = (int32_t)prop.major;
	out->minor = (int32_t)prop.minor;
	out->multiprocessor_count = (int32_t)prop.multiProcessorCount;
	if ( prop.totalGlobalMem > (size_t)INT64_MAX )
		return(ds4_cuda_fail(DS4_CUDA_ERR_SIZE_OVERFLOW));
	out->total_global_mem = (int64_t)prop.totalGlobalMem;
	cap = (int32_t)(sizeof(out->name) - 1);
	for (i=0; i<cap && prop.name[i]!=0; i++)
		out->name[i] = prop.name[i];
	out->name[i] = 0;
	return(ds4_cuda_ok());
}

ds4_cuda_status_t ds4_cuda_stream_create(ds4_cuda_stream_t *out,int32_t flags)
{
	cudaStream_t s;
	cudaError_t err;
	if ( out == 0 )
		return(ds4_cuda_fail(DS4_CUDA_ERR_INVALID_ARG));
	out->h = 0;
	if ( flags != DS4_CUDA_STREAM_FLAGS_DEFAULT )
		return(ds4_cuda_fail(DS4_CUDA_ERR_INVALID_ARG));
	s = 0;
	err = cudaStreamCreate(&s);
	if ( err != cudaSuccess )
		return(ds4_cuda_fail((int32_t)err));
	out->h = (void *)s;
	return(ds4_cuda_ok());
}

ds4_cuda_status_t ds4_cuda_stream_destroy(ds4_cuda_stream_t *s)
{
	cudaError_t err;
	if ( s == 0 )
		return(ds4_cuda_fail(DS4_CUDA_ERR_INVALID_ARG));
	if ( s->h == 0 )
		return(ds4_cuda_ok());
	err = cudaStreamDestroy((cudaStream_t)s->h);
	if ( err != cudaSuccess )
		return(ds4_cuda_fail((int32_t)err));
	s->h = 0;
	return(ds4_cuda_ok());
}

ds4_cuda_status_t ds4_cuda_stream_synchronize(ds4_cuda_stream_t s)
{
	cudaError_t err;
	if ( s.h == 0 )
		return(ds4_cuda_fail(DS4_CUDA_ERR_INVALID_ARG));
	err = cudaStreamSynchronize((cudaStream_t)s.h);
	if ( err != cudaSuccess )
		return(ds4_cuda_fail((int32_t)err));
	return(ds4_cuda_ok());
}

ds4_cuda_status_t ds4_cuda_event_create(ds4_cuda_event_t *out,int32_t flags)
{
	cudaEvent_t e;
	cudaError_t err;
	unsigned int cuda_flags;
	if ( out == 0 )
		return(ds4_cuda_fail(DS4_CUDA_ERR_INVALID_ARG));
	out->h = 0;
	if ( (flags & ~DS4_CUDA_EVENT_FLAGS_DISABLE_TIMING) != 0 )
		return(ds4_cuda_fail(DS4_CUDA_ERR_INVALID_ARG));
	cuda_flags = 0;
	if ( (flags & DS4_CUDA_EVENT_FLAGS_DISABLE_TIMING) != 0 )
		cuda_flags |= (unsigned int)cudaEventDisableTiming;
	e = 0;
	err = cudaEventCreateWithFlags(&e,cuda_flags);
	if ( err != cudaSuccess )
		return(ds4_cuda_fail((int32_t)err));
	out->h = (void *)e;
	return(ds4_cuda_ok());
}

ds4_cuda_status_t ds4_cuda_event_destroy(ds4_cuda_event_t *e)
{
	cudaError_t err;
	if ( e == 0 )
		return(ds4_cuda_fail(DS4_CUDA_ERR_INVALID_ARG));
	if ( e->h == 0 )
		return(ds4_cuda_ok());
	err = cudaEventDestroy((cudaEvent_t)e->h);
	if ( err != cudaSuccess )
		return(ds4_cuda_fail((int32_t)err));
	e->h = 0;
	return(ds4_cuda_ok());
}

ds4_cuda_status_t ds4_cuda_event_record(ds4_cuda_event_t e,ds4_cuda_stream_t s)
{
	cudaError_t err;
	if ( e.h == 0 )
		return(ds4_cuda_fail(DS4_CUDA_ERR_INVALID_ARG));
	if ( s.h == 0 )
		return(ds4_cuda_fail(DS4_CUDA_ERR_INVALID_ARG));
	err = cudaEventRecord((cudaEvent_t)e.h,(cudaStream_t)s.h);
	if ( err != cudaSuccess )
		return(ds4_cuda_fail((int32_t)err));
	return(ds4_cuda_ok());
}

ds4_cuda_status_t ds4_cuda_event_synchronize(ds4_cuda_event_t e)
{
	cudaError_t err;
	if ( e.h == 0 )
		return(ds4_cuda_fail(DS4_CUDA_ERR_INVALID_ARG));
	err = cudaEventSynchronize((cudaEvent_t)e.h);
	if ( err != cudaSuccess )
		return(ds4_cuda_fail((int32_t)err));
	return(ds4_cuda_ok());
}

ds4_cuda_status_t ds4_cuda_event_elapsed_ms(float *out_ms,ds4_cuda_event_t start,ds4_cuda_event_t end)
{
	cudaError_t err;
	float ms;
	if ( out_ms == 0 )
		return(ds4_cuda_fail(DS4_CUDA_ERR_INVALID_ARG));
	*out_ms = 0.0f;
	if ( start.h == 0 )
		return(ds4_cuda_fail(DS4_CUDA_ERR_INVALID_ARG));
	if ( end.h == 0 )
		return(ds4_cuda_fail(DS4_CUDA_ERR_INVALID_ARG));
	ms = 0.0f;
	err = cudaEventElapsedTime(&ms,(cudaEvent_t)start.h,(cudaEvent_t)end.h);
	if ( err != cudaSuccess )
		return(ds4_cuda_fail((int32_t)err));
	*out_ms = ms;
	return(ds4_cuda_ok());
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

ds4_cuda_status_t ds4_cuda_malloc_host(void **out,int64_t bytes)
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
	err = cudaMallocHost(out,n);
	if ( err != cudaSuccess )
		return(ds4_cuda_fail((int32_t)err));
	return(ds4_cuda_ok());
}

ds4_cuda_status_t ds4_cuda_free_host(void *ptr)
{
	cudaError_t err;
	err = cudaFreeHost(ptr);
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
