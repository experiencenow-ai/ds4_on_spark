#include "ds4/arena.h"

#include <string.h>

static int32_t ds4_align_up_i32(int32_t x,int32_t a,int32_t *out)
{
	int32_t m;
	int64_t y,mask,r;
	if ( out == 0 )
		return(-1);
	if ( a <= 1 )
	{
		*out = x;
		return(0);
	}
	if ( x < 0 )
		return(-2);
	m = (a - 1);
	y = ((int64_t)x + (int64_t)m);
	if ( y > (int64_t)INT32_MAX )
		return(-3);
	mask = ~((int64_t)m);
	r = (y & mask);
	if ( r > (int64_t)INT32_MAX )
		return(-4);
	*out = (int32_t)r;
	return(0);
}

static int32_t ds4_is_pow2_i32(int32_t x)
{
	if ( x <= 0 )
		return(0);
	if ( (x & (x - 1)) != 0 )
		return(0);
	return(1);
}

static int32_t ds4_is_aligned_ptr(const void *p,int32_t align)
{
	uintptr_t v;
	if ( p == 0 )
		return(0);
	if ( align <= 1 )
		return(1);
	v = (uintptr_t)p;
	if ( (v & (uintptr_t)(align - 1)) != 0 )
		return(0);
	return(1);
}

int32_t ds4_arena_init(ds4_arena_t *a,uint8_t *mem,int32_t size)
{
	if ( a == 0 )
		return(-1);
	if ( mem == 0 )
		return(-2);
	if ( size <= 0 )
		return(-3);
	a->base = mem;
	a->size = size;
	a->used = 0;
	return(0);
}

int32_t ds4_arena_init_ex(ds4_arena_t *a,uint8_t *mem,int32_t size,int32_t align)
{
	if ( a == 0 )
		return(-1);
	if ( mem == 0 )
		return(-2);
	if ( size <= 0 )
		return(-3);
	if ( align <= 0 )
		align = 1;
	if ( ds4_is_pow2_i32(align) == 0 )
		return(-4);
	if ( ds4_is_aligned_ptr(mem,align) == 0 )
		return(-5);
	a->base = mem;
	a->size = size;
	a->used = 0;
	return(0);
}

int32_t ds4_arena_reset(ds4_arena_t *a)
{
	if ( a == 0 )
		return(-1);
	a->used = 0;
	return(0);
}

int32_t ds4_arena_mark(ds4_arena_t *a,int32_t *out_mark)
{
	if ( a == 0 )
		return(-1);
	if ( out_mark == 0 )
		return(-2);
	*out_mark = a->used;
	return(0);
}

int32_t ds4_arena_release(ds4_arena_t *a,int32_t mark)
{
	if ( a == 0 )
		return(-1);
	if ( mark < 0 )
		return(-2);
	if ( mark > a->size )
		return(-3);
	a->used = mark;
	return(0);
}

int32_t ds4_arena_validate(const ds4_arena_t *a)
{
	if ( a == 0 )
		return(-1);
	if ( a->base == 0 )
		return(-2);
	if ( a->size <= 0 )
		return(-3);
	if ( a->used < 0 )
		return(-4);
	if ( a->used > a->size )
		return(-5);
	return(0);
}

int32_t ds4_arena_bytes_left(const ds4_arena_t *a,int32_t *out_bytes)
{
	int32_t left;
	if ( out_bytes == 0 )
		return(-1);
	*out_bytes = 0;
	if ( ds4_arena_validate(a) < 0 )
		return(-2);
	left = (a->size - a->used);
	if ( left < 0 )
		return(-3);
	*out_bytes = left;
	return(0);
}

int32_t ds4_arena_alloc(ds4_arena_t *a,int32_t size,int32_t align,void **out)
{
	int32_t used2,used3;
	int64_t used3_64;
	if ( a == 0 )
		return(-1);
	if ( out == 0 )
		return(-2);
	if ( size <= 0 )
		return(-3);
	if ( align <= 0 )
		align = 1;
	if ( ds4_is_pow2_i32(align) == 0 )
		return(-4);
	if ( ds4_align_up_i32(a->used,align,&used2) < 0 )
		return(-5);
	if ( (used2 < 0) || (used2 > a->size) )
		return(-6);
	if ( (a->size - used2) < size )
		return(-7);
	*out = (void *)(a->base + used2);
	used3_64 = ((int64_t)used2 + (int64_t)size);
	if ( used3_64 > (int64_t)INT32_MAX )
		return(-8);
	used3 = (int32_t)used3_64;
	if ( used3 < 0 )
		return(-9);
	a->used = used3;
	return(0);
}

int32_t ds4_arena_alloc_n(ds4_arena_t *a,int32_t count,int32_t elem_size,int32_t align,void **out)
{
	int64_t bytes_64;
	int32_t bytes;
	if ( a == 0 )
		return(-1);
	if ( out == 0 )
		return(-2);
	if ( count <= 0 )
		return(-3);
	if ( elem_size <= 0 )
		return(-4);
	bytes_64 = ((int64_t)count * (int64_t)elem_size);
	if ( bytes_64 > (int64_t)INT32_MAX )
		return(-5);
	bytes = (int32_t)bytes_64;
	if ( bytes <= 0 )
		return(-6);
	if ( ds4_arena_alloc(a,bytes,align,out) < 0 )
		return(-7);
	return(0);
}

int32_t ds4_arena_alloc_zero(ds4_arena_t *a,int32_t size,int32_t align,void **out)
{
	void *p;
	if ( a == 0 )
		return(-1);
	if ( out == 0 )
		return(-2);
	if ( ds4_arena_alloc(a,size,align,&p) < 0 )
		return(-3);
	memset(p,0,(size_t)size);
	*out = p;
	return(0);
}

int32_t ds4_arena_alloc_zero_n(ds4_arena_t *a,int32_t count,int32_t elem_size,int32_t align,void **out)
{
	int64_t bytes_64;
	int32_t bytes;
	if ( a == 0 )
		return(-1);
	if ( out == 0 )
		return(-2);
	if ( count <= 0 )
		return(-3);
	if ( elem_size <= 0 )
		return(-4);
	bytes_64 = ((int64_t)count * (int64_t)elem_size);
	if ( bytes_64 > (int64_t)INT32_MAX )
		return(-5);
	bytes = (int32_t)bytes_64;
	if ( bytes <= 0 )
		return(-6);
	if ( ds4_arena_alloc_zero(a,bytes,align,out) < 0 )
		return(-7);
	return(0);
}
