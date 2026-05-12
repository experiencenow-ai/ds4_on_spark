#pragma once

#include "ds4/common.h"

typedef struct
{
	uint8_t *base;
	int32_t size,used;
} ds4_arena_t;

DS4_EXTERN_C_BEGIN
int32_t ds4_arena_init(ds4_arena_t *a,uint8_t *mem,int32_t size);
int32_t ds4_arena_init_ex(ds4_arena_t *a,uint8_t *mem,int32_t size,int32_t align);
int32_t ds4_arena_reset(ds4_arena_t *a);
int32_t ds4_arena_mark(ds4_arena_t *a,int32_t *out_mark);
int32_t ds4_arena_release(ds4_arena_t *a,int32_t mark);
int32_t ds4_arena_alloc(ds4_arena_t *a,int32_t size,int32_t align,void **out);
int32_t ds4_arena_alloc_n(ds4_arena_t *a,int32_t count,int32_t elem_size,int32_t align,void **out);
int32_t ds4_arena_alloc_zero(ds4_arena_t *a,int32_t size,int32_t align,void **out);
int32_t ds4_arena_alloc_zero_n(ds4_arena_t *a,int32_t count,int32_t elem_size,int32_t align,void **out);
DS4_EXTERN_C_END
