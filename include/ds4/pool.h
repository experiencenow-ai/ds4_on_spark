#pragma once

#include "ds4/common.h"

typedef struct
{
	uint8_t *base;
	int32_t block_size,block_count;
	int32_t free_head;
} ds4_pool_t;

DS4_EXTERN_C_BEGIN
int32_t ds4_pool_bytes_needed(int32_t block_count,int32_t block_size,int32_t *out_bytes);
int32_t ds4_pool_init(ds4_pool_t *p,uint8_t *mem,int32_t mem_size,int32_t block_size);
int32_t ds4_pool_reset(ds4_pool_t *p);
int32_t ds4_pool_alloc(ds4_pool_t *p,void **out);
int32_t ds4_pool_alloc_zero(ds4_pool_t *p,void **out);
int32_t ds4_pool_free(ds4_pool_t *p,void *ptr);
int32_t ds4_pool_free_count(ds4_pool_t *p,int32_t *out);
int32_t ds4_pool_used_count(ds4_pool_t *p,int32_t *out);
DS4_EXTERN_C_END
