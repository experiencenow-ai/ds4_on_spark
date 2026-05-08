#pragma once

#include <stdint.h>

typedef struct
{
	uint8_t *base;
	int32_t size,used;
} ds4_arena_t;

int32_t ds4_arena_init(ds4_arena_t *a,uint8_t *mem,int32_t size);
int32_t ds4_arena_alloc(ds4_arena_t *a,int32_t size,int32_t align,void **out);
