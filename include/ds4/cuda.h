#pragma once

#include <stdint.h>

#define DS4_CUDA_ERR_DISABLED (-1)

typedef struct
{
	int32_t code;
} ds4_cuda_status_t;

#ifdef __cplusplus
extern "C" {
#endif

ds4_cuda_status_t ds4_cuda_ok(void);
ds4_cuda_status_t ds4_cuda_fail(int32_t code);
int32_t ds4_cuda_is_ok(ds4_cuda_status_t st);
const char *ds4_cuda_errstr(ds4_cuda_status_t st);
ds4_cuda_status_t ds4_cuda_last_error(void);
ds4_cuda_status_t ds4_cuda_peek_last_error(void);
ds4_cuda_status_t ds4_cuda_device_synchronize(void);
ds4_cuda_status_t ds4_cuda_check_i32(int32_t cuda_err,const char *expr,const char *file,int32_t line);

#ifdef __cplusplus
}
#endif

#if defined(DS4_HAS_CUDA)
#define DS4_CUDA_CALL(expr) ds4_cuda_check_i32((int32_t)(expr),#expr,__FILE__,(int32_t)__LINE__)
#endif
