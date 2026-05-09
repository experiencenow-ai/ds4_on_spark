#pragma once

#include <stdint.h>

#define DS4_CUDA_ERR_DISABLED (-1)

typedef struct
{
	int32_t code;
} ds4_cuda_status_t;

ds4_cuda_status_t ds4_cuda_ok(void);
ds4_cuda_status_t ds4_cuda_fail(int32_t code);
int32_t ds4_cuda_is_ok(ds4_cuda_status_t st);
const char *ds4_cuda_errstr(ds4_cuda_status_t st);
ds4_cuda_status_t ds4_cuda_last_error(void);
