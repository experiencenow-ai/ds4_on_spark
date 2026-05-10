#pragma once

#include "ds4/common.h"

#define DS4_CUDA_ERR_DISABLED (-1)
#define DS4_CUDA_ERR_NO_DEVICE (-2)
#define DS4_CUDA_ERR_INVALID_ARG (-3)
#define DS4_CUDA_ERR_SIZE_OVERFLOW (-4)

typedef struct
{
	int32_t code;
} ds4_cuda_status_t;

typedef struct
{
	int32_t dev;
	int32_t major;
	int32_t minor;
	int32_t multiprocessor_count;
	int64_t total_global_mem;
	char name[128];
} ds4_cuda_device_info_t;

typedef struct
{
	void *h;
} ds4_cuda_stream_t;

typedef struct
{
	void *h;
} ds4_cuda_event_t;

#define DS4_CUDA_STREAM_FLAGS_DEFAULT 0

#define DS4_CUDA_EVENT_FLAGS_DEFAULT 0
#define DS4_CUDA_EVENT_FLAGS_DISABLE_TIMING 1

DS4_EXTERN_C_BEGIN
ds4_cuda_status_t ds4_cuda_ok(void);
ds4_cuda_status_t ds4_cuda_fail(int32_t code);
int32_t ds4_cuda_is_ok(ds4_cuda_status_t st);
int32_t ds4_cuda_is_enabled_build(void);
ds4_cuda_status_t ds4_cuda_init(void);
ds4_cuda_status_t ds4_cuda_get_device(int32_t *out_dev);
ds4_cuda_status_t ds4_cuda_set_device(int32_t dev);
const char *ds4_cuda_errstr(ds4_cuda_status_t st);
ds4_cuda_status_t ds4_cuda_last_error(void);
ds4_cuda_status_t ds4_cuda_peek_last_error(void);
ds4_cuda_status_t ds4_cuda_check_peek_last_error_ex(const char *expr,const char *file,int32_t line);
ds4_cuda_status_t ds4_cuda_device_synchronize(void);
ds4_cuda_status_t ds4_cuda_check_i32(int32_t cuda_err,const char *expr,const char *file,int32_t line);
ds4_cuda_status_t ds4_cuda_check_last_error(const char *file,int32_t line);
ds4_cuda_status_t ds4_cuda_check_peek_last_error(const char *file,int32_t line);
ds4_cuda_status_t ds4_cuda_device_count(int32_t *out_count);
ds4_cuda_status_t ds4_cuda_device_info(ds4_cuda_device_info_t *out,int32_t dev_index);
ds4_cuda_status_t ds4_cuda_stream_create(ds4_cuda_stream_t *out,int32_t flags);
ds4_cuda_status_t ds4_cuda_stream_destroy(ds4_cuda_stream_t *s);
ds4_cuda_status_t ds4_cuda_stream_synchronize(ds4_cuda_stream_t s);
ds4_cuda_status_t ds4_cuda_event_create(ds4_cuda_event_t *out,int32_t flags);
ds4_cuda_status_t ds4_cuda_event_destroy(ds4_cuda_event_t *e);
ds4_cuda_status_t ds4_cuda_event_record(ds4_cuda_event_t e,ds4_cuda_stream_t s);
ds4_cuda_status_t ds4_cuda_event_synchronize(ds4_cuda_event_t e);
ds4_cuda_status_t ds4_cuda_event_elapsed_ms(float *out_ms,ds4_cuda_event_t start,ds4_cuda_event_t end);
ds4_cuda_status_t ds4_cuda_malloc(void **out,int64_t bytes);
ds4_cuda_status_t ds4_cuda_free(void *ptr);
ds4_cuda_status_t ds4_cuda_malloc_host(void **out,int64_t bytes);
ds4_cuda_status_t ds4_cuda_free_host(void *ptr);
ds4_cuda_status_t ds4_cuda_memset(void *dst,int32_t value,int64_t bytes);
ds4_cuda_status_t ds4_cuda_memcpy_h2d(void *dst,const void *src,int64_t bytes);
ds4_cuda_status_t ds4_cuda_memcpy_d2h(void *dst,const void *src,int64_t bytes);
ds4_cuda_status_t ds4_cuda_memset_async(void *dst,int32_t value,int64_t bytes,ds4_cuda_stream_t s);
ds4_cuda_status_t ds4_cuda_memcpy_h2d_async(void *dst,const void *src,int64_t bytes,ds4_cuda_stream_t s);
ds4_cuda_status_t ds4_cuda_memcpy_d2h_async(void *dst,const void *src,int64_t bytes,ds4_cuda_stream_t s);
DS4_EXTERN_C_END

#define DS4_CUDA_CALL(expr) ds4_cuda_check_i32((int32_t)(expr),#expr,__FILE__,(int32_t)__LINE__)
#define DS4_CUDA_CHECK_LAST_ERROR() ds4_cuda_check_last_error(__FILE__,(int32_t)__LINE__)
#define DS4_CUDA_CHECK_PEEK_LAST_ERROR() ds4_cuda_check_peek_last_error(__FILE__,(int32_t)__LINE__)

#if defined(DS4_HAS_CUDA) && defined(__CUDACC__)
#define DS4_CUDA_KERNEL_LAUNCH(call) ((call),ds4_cuda_check_peek_last_error_ex(#call,__FILE__,(int32_t)__LINE__))
#endif
