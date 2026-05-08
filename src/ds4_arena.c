#include "ds4/arena.h"

static int32_t ds4_align_up(int32_t x,int32_t a)
{
	int32_t m;
	if ( a <= 1 )
		return(x);
	m = (a - 1);
	return((x + m) & ~m);
}

static int32_t ds4_is_pow2_i32(int32_t x)
{
	if ( x <= 0 )
		return(0);
	if ( (x & (x - 1)) != 0 )
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

int32_t ds4_arena_alloc(ds4_arena_t *a,int32_t size,int32_t align,void **out)
{
	int32_t used2;
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
	used2 = ds4_align_up(a->used,align);
	if ( (used2 < 0) || (used2 > a->size) )
		return(-5);
	if ( (a->size - used2) < size )
		return(-6);
	*out = (void *)(a->base + used2);
	a->used = (used2 + size);
	return(0);
}
