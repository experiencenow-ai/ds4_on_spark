#include "ds4/cuda.h"
#include "ds4/log.h"

#if DS4_HAS_CUDA
#include <cuda_runtime.h>
#include <limits.h>
#include <stddef.h>
#include <stdio.h>

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

static int32_t ds4_cuda_i64_fits_size(int64_t bytes)
{
	if ( bytes < 0 )
		return(0);
	if ( (uint64_t)bytes > (uint64_t)SIZE_MAX )
		return(0);
	return(1);
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

int32_t ds4_cuda_status_format(ds4_cuda_status_t st,char *out,int32_t cap)
{
	const char *s;
	int32_t n;
	if ( out == 0 )
		return(-1);
	if ( cap <= 0 )
		return(-2);
	s = ds4_cuda_errstr(st);
	if ( s == 0 )
		s = "?";
	n = (int32_t)snprintf(out,(size_t)cap,"code=%d err=%s",st.code,s);
	if ( n < 0 )
	{
		out[0] = 0;
		return(-3);
	}
	out[cap - 1] = 0;
	if ( n >= cap )
		return(-4);
	return(n);
}

int32_t ds4_cuda_error_format_i32(int32_t cuda_err,const char *expr,const char *file,int32_t line,char *out,int32_t cap)
{
	ds4_cuda_status_t st;
	const char *s;
	int32_t n;
	if ( out == 0 )
		return(-1);
	if ( cap <= 0 )
		return(-2);
	if ( expr == 0 )
		expr = "?";
	if ( file == 0 )
		file = "?";
	if ( cuda_err == 0 )
		st = ds4_cuda_ok();
	else
		st = ds4_cuda_fail(cuda_err);
	s = ds4_cuda_errstr(st);
	if ( s == 0 )
		s = "?";
	n = (int32_t)snprintf(out,(size_t)cap,"%s:%d %s => code=%d err=%s",file,line,expr,cuda_err,s);
	if ( n < 0 )
	{
		out[0] = 0;
		return(-3);
	}
	out[cap - 1] = 0;
	if ( n >= cap )
		return(-4);
	return(n);
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
	char msg[256];
	if ( cuda_err == 0 )
		return(ds4_cuda_ok());
	if ( cuda_err < 0 )
		return(ds4_cuda_fail(cuda_err));
	err = (cudaError_t)cuda_err;
	if ( expr == 0 )
		expr = "?";
	if ( file == 0 )
		file = "?";
	msg[0] = 0;
	if ( ds4_cuda_error_format_i32((int32_t)err,expr,file,line,msg,(int32_t)sizeof(msg)) > 0 && msg[0] != 0 )
		DS4_LOGE("cuda: %s",msg);
	else
		DS4_LOGE("cuda: %s:%d %s failed: %s",file,line,expr,cudaGetErrorString(err));
	return(ds4_cuda_fail(cuda_err));
}

ds4_cuda_status_t ds4_cuda_check_peek_last_error_ex(const char *expr,const char *file,int32_t line)
{
	cudaError_t err;
	err = cudaPeekAtLastError();
	return(ds4_cuda_check_i32((int32_t)err,expr,file,line));
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
	if ( out == 0 )
		return(ds4_cuda_fail(DS4_CUDA_ERR_INVALID_ARG));
	*out = 0;
	if ( bytes < 0 )
		return(ds4_cuda_fail(DS4_CUDA_ERR_INVALID_ARG));
	if ( bytes == 0 )
		return(ds4_cuda_ok());
	if ( ds4_cuda_i64_fits_size(bytes) == 0 )
		return(ds4_cuda_fail(DS4_CUDA_ERR_SIZE_OVERFLOW));
	err = cudaMalloc(out,(size_t)bytes);
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
	if ( out == 0 )
		return(ds4_cuda_fail(DS4_CUDA_ERR_INVALID_ARG));
	*out = 0;
	if ( bytes < 0 )
		return(ds4_cuda_fail(DS4_CUDA_ERR_INVALID_ARG));
	if ( bytes == 0 )
		return(ds4_cuda_ok());
	if ( ds4_cuda_i64_fits_size(bytes) == 0 )
		return(ds4_cuda_fail(DS4_CUDA_ERR_SIZE_OVERFLOW));
	err = cudaMallocHost(out,(size_t)bytes);
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
	if ( bytes < 0 )
		return(ds4_cuda_fail(DS4_CUDA_ERR_INVALID_ARG));
	if ( bytes == 0 )
		return(ds4_cuda_ok());
	if ( dst == 0 )
		return(ds4_cuda_fail(DS4_CUDA_ERR_INVALID_ARG));
	if ( ds4_cuda_i64_fits_size(bytes) == 0 )
		return(ds4_cuda_fail(DS4_CUDA_ERR_SIZE_OVERFLOW));
	err = cudaMemset(dst,value,(size_t)bytes);
	if ( err != cudaSuccess )
		return(ds4_cuda_fail((int32_t)err));
	return(ds4_cuda_ok());
}

ds4_cuda_status_t ds4_cuda_memcpy_h2d(void *dst,const void *src,int64_t bytes)
{
	cudaError_t err;
	if ( bytes < 0 )
		return(ds4_cuda_fail(DS4_CUDA_ERR_INVALID_ARG));
	if ( bytes == 0 )
		return(ds4_cuda_ok());
	if ( dst == 0 )
		return(ds4_cuda_fail(DS4_CUDA_ERR_INVALID_ARG));
	if ( src == 0 )
		return(ds4_cuda_fail(DS4_CUDA_ERR_INVALID_ARG));
	if ( ds4_cuda_i64_fits_size(bytes) == 0 )
		return(ds4_cuda_fail(DS4_CUDA_ERR_SIZE_OVERFLOW));
	err = cudaMemcpy(dst,src,(size_t)bytes,cudaMemcpyHostToDevice);
	if ( err != cudaSuccess )
		return(ds4_cuda_fail((int32_t)err));
	return(ds4_cuda_ok());
}

ds4_cuda_status_t ds4_cuda_memcpy_d2h(void *dst,const void *src,int64_t bytes)
{
	cudaError_t err;
	if ( bytes < 0 )
		return(ds4_cuda_fail(DS4_CUDA_ERR_INVALID_ARG));
	if ( bytes == 0 )
		return(ds4_cuda_ok());
	if ( dst == 0 )
		return(ds4_cuda_fail(DS4_CUDA_ERR_INVALID_ARG));
	if ( src == 0 )
		return(ds4_cuda_fail(DS4_CUDA_ERR_INVALID_ARG));
	if ( ds4_cuda_i64_fits_size(bytes) == 0 )
		return(ds4_cuda_fail(DS4_CUDA_ERR_SIZE_OVERFLOW));
	err = cudaMemcpy(dst,src,(size_t)bytes,cudaMemcpyDeviceToHost);
	if ( err != cudaSuccess )
		return(ds4_cuda_fail((int32_t)err));
	return(ds4_cuda_ok());
}

static __global__ void ds4_fill_u8_kernel(uint8_t *dst,uint8_t value,int32_t n)
{
	int64_t idx64;
	idx64 = ((int64_t)((int32_t)blockIdx.x) * (int64_t)((int32_t)blockDim.x));
	idx64 += (int64_t)((int32_t)threadIdx.x);
	if ( idx64 >= (int64_t)n )
		return;
	dst[(int32_t)idx64] = value;
}

ds4_cuda_status_t ds4_cuda_fill_u8(void *dst,uint8_t value,int64_t bytes,ds4_cuda_stream_t s)
{
	dim3 grid,block;
	cudaStream_t stream;
	int32_t n,threads,blocks;
	if ( bytes < 0 )
		return(ds4_cuda_fail(DS4_CUDA_ERR_INVALID_ARG));
	if ( bytes == 0 )
		return(ds4_cuda_ok());
	if ( dst == 0 )
		return(ds4_cuda_fail(DS4_CUDA_ERR_INVALID_ARG));
	if ( bytes > (int64_t)INT32_MAX )
		return(ds4_cuda_fail(DS4_CUDA_ERR_SIZE_OVERFLOW));
	n = (int32_t)bytes;
	threads = 256;
	blocks = ((n + threads - 1) / threads);
	block = dim3((unsigned int)threads,1,1);
	grid = dim3((unsigned int)blocks,1,1);
	stream = (cudaStream_t)s.h;
	return(DS4_CUDA_KERNEL_LAUNCH(ds4_fill_u8_kernel<<<grid,block,0,stream>>>((uint8_t *)dst,value,n)));
}

typedef struct
{
	float *x,*gate,*up,*down,*mid,*out;
	int32_t *selected,*sorted_pairs,*expert_offsets,*expert_counts;
	const float **gate_ptrs,**up_ptrs,**down_ptrs;
	const float **host_gate_ptrs,**host_up_ptrs,**host_down_ptrs;
	int32_t *host_selected,*host_sorted_pairs,*host_expert_offsets,*host_expert_counts,*host_expert_write;
} ds4_expert_dummy_buffers_t;

static __global__ void ds4_expert_dummy_init_float_kernel(float *dst,int64_t n,uint32_t seed)
{
	int64_t idx;
	uint32_t x;
	idx = ((int64_t)((int32_t)blockIdx.x) * (int64_t)((int32_t)blockDim.x));
	idx += (int64_t)((int32_t)threadIdx.x);
	if ( idx >= n )
		return;
	x = (uint32_t)idx ^ seed;
	x = ((x * 1664525u) + 1013904223u);
	dst[idx] = ((float)(int32_t)(x & 1023u) - 512.0f) * 0.0009765625f;
}

static __global__ void ds4_expert_dummy_gateup_kernel(float *mid,const float *x,const float * const *gate_ptrs,const float * const *up_ptrs,const int32_t *selected,int32_t tokens,int32_t topk,int32_t hidden_dim,int32_t mid_dim)
{
	int32_t row,pair,token,expert,h;
	const float *xr,*gr,*ur;
	float gate,up;
	row = ((int32_t)blockIdx.x * (int32_t)blockDim.x) + (int32_t)threadIdx.x;
	pair = (int32_t)blockIdx.y;
	if ( row >= mid_dim )
		return;
	if ( pair >= (tokens * topk) )
		return;
	token = (pair / topk);
	expert = selected[pair];
	xr = x + ((int64_t)token * (int64_t)hidden_dim);
	gr = gate_ptrs[expert] + ((int64_t)row * (int64_t)hidden_dim);
	ur = up_ptrs[expert] + ((int64_t)row * (int64_t)hidden_dim);
	gate = 0.0f;
	up = 0.0f;
	for (h=0; h<hidden_dim; h++)
	{
		gate += (gr[h] * xr[h]);
		up += (ur[h] * xr[h]);
	}
	mid[((int64_t)pair * (int64_t)mid_dim) + row] = ((gate / (1.0f + expf(-gate))) * up);
}

static __global__ void ds4_expert_dummy_down_kernel(float *out,const float *mid,const float * const *down_ptrs,const int32_t *selected,int32_t tokens,int32_t topk,int32_t mid_dim,int32_t out_dim)
{
	int32_t row,token,k,expert,m,pair;
	const float *mr,*dr;
	float acc;
	row = ((int32_t)blockIdx.x * (int32_t)blockDim.x) + (int32_t)threadIdx.x;
	token = (int32_t)blockIdx.y;
	if ( row >= out_dim )
		return;
	if ( token >= tokens )
		return;
	acc = 0.0f;
	for (k=0; k<topk; k++)
	{
		pair = ((token * topk) + k);
		expert = selected[pair];
		mr = mid + ((int64_t)pair * (int64_t)mid_dim);
		dr = down_ptrs[expert] + ((int64_t)row * (int64_t)mid_dim);
		for (m=0; m<mid_dim; m++)
			acc += (dr[m] * mr[m]);
	}
	out[((int64_t)token * (int64_t)out_dim) + row] = acc;
}

static __global__ void ds4_expert_dummy_gateup_sorted_kernel(float *mid,const float *x,const float * const *gate_ptrs,const float * const *up_ptrs,const int32_t *sorted_pairs,const int32_t *expert_offsets,const int32_t *expert_counts,int32_t tokens,int32_t topk,int32_t hidden_dim,int32_t mid_dim)
{
	int32_t row,expert,q,pair,token,h;
	const float *xr,*gr,*ur;
	float gate,up;
	row = ((int32_t)blockIdx.x * (int32_t)blockDim.x) + (int32_t)threadIdx.x;
	expert = (int32_t)blockIdx.y;
	q = (int32_t)blockIdx.z;
	if ( row >= mid_dim )
		return;
	if ( q >= expert_counts[expert] )
		return;
	pair = sorted_pairs[expert_offsets[expert] + q];
	token = (pair / topk);
	if ( token >= tokens )
		return;
	xr = x + ((int64_t)token * (int64_t)hidden_dim);
	gr = gate_ptrs[expert] + ((int64_t)row * (int64_t)hidden_dim);
	ur = up_ptrs[expert] + ((int64_t)row * (int64_t)hidden_dim);
	gate = 0.0f;
	up = 0.0f;
	for (h=0; h<hidden_dim; h++)
	{
		gate += (gr[h] * xr[h]);
		up += (ur[h] * xr[h]);
	}
	mid[((int64_t)pair * (int64_t)mid_dim) + row] = ((gate / (1.0f + expf(-gate))) * up);
}

static __global__ void ds4_expert_dummy_down_sorted_kernel(float *out,const float *mid,const float * const *down_ptrs,const int32_t *sorted_pairs,const int32_t *expert_offsets,const int32_t *expert_counts,int32_t tokens,int32_t topk,int32_t mid_dim,int32_t out_dim)
{
	int32_t row,expert,q,pair,token,m;
	const float *mr,*dr;
	float acc;
	row = ((int32_t)blockIdx.x * (int32_t)blockDim.x) + (int32_t)threadIdx.x;
	expert = (int32_t)blockIdx.y;
	q = (int32_t)blockIdx.z;
	if ( row >= out_dim )
		return;
	if ( q >= expert_counts[expert] )
		return;
	pair = sorted_pairs[expert_offsets[expert] + q];
	token = (pair / topk);
	if ( token >= tokens )
		return;
	mr = mid + ((int64_t)pair * (int64_t)mid_dim);
	dr = down_ptrs[expert] + ((int64_t)row * (int64_t)mid_dim);
	acc = 0.0f;
	for (m=0; m<mid_dim; m++)
		acc += (dr[m] * mr[m]);
	atomicAdd(out + ((int64_t)token * (int64_t)out_dim) + row,acc);
}

static int32_t ds4_i64_mul_checked(int64_t *out,int64_t a,int64_t b)
{
	if ( out == 0 )
		return(-1);
	*out = 0;
	if ( a < 0 || b < 0 )
		return(-2);
	if ( a != 0 && b > (INT64_MAX / a) )
		return(-3);
	*out = (a * b);
	return(0);
}

static int32_t ds4_expert_dummy_bytes(const ds4_cuda_expert_queue_dummy_config_t *cfg,int64_t *x_bytes,int64_t *gate_bytes,int64_t *down_bytes,int64_t *mid_bytes,int64_t *out_bytes,int64_t *selected_bytes,int64_t *ptr_bytes)
{
	int64_t pairs,hidden_bytes,mid_float_bytes,out_float_bytes,experts_mid;
	if ( cfg == 0 || x_bytes == 0 || gate_bytes == 0 || down_bytes == 0 || mid_bytes == 0 || out_bytes == 0 || selected_bytes == 0 || ptr_bytes == 0 )
		return(-1);
	if ( cfg->tokens <= 0 || cfg->topk <= 0 || cfg->n_experts <= 0 || cfg->route_experts <= 0 || cfg->route_experts > cfg->n_experts || cfg->hidden_dim <= 0 || cfg->mid_dim <= 0 || cfg->out_dim <= 0 || cfg->iterations <= 0 )
		return(-2);
	if ( ds4_i64_mul_checked(&pairs,(int64_t)cfg->tokens,(int64_t)cfg->topk) < 0 )
		return(-3);
	if ( pairs > (int64_t)INT32_MAX )
		return(-16);
	if ( ds4_i64_mul_checked(&hidden_bytes,(int64_t)cfg->hidden_dim,(int64_t)sizeof(float)) < 0 )
		return(-4);
	if ( ds4_i64_mul_checked(&mid_float_bytes,(int64_t)cfg->mid_dim,(int64_t)sizeof(float)) < 0 )
		return(-5);
	if ( ds4_i64_mul_checked(&out_float_bytes,(int64_t)cfg->out_dim,(int64_t)sizeof(float)) < 0 )
		return(-6);
	if ( ds4_i64_mul_checked(x_bytes,(int64_t)cfg->tokens,hidden_bytes) < 0 )
		return(-7);
	if ( ds4_i64_mul_checked(&experts_mid,(int64_t)cfg->n_experts,(int64_t)cfg->mid_dim) < 0 )
		return(-8);
	if ( ds4_i64_mul_checked(gate_bytes,experts_mid,hidden_bytes) < 0 )
		return(-9);
	if ( ds4_i64_mul_checked(down_bytes,(int64_t)cfg->n_experts,(int64_t)cfg->out_dim) < 0 )
		return(-10);
	if ( ds4_i64_mul_checked(down_bytes,*down_bytes,mid_float_bytes) < 0 )
		return(-11);
	if ( ds4_i64_mul_checked(mid_bytes,pairs,mid_float_bytes) < 0 )
		return(-12);
	if ( ds4_i64_mul_checked(out_bytes,(int64_t)cfg->tokens,out_float_bytes) < 0 )
		return(-13);
	if ( ds4_i64_mul_checked(selected_bytes,pairs,(int64_t)sizeof(int32_t)) < 0 )
		return(-14);
	if ( ds4_i64_mul_checked(ptr_bytes,(int64_t)cfg->n_experts,(int64_t)sizeof(float *)) < 0 )
		return(-15);
	return(0);
}

static void ds4_expert_dummy_zero(ds4_expert_dummy_buffers_t *b)
{
	b->x = 0;
	b->gate = 0;
	b->up = 0;
	b->down = 0;
	b->mid = 0;
	b->out = 0;
	b->selected = 0;
	b->sorted_pairs = 0;
	b->expert_offsets = 0;
	b->expert_counts = 0;
	b->gate_ptrs = 0;
	b->up_ptrs = 0;
	b->down_ptrs = 0;
	b->host_gate_ptrs = 0;
	b->host_up_ptrs = 0;
	b->host_down_ptrs = 0;
	b->host_selected = 0;
	b->host_sorted_pairs = 0;
	b->host_expert_offsets = 0;
	b->host_expert_counts = 0;
	b->host_expert_write = 0;
}

static void ds4_expert_dummy_free(ds4_expert_dummy_buffers_t *b)
{
	if ( b->x != 0 )
		cudaFree(b->x);
	if ( b->gate != 0 )
		cudaFree(b->gate);
	if ( b->up != 0 )
		cudaFree(b->up);
	if ( b->down != 0 )
		cudaFree(b->down);
	if ( b->mid != 0 )
		cudaFree(b->mid);
	if ( b->out != 0 )
		cudaFree(b->out);
	if ( b->selected != 0 )
		cudaFree(b->selected);
	if ( b->sorted_pairs != 0 )
		cudaFree(b->sorted_pairs);
	if ( b->expert_offsets != 0 )
		cudaFree(b->expert_offsets);
	if ( b->expert_counts != 0 )
		cudaFree(b->expert_counts);
	if ( b->gate_ptrs != 0 )
		cudaFree(b->gate_ptrs);
	if ( b->up_ptrs != 0 )
		cudaFree(b->up_ptrs);
	if ( b->down_ptrs != 0 )
		cudaFree(b->down_ptrs);
	if ( b->host_gate_ptrs != 0 )
		cudaFreeHost((void *)b->host_gate_ptrs);
	if ( b->host_up_ptrs != 0 )
		cudaFreeHost((void *)b->host_up_ptrs);
	if ( b->host_down_ptrs != 0 )
		cudaFreeHost((void *)b->host_down_ptrs);
	if ( b->host_selected != 0 )
		cudaFreeHost((void *)b->host_selected);
	if ( b->host_sorted_pairs != 0 )
		cudaFreeHost((void *)b->host_sorted_pairs);
	if ( b->host_expert_offsets != 0 )
		cudaFreeHost((void *)b->host_expert_offsets);
	if ( b->host_expert_counts != 0 )
		cudaFreeHost((void *)b->host_expert_counts);
	if ( b->host_expert_write != 0 )
		cudaFreeHost((void *)b->host_expert_write);
	ds4_expert_dummy_zero(b);
}

static ds4_cuda_status_t ds4_expert_dummy_alloc(ds4_expert_dummy_buffers_t *b,const ds4_cuda_expert_queue_dummy_config_t *cfg)
{
	int64_t x_bytes,gate_bytes,down_bytes,mid_bytes,out_bytes,selected_bytes,ptr_bytes,count_bytes,offset_bytes;
	cudaError_t err;
	if ( ds4_expert_dummy_bytes(cfg,&x_bytes,&gate_bytes,&down_bytes,&mid_bytes,&out_bytes,&selected_bytes,&ptr_bytes) < 0 )
		return(ds4_cuda_fail(DS4_CUDA_ERR_INVALID_ARG));
	count_bytes = (int64_t)cfg->n_experts * (int64_t)sizeof(int32_t);
	offset_bytes = ((int64_t)cfg->n_experts + 1) * (int64_t)sizeof(int32_t);
	if ( ds4_cuda_i64_fits_size(x_bytes) == 0 || ds4_cuda_i64_fits_size(gate_bytes) == 0 || ds4_cuda_i64_fits_size(down_bytes) == 0 || ds4_cuda_i64_fits_size(mid_bytes) == 0 || ds4_cuda_i64_fits_size(out_bytes) == 0 || ds4_cuda_i64_fits_size(selected_bytes) == 0 || ds4_cuda_i64_fits_size(ptr_bytes) == 0 || ds4_cuda_i64_fits_size(count_bytes) == 0 || ds4_cuda_i64_fits_size(offset_bytes) == 0 )
		return(ds4_cuda_fail(DS4_CUDA_ERR_SIZE_OVERFLOW));
	err = cudaMalloc((void **)&b->x,(size_t)x_bytes);
	if ( err != cudaSuccess )
		return(ds4_cuda_fail((int32_t)err));
	err = cudaMalloc((void **)&b->gate,(size_t)gate_bytes);
	if ( err != cudaSuccess )
		return(ds4_cuda_fail((int32_t)err));
	err = cudaMalloc((void **)&b->up,(size_t)gate_bytes);
	if ( err != cudaSuccess )
		return(ds4_cuda_fail((int32_t)err));
	err = cudaMalloc((void **)&b->down,(size_t)down_bytes);
	if ( err != cudaSuccess )
		return(ds4_cuda_fail((int32_t)err));
	err = cudaMalloc((void **)&b->mid,(size_t)mid_bytes);
	if ( err != cudaSuccess )
		return(ds4_cuda_fail((int32_t)err));
	err = cudaMalloc((void **)&b->out,(size_t)out_bytes);
	if ( err != cudaSuccess )
		return(ds4_cuda_fail((int32_t)err));
	err = cudaMalloc((void **)&b->selected,(size_t)selected_bytes);
	if ( err != cudaSuccess )
		return(ds4_cuda_fail((int32_t)err));
	err = cudaMalloc((void **)&b->sorted_pairs,(size_t)selected_bytes);
	if ( err != cudaSuccess )
		return(ds4_cuda_fail((int32_t)err));
	err = cudaMalloc((void **)&b->expert_offsets,(size_t)offset_bytes);
	if ( err != cudaSuccess )
		return(ds4_cuda_fail((int32_t)err));
	err = cudaMalloc((void **)&b->expert_counts,(size_t)count_bytes);
	if ( err != cudaSuccess )
		return(ds4_cuda_fail((int32_t)err));
	err = cudaMalloc((void **)&b->gate_ptrs,(size_t)ptr_bytes);
	if ( err != cudaSuccess )
		return(ds4_cuda_fail((int32_t)err));
	err = cudaMalloc((void **)&b->up_ptrs,(size_t)ptr_bytes);
	if ( err != cudaSuccess )
		return(ds4_cuda_fail((int32_t)err));
	err = cudaMalloc((void **)&b->down_ptrs,(size_t)ptr_bytes);
	if ( err != cudaSuccess )
		return(ds4_cuda_fail((int32_t)err));
	err = cudaMallocHost((void **)&b->host_gate_ptrs,(size_t)ptr_bytes);
	if ( err != cudaSuccess )
		return(ds4_cuda_fail((int32_t)err));
	err = cudaMallocHost((void **)&b->host_up_ptrs,(size_t)ptr_bytes);
	if ( err != cudaSuccess )
		return(ds4_cuda_fail((int32_t)err));
	err = cudaMallocHost((void **)&b->host_down_ptrs,(size_t)ptr_bytes);
	if ( err != cudaSuccess )
		return(ds4_cuda_fail((int32_t)err));
	err = cudaMallocHost((void **)&b->host_selected,(size_t)selected_bytes);
	if ( err != cudaSuccess )
		return(ds4_cuda_fail((int32_t)err));
	err = cudaMallocHost((void **)&b->host_sorted_pairs,(size_t)selected_bytes);
	if ( err != cudaSuccess )
		return(ds4_cuda_fail((int32_t)err));
	err = cudaMallocHost((void **)&b->host_expert_offsets,(size_t)offset_bytes);
	if ( err != cudaSuccess )
		return(ds4_cuda_fail((int32_t)err));
	err = cudaMallocHost((void **)&b->host_expert_counts,(size_t)count_bytes);
	if ( err != cudaSuccess )
		return(ds4_cuda_fail((int32_t)err));
	err = cudaMallocHost((void **)&b->host_expert_write,(size_t)count_bytes);
	if ( err != cudaSuccess )
		return(ds4_cuda_fail((int32_t)err));
	return(ds4_cuda_ok());
}

static ds4_cuda_status_t ds4_expert_dummy_prepare(ds4_expert_dummy_buffers_t *b,const ds4_cuda_expert_queue_dummy_config_t *cfg)
{
	int64_t x_bytes,gate_bytes,down_bytes,mid_bytes,out_bytes,selected_bytes,ptr_bytes,count_bytes,offset_bytes;
	int32_t i,pairs,threads,blocks,expert;
	ds4_cuda_status_t st;
	cudaError_t err;
	pairs = (cfg->tokens * cfg->topk);
	if ( ds4_expert_dummy_bytes(cfg,&x_bytes,&gate_bytes,&down_bytes,&mid_bytes,&out_bytes,&selected_bytes,&ptr_bytes) < 0 )
		return(ds4_cuda_fail(DS4_CUDA_ERR_INVALID_ARG));
	for (i=0; i<cfg->n_experts; i++)
	{
		b->host_gate_ptrs[i] = b->gate + ((int64_t)i * (int64_t)cfg->mid_dim * (int64_t)cfg->hidden_dim);
		b->host_up_ptrs[i] = b->up + ((int64_t)i * (int64_t)cfg->mid_dim * (int64_t)cfg->hidden_dim);
		b->host_down_ptrs[i] = b->down + ((int64_t)i * (int64_t)cfg->out_dim * (int64_t)cfg->mid_dim);
	}
	for (i=0; i<pairs; i++)
		b->host_selected[i] = (int32_t)(((uint32_t)i * 37u + cfg->seed) % (uint32_t)cfg->route_experts);
	count_bytes = (int64_t)cfg->n_experts * (int64_t)sizeof(int32_t);
	offset_bytes = ((int64_t)cfg->n_experts + 1) * (int64_t)sizeof(int32_t);
	for (i=0; i<cfg->n_experts; i++)
		b->host_expert_counts[i] = 0;
	for (i=0; i<pairs; i++)
	{
		expert = b->host_selected[i];
		if ( expert < 0 || expert >= cfg->n_experts )
			return(ds4_cuda_fail(DS4_CUDA_ERR_INVALID_ARG));
		b->host_expert_counts[expert]++;
	}
	b->host_expert_offsets[0] = 0;
	for (i=0; i<cfg->n_experts; i++)
	{
		b->host_expert_offsets[i + 1] = b->host_expert_offsets[i] + b->host_expert_counts[i];
		b->host_expert_write[i] = b->host_expert_offsets[i];
	}
	for (i=0; i<pairs; i++)
	{
		expert = b->host_selected[i];
		b->host_sorted_pairs[b->host_expert_write[expert]] = i;
		b->host_expert_write[expert]++;
	}
	err = cudaMemcpy(b->gate_ptrs,b->host_gate_ptrs,(size_t)ptr_bytes,cudaMemcpyHostToDevice);
	if ( err != cudaSuccess )
		return(ds4_cuda_fail((int32_t)err));
	err = cudaMemcpy(b->up_ptrs,b->host_up_ptrs,(size_t)ptr_bytes,cudaMemcpyHostToDevice);
	if ( err != cudaSuccess )
		return(ds4_cuda_fail((int32_t)err));
	err = cudaMemcpy(b->down_ptrs,b->host_down_ptrs,(size_t)ptr_bytes,cudaMemcpyHostToDevice);
	if ( err != cudaSuccess )
		return(ds4_cuda_fail((int32_t)err));
	err = cudaMemcpy(b->selected,b->host_selected,(size_t)selected_bytes,cudaMemcpyHostToDevice);
	if ( err != cudaSuccess )
		return(ds4_cuda_fail((int32_t)err));
	err = cudaMemcpy(b->sorted_pairs,b->host_sorted_pairs,(size_t)selected_bytes,cudaMemcpyHostToDevice);
	if ( err != cudaSuccess )
		return(ds4_cuda_fail((int32_t)err));
	err = cudaMemcpy(b->expert_offsets,b->host_expert_offsets,(size_t)offset_bytes,cudaMemcpyHostToDevice);
	if ( err != cudaSuccess )
		return(ds4_cuda_fail((int32_t)err));
	err = cudaMemcpy(b->expert_counts,b->host_expert_counts,(size_t)count_bytes,cudaMemcpyHostToDevice);
	if ( err != cudaSuccess )
		return(ds4_cuda_fail((int32_t)err));
	threads = 256;
	blocks = (int32_t)((x_bytes / (int64_t)sizeof(float) + threads - 1) / threads);
	st = DS4_CUDA_KERNEL_LAUNCH(ds4_expert_dummy_init_float_kernel<<<blocks,threads>>>(b->x,x_bytes / (int64_t)sizeof(float),cfg->seed ^ 0x11u));
	if ( ds4_cuda_is_ok(st) == 0 )
		return(st);
	blocks = (int32_t)((gate_bytes / (int64_t)sizeof(float) + threads - 1) / threads);
	st = DS4_CUDA_KERNEL_LAUNCH(ds4_expert_dummy_init_float_kernel<<<blocks,threads>>>(b->gate,gate_bytes / (int64_t)sizeof(float),cfg->seed ^ 0x22u));
	if ( ds4_cuda_is_ok(st) == 0 )
		return(st);
	st = DS4_CUDA_KERNEL_LAUNCH(ds4_expert_dummy_init_float_kernel<<<blocks,threads>>>(b->up,gate_bytes / (int64_t)sizeof(float),cfg->seed ^ 0x33u));
	if ( ds4_cuda_is_ok(st) == 0 )
		return(st);
	blocks = (int32_t)((down_bytes / (int64_t)sizeof(float) + threads - 1) / threads);
	st = DS4_CUDA_KERNEL_LAUNCH(ds4_expert_dummy_init_float_kernel<<<blocks,threads>>>(b->down,down_bytes / (int64_t)sizeof(float),cfg->seed ^ 0x44u));
	if ( ds4_cuda_is_ok(st) == 0 )
		return(st);
	return(ds4_cuda_device_synchronize());
}

static ds4_cuda_status_t ds4_expert_dummy_launch_gateup(ds4_expert_dummy_buffers_t *b,const ds4_cuda_expert_queue_dummy_config_t *cfg)
{
	dim3 grid,block;
	block = dim3(128,1,1);
	grid = dim3((unsigned int)((cfg->mid_dim + 127) / 128),(unsigned int)(cfg->tokens * cfg->topk),1);
	return(DS4_CUDA_KERNEL_LAUNCH(ds4_expert_dummy_gateup_kernel<<<grid,block>>>(b->mid,b->x,b->gate_ptrs,b->up_ptrs,b->selected,cfg->tokens,cfg->topk,cfg->hidden_dim,cfg->mid_dim)));
}

static ds4_cuda_status_t ds4_expert_dummy_launch_down(ds4_expert_dummy_buffers_t *b,const ds4_cuda_expert_queue_dummy_config_t *cfg)
{
	dim3 grid,block;
	block = dim3(128,1,1);
	grid = dim3((unsigned int)((cfg->out_dim + 127) / 128),(unsigned int)cfg->tokens,1);
	return(DS4_CUDA_KERNEL_LAUNCH(ds4_expert_dummy_down_kernel<<<grid,block>>>(b->out,b->mid,b->down_ptrs,b->selected,cfg->tokens,cfg->topk,cfg->mid_dim,cfg->out_dim)));
}

static int32_t ds4_expert_dummy_max_queue(const ds4_expert_dummy_buffers_t *b,const ds4_cuda_expert_queue_dummy_config_t *cfg)
{
	int32_t i,maxq;
	maxq = 0;
	if ( b == 0 || cfg == 0 || b->host_expert_counts == 0 )
		return(0);
	for (i=0; i<cfg->n_experts; i++)
	{
		if ( b->host_expert_counts[i] > maxq )
			maxq = b->host_expert_counts[i];
	}
	return(maxq);
}

static void ds4_expert_dummy_queue_stats(const ds4_expert_dummy_buffers_t *b,const ds4_cuda_expert_queue_dummy_config_t *cfg,int32_t *active,int32_t *maxq,float *meanq)
{
	int32_t i,a,m,total;
	a = 0;
	m = 0;
	total = 0;
	if ( active != 0 )
		*active = 0;
	if ( maxq != 0 )
		*maxq = 0;
	if ( meanq != 0 )
		*meanq = 0.0f;
	if ( b == 0 || cfg == 0 || b->host_expert_counts == 0 )
		return;
	for (i=0; i<cfg->n_experts; i++)
	{
		if ( b->host_expert_counts[i] > 0 )
		{
			a++;
			total += b->host_expert_counts[i];
			if ( b->host_expert_counts[i] > m )
				m = b->host_expert_counts[i];
		}
	}
	if ( active != 0 )
		*active = a;
	if ( maxq != 0 )
		*maxq = m;
	if ( meanq != 0 && a > 0 )
		*meanq = ((float)total / (float)a);
}

static ds4_cuda_status_t ds4_expert_dummy_launch_gateup_sorted(ds4_expert_dummy_buffers_t *b,const ds4_cuda_expert_queue_dummy_config_t *cfg)
{
	dim3 grid,block;
	int32_t maxq;
	maxq = ds4_expert_dummy_max_queue(b,cfg);
	if ( maxq <= 0 )
		return(ds4_cuda_fail(DS4_CUDA_ERR_INVALID_ARG));
	block = dim3(128,1,1);
	grid = dim3((unsigned int)((cfg->mid_dim + 127) / 128),(unsigned int)cfg->route_experts,(unsigned int)maxq);
	return(DS4_CUDA_KERNEL_LAUNCH(ds4_expert_dummy_gateup_sorted_kernel<<<grid,block>>>(b->mid,b->x,b->gate_ptrs,b->up_ptrs,b->sorted_pairs,b->expert_offsets,b->expert_counts,cfg->tokens,cfg->topk,cfg->hidden_dim,cfg->mid_dim)));
}

static ds4_cuda_status_t ds4_expert_dummy_launch_down_sorted(ds4_expert_dummy_buffers_t *b,const ds4_cuda_expert_queue_dummy_config_t *cfg)
{
	dim3 grid,block;
	ds4_cuda_status_t st;
	int32_t maxq;
	maxq = ds4_expert_dummy_max_queue(b,cfg);
	if ( maxq <= 0 )
		return(ds4_cuda_fail(DS4_CUDA_ERR_INVALID_ARG));
	st = ds4_cuda_memset(b->out,0,(int64_t)cfg->tokens * (int64_t)cfg->out_dim * (int64_t)sizeof(float));
	if ( ds4_cuda_is_ok(st) == 0 )
		return(st);
	block = dim3(128,1,1);
	grid = dim3((unsigned int)((cfg->out_dim + 127) / 128),(unsigned int)cfg->route_experts,(unsigned int)maxq);
	return(DS4_CUDA_KERNEL_LAUNCH(ds4_expert_dummy_down_sorted_kernel<<<grid,block>>>(b->out,b->mid,b->down_ptrs,b->sorted_pairs,b->expert_offsets,b->expert_counts,cfg->tokens,cfg->topk,cfg->mid_dim,cfg->out_dim)));
}

static ds4_cuda_status_t ds4_expert_dummy_measure(float *gateup_ms,float *down_ms,ds4_expert_dummy_buffers_t *b,const ds4_cuda_expert_queue_dummy_config_t *cfg)
{
	ds4_cuda_event_t a,beg,end;
	ds4_cuda_status_t st;
	int32_t i;
	*gateup_ms = 0.0f;
	*down_ms = 0.0f;
	a.h = 0;
	beg.h = 0;
	end.h = 0;
	if ( cfg->sorted != 0 )
		st = ds4_expert_dummy_launch_gateup_sorted(b,cfg);
	else
		st = ds4_expert_dummy_launch_gateup(b,cfg);
	if ( ds4_cuda_is_ok(st) != 0 )
	{
		if ( cfg->sorted != 0 )
			st = ds4_expert_dummy_launch_down_sorted(b,cfg);
		else
			st = ds4_expert_dummy_launch_down(b,cfg);
	}
	if ( ds4_cuda_is_ok(st) != 0 )
		st = ds4_cuda_device_synchronize();
	if ( ds4_cuda_is_ok(st) != 0 )
		st = ds4_cuda_event_create(&a,DS4_CUDA_EVENT_FLAGS_DEFAULT);
	if ( ds4_cuda_is_ok(st) != 0 )
		st = ds4_cuda_event_create(&beg,DS4_CUDA_EVENT_FLAGS_DEFAULT);
	if ( ds4_cuda_is_ok(st) != 0 )
		st = ds4_cuda_event_create(&end,DS4_CUDA_EVENT_FLAGS_DEFAULT);
	if ( ds4_cuda_is_ok(st) != 0 )
		st = ds4_cuda_event_record(a,(ds4_cuda_stream_t){0});
	for (i=0; ds4_cuda_is_ok(st) != 0 && i<cfg->iterations; i++)
	{
		if ( cfg->sorted != 0 )
			st = ds4_expert_dummy_launch_gateup_sorted(b,cfg);
		else
			st = ds4_expert_dummy_launch_gateup(b,cfg);
	}
	if ( ds4_cuda_is_ok(st) != 0 )
		st = ds4_cuda_event_record(beg,(ds4_cuda_stream_t){0});
	if ( ds4_cuda_is_ok(st) != 0 )
		st = ds4_cuda_event_synchronize(beg);
	if ( ds4_cuda_is_ok(st) != 0 )
		st = ds4_cuda_event_elapsed_ms(gateup_ms,a,beg);
	if ( ds4_cuda_is_ok(st) != 0 )
		st = ds4_cuda_event_record(a,(ds4_cuda_stream_t){0});
	for (i=0; ds4_cuda_is_ok(st) != 0 && i<cfg->iterations; i++)
	{
		if ( cfg->sorted != 0 )
			st = ds4_expert_dummy_launch_down_sorted(b,cfg);
		else
			st = ds4_expert_dummy_launch_down(b,cfg);
	}
	if ( ds4_cuda_is_ok(st) != 0 )
		st = ds4_cuda_event_record(end,(ds4_cuda_stream_t){0});
	if ( ds4_cuda_is_ok(st) != 0 )
		st = ds4_cuda_event_synchronize(end);
	if ( ds4_cuda_is_ok(st) != 0 )
		st = ds4_cuda_event_elapsed_ms(down_ms,a,end);
	if ( a.h != 0 )
		ds4_cuda_event_destroy(&a);
	if ( beg.h != 0 )
		ds4_cuda_event_destroy(&beg);
	if ( end.h != 0 )
		ds4_cuda_event_destroy(&end);
	return(st);
}

void ds4_cuda_expert_queue_dummy_default_config(ds4_cuda_expert_queue_dummy_config_t *out)
{
	if ( out == 0 )
		return;
	out->tokens = 32;
	out->topk = 6;
	out->n_experts = 256;
	out->route_experts = 256;
	out->hidden_dim = 128;
	out->mid_dim = 256;
	out->out_dim = 128;
	out->iterations = 8;
	out->sorted = 0;
	out->seed = 1234u;
}

ds4_cuda_status_t ds4_cuda_expert_queue_dummy_run(const ds4_cuda_expert_queue_dummy_config_t *cfg,ds4_cuda_expert_queue_dummy_result_t *out)
{
	ds4_cuda_expert_queue_dummy_config_t c;
	ds4_expert_dummy_buffers_t b;
	ds4_cuda_status_t st;
	int64_t x_bytes,gate_bytes,down_bytes,mid_bytes,out_bytes,selected_bytes,ptr_bytes,move_bytes;
	float gateup_ms,down_ms,total_ms;
	int32_t active_experts,max_queue_depth;
	float mean_queue_depth;
	if ( cfg == 0 || out == 0 )
		return(ds4_cuda_fail(DS4_CUDA_ERR_INVALID_ARG));
	c = *cfg;
	if ( c.route_experts <= 0 )
		c.route_experts = c.n_experts;
	if ( c.sorted != 0 )
		c.sorted = 1;
	out->tokens = 0;
	out->topk = 0;
	out->n_experts = 0;
	out->route_experts = 0;
	out->hidden_dim = 0;
	out->mid_dim = 0;
	out->out_dim = 0;
	out->iterations = 0;
	out->sorted = 0;
	out->active_experts = 0;
	out->max_queue_depth = 0;
	out->estimated_bytes_moved = 0;
	out->mean_queue_depth = 0.0f;
	out->gateup_ms = 0.0f;
	out->down_ms = 0.0f;
	out->total_ms = 0.0f;
	out->tokens_per_s = 0.0f;
	out->expert_pairs_per_s = 0.0f;
	out->estimated_gib_per_s = 0.0f;
	if ( ds4_expert_dummy_bytes(&c,&x_bytes,&gate_bytes,&down_bytes,&mid_bytes,&out_bytes,&selected_bytes,&ptr_bytes) < 0 )
		return(ds4_cuda_fail(DS4_CUDA_ERR_INVALID_ARG));
	st = ds4_cuda_init();
	ds4_expert_dummy_zero(&b);
	active_experts = 0;
	max_queue_depth = 0;
	mean_queue_depth = 0.0f;
	if ( ds4_cuda_is_ok(st) != 0 )
		st = ds4_expert_dummy_alloc(&b,&c);
	if ( ds4_cuda_is_ok(st) != 0 )
		st = ds4_expert_dummy_prepare(&b,&c);
	if ( ds4_cuda_is_ok(st) != 0 )
		ds4_expert_dummy_queue_stats(&b,&c,&active_experts,&max_queue_depth,&mean_queue_depth);
	if ( ds4_cuda_is_ok(st) != 0 )
		st = ds4_expert_dummy_measure(&gateup_ms,&down_ms,&b,&c);
	ds4_expert_dummy_free(&b);
	if ( ds4_cuda_is_ok(st) == 0 )
		return(st);
	move_bytes = ((int64_t)c.tokens * (int64_t)c.topk * (int64_t)c.mid_dim * (int64_t)c.hidden_dim * (int64_t)sizeof(float) * 3);
	move_bytes += ((int64_t)c.tokens * (int64_t)c.topk * (int64_t)c.out_dim * (int64_t)c.mid_dim * (int64_t)sizeof(float));
	move_bytes *= (int64_t)c.iterations;
	total_ms = (gateup_ms + down_ms);
	out->tokens = c.tokens;
	out->topk = c.topk;
	out->n_experts = c.n_experts;
	out->route_experts = c.route_experts;
	out->hidden_dim = c.hidden_dim;
	out->mid_dim = c.mid_dim;
	out->out_dim = c.out_dim;
	out->iterations = c.iterations;
	out->sorted = c.sorted;
	out->active_experts = active_experts;
	out->max_queue_depth = max_queue_depth;
	out->estimated_bytes_moved = move_bytes;
	out->mean_queue_depth = mean_queue_depth;
	out->gateup_ms = gateup_ms;
	out->down_ms = down_ms;
	out->total_ms = total_ms;
	if ( total_ms > 0.0f )
	{
		out->tokens_per_s = (((float)c.tokens * (float)c.iterations * 1000.0f) / total_ms);
		out->expert_pairs_per_s = (((float)c.tokens * (float)c.topk * (float)c.iterations * 1000.0f) / total_ms);
		out->estimated_gib_per_s = ((float)((double)move_bytes / (1024.0 * 1024.0 * 1024.0)) * 1000.0f / total_ms);
	}
	return(ds4_cuda_ok());
}

ds4_cuda_status_t ds4_cuda_memset_async(void *dst,int32_t value,int64_t bytes,ds4_cuda_stream_t s)
{
	cudaError_t err;
	cudaStream_t stream;
	if ( bytes < 0 )
		return(ds4_cuda_fail(DS4_CUDA_ERR_INVALID_ARG));
	if ( bytes == 0 )
		return(ds4_cuda_ok());
	if ( dst == 0 )
		return(ds4_cuda_fail(DS4_CUDA_ERR_INVALID_ARG));
	if ( ds4_cuda_i64_fits_size(bytes) == 0 )
		return(ds4_cuda_fail(DS4_CUDA_ERR_SIZE_OVERFLOW));
	stream = (cudaStream_t)s.h;
	err = cudaMemsetAsync(dst,value,(size_t)bytes,stream);
	if ( err != cudaSuccess )
		return(ds4_cuda_fail((int32_t)err));
	return(ds4_cuda_ok());
}

ds4_cuda_status_t ds4_cuda_memcpy_h2d_async(void *dst,const void *src,int64_t bytes,ds4_cuda_stream_t s)
{
	cudaError_t err;
	cudaStream_t stream;
	if ( bytes < 0 )
		return(ds4_cuda_fail(DS4_CUDA_ERR_INVALID_ARG));
	if ( bytes == 0 )
		return(ds4_cuda_ok());
	if ( dst == 0 )
		return(ds4_cuda_fail(DS4_CUDA_ERR_INVALID_ARG));
	if ( src == 0 )
		return(ds4_cuda_fail(DS4_CUDA_ERR_INVALID_ARG));
	if ( ds4_cuda_i64_fits_size(bytes) == 0 )
		return(ds4_cuda_fail(DS4_CUDA_ERR_SIZE_OVERFLOW));
	stream = (cudaStream_t)s.h;
	err = cudaMemcpyAsync(dst,src,(size_t)bytes,cudaMemcpyHostToDevice,stream);
	if ( err != cudaSuccess )
		return(ds4_cuda_fail((int32_t)err));
	return(ds4_cuda_ok());
}

ds4_cuda_status_t ds4_cuda_memcpy_d2h_async(void *dst,const void *src,int64_t bytes,ds4_cuda_stream_t s)
{
	cudaError_t err;
	cudaStream_t stream;
	if ( bytes < 0 )
		return(ds4_cuda_fail(DS4_CUDA_ERR_INVALID_ARG));
	if ( bytes == 0 )
		return(ds4_cuda_ok());
	if ( dst == 0 )
		return(ds4_cuda_fail(DS4_CUDA_ERR_INVALID_ARG));
	if ( src == 0 )
		return(ds4_cuda_fail(DS4_CUDA_ERR_INVALID_ARG));
	if ( ds4_cuda_i64_fits_size(bytes) == 0 )
		return(ds4_cuda_fail(DS4_CUDA_ERR_SIZE_OVERFLOW));
	stream = (cudaStream_t)s.h;
	err = cudaMemcpyAsync(dst,src,(size_t)bytes,cudaMemcpyDeviceToHost,stream);
	if ( err != cudaSuccess )
		return(ds4_cuda_fail((int32_t)err));
	return(ds4_cuda_ok());
}

}
#else
#error "ds4_cuda.cu must only compile when DS4_HAS_CUDA=1"
#endif
