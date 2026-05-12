#pragma once

#include "ds4/common.h"
#include "ds4/cuda.h"

#define DS4_CUDA_ARENA_ALIGN_DEFAULT 256

typedef struct
{
	uint8_t *base;
	int64_t size;
	int64_t used;
	int32_t owns_base;
} ds4_cuda_arena_t;

DS4_EXTERN_C_BEGIN
int32_t ds4_cuda_arena_init(ds4_cuda_arena_t *a,void *base,int64_t size);
int32_t ds4_cuda_arena_init_malloc(ds4_cuda_arena_t *a,int64_t size);
int32_t ds4_cuda_arena_deinit(ds4_cuda_arena_t *a);
int32_t ds4_cuda_arena_reset(ds4_cuda_arena_t *a);
int32_t ds4_cuda_arena_alloc(ds4_cuda_arena_t *a,int64_t size,int32_t align,void **out);
int32_t ds4_cuda_arena_alloc_n(ds4_cuda_arena_t *a,int64_t count,int64_t elem_size,int32_t align,void **out);
int32_t ds4_cuda_arena_alloc_zero(ds4_cuda_arena_t *a,int64_t size,int32_t align,void **out);
DS4_EXTERN_C_END
