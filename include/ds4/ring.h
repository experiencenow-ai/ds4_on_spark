#pragma once

#include <stdint.h>

typedef struct
{
	uint8_t *base;
	int32_t elem_size,elem_count;
	int32_t head,tail,count;
} ds4_ring_t;

int32_t ds4_ring_init(ds4_ring_t *r,uint8_t *mem,int32_t elem_count,int32_t elem_size);
int32_t ds4_ring_reset(ds4_ring_t *r);
int32_t ds4_ring_count(ds4_ring_t *r,int32_t *out_count);
int32_t ds4_ring_capacity(ds4_ring_t *r,int32_t *out_cap);
int32_t ds4_ring_push(ds4_ring_t *r,const void *elem);
int32_t ds4_ring_pop(ds4_ring_t *r,void *out_elem);
