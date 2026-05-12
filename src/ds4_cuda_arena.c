#include "ds4/cuda_arena.h"

#include <stdint.h>

static int32_t ds4_is_pow2_i32(int32_t x)
{
	if ( x <= 0 )
		return(0);
	if ( (x & (x - 1)) != 0 )
		return(0);
	return(1);
}

static int32_t ds4_align_up_i64(int64_t x,int32_t a,int64_t *out)
{
	int64_t m,mask,r;
	if ( out == 0 )
		return(-1);
	if ( a <= 1 )
	{
		*out = x;
		return(0);
	}
	if ( x < 0 )
		return(-2);
	m = (int64_t)(a - 1);
	mask = ~m;
	r = ((x + m) & mask);
	*out = r;
	return(0);
}

int32_t ds4_cuda_arena_init(ds4_cuda_arena_t *a,void *base,int64_t size)
{
	if ( a == 0 )
		return(-1);
	if ( base == 0 )
		return(-2);
	if ( size <= 0 )
		return(-3);
	a->base = (uint8_t *)base;
	a->size = size;
	a->used = 0;
	a->owns_base = 0;
	return(0);
}

int32_t ds4_cuda_arena_init_malloc(ds4_cuda_arena_t *a,int64_t size)
{
	ds4_cuda_status_t st;
	void *base;
	if ( a == 0 )
		return(-1);
	if ( size <= 0 )
		return(-2);
	base = 0;
	st = ds4_cuda_malloc(&base,size);
	if ( ds4_cuda_is_ok(st) == 0 )
		return(st.code);
	a->base = (uint8_t *)base;
	a->size = size;
	a->used = 0;
	a->owns_base = 1;
	return(0);
}

int32_t ds4_cuda_arena_deinit(ds4_cuda_arena_t *a)
{
	ds4_cuda_status_t st;
	if ( a == 0 )
		return(-1);
	if ( a->owns_base != 0 && a->base != 0 )
	{
		st = ds4_cuda_free(a->base);
		if ( ds4_cuda_is_ok(st) == 0 )
			return(st.code);
	}
	a->base = 0;
	a->size = 0;
	a->used = 0;
	a->owns_base = 0;
	return(0);
}

int32_t ds4_cuda_arena_reset(ds4_cuda_arena_t *a)
{
	if ( a == 0 )
		return(-1);
	a->used = 0;
	return(0);
}

int32_t ds4_cuda_arena_alloc(ds4_cuda_arena_t *a,int64_t size,int32_t align,void **out)
{
	int64_t used2,used3;
	if ( a == 0 )
		return(-1);
	if ( out == 0 )
		return(-2);
	if ( a->base == 0 )
		return(-3);
	if ( a->size <= 0 )
		return(-4);
	if ( size <= 0 )
		return(-5);
	if ( align <= 0 )
		align = DS4_CUDA_ARENA_ALIGN_DEFAULT;
	if ( ds4_is_pow2_i32(align) == 0 )
		return(-6);
	if ( ds4_align_up_i64(a->used,align,&used2) < 0 )
		return(-7);
	if ( (used2 < 0) || (used2 > a->size) )
		return(-8);
	if ( (a->size - used2) < size )
		return(-9);
	*out = (void *)(a->base + used2);
	used3 = (used2 + size);
	if ( used3 < used2 )
		return(-10);
	if ( used3 > a->size )
		return(-11);
	a->used = used3;
	return(0);
}

int32_t ds4_cuda_arena_alloc_n(ds4_cuda_arena_t *a,int64_t count,int64_t elem_size,int32_t align,void **out)
{
	int64_t bytes;
	if ( a == 0 )
		return(-1);
	if ( out == 0 )
		return(-2);
	if ( count <= 0 )
		return(-3);
	if ( elem_size <= 0 )
		return(-4);
	if ( count > (INT64_MAX / elem_size) )
		return(-5);
	bytes = (count * elem_size);
	if ( bytes <= 0 )
		return(-6);
	if ( ds4_cuda_arena_alloc(a,bytes,align,out) < 0 )
		return(-7);
	return(0);
}

int32_t ds4_cuda_arena_alloc_zero(ds4_cuda_arena_t *a,int64_t size,int32_t align,void **out)
{
	ds4_cuda_status_t st;
	void *p;
	int64_t used0;
	if ( a == 0 )
		return(-1);
	if ( out == 0 )
		return(-2);
	*out = 0;
	if ( ds4_cuda_is_enabled_build() == 0 )
		return(DS4_CUDA_ERR_DISABLED);
	used0 = a->used;
	p = 0;
	if ( ds4_cuda_arena_alloc(a,size,align,&p) < 0 )
		return(-3);
	if ( p == 0 )
	{
		a->used = used0;
		return(-4);
	}
	st = ds4_cuda_memset(p,0,size);
	if ( ds4_cuda_is_ok(st) == 0 )
	{
		a->used = used0;
		return(st.code);
	}
	*out = p;
	return(0);
}

int32_t ds4_cuda_arena_alloc_zero_n(ds4_cuda_arena_t *a,int64_t count,int64_t elem_size,int32_t align,void **out)
{
	int64_t bytes;
	int32_t err;
	if ( a == 0 )
		return(-1);
	if ( out == 0 )
		return(-2);
	if ( count <= 0 )
		return(-3);
	if ( elem_size <= 0 )
		return(-4);
	if ( count > (INT64_MAX / elem_size) )
		return(-5);
	bytes = (count * elem_size);
	if ( bytes <= 0 )
		return(-6);
	err = ds4_cuda_arena_alloc_zero(a,bytes,align,out);
	if ( err != 0 )
		return(err);
	return(0);
}
