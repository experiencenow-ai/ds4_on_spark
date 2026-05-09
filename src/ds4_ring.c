#include "ds4/ring.h"

#include <string.h>

int32_t ds4_ring_init(ds4_ring_t *r,uint8_t *mem,int32_t elem_count,int32_t elem_size)
{
	if ( r == 0 )
		return(-1);
	if ( mem == 0 )
		return(-2);
	if ( elem_count <= 0 )
		return(-3);
	if ( elem_size <= 0 )
		return(-4);
	r->base = mem;
	r->elem_size = elem_size;
	r->elem_count = elem_count;
	r->head = 0;
	r->tail = 0;
	r->count = 0;
	return(0);
}

int32_t ds4_ring_reset(ds4_ring_t *r)
{
	if ( r == 0 )
		return(-1);
	r->head = 0;
	r->tail = 0;
	r->count = 0;
	return(0);
}

int32_t ds4_ring_count(ds4_ring_t *r,int32_t *out_count)
{
	if ( r == 0 )
		return(-1);
	if ( out_count == 0 )
		return(-2);
	*out_count = r->count;
	return(0);
}

int32_t ds4_ring_capacity(ds4_ring_t *r,int32_t *out_cap)
{
	if ( r == 0 )
		return(-1);
	if ( out_cap == 0 )
		return(-2);
	*out_cap = r->elem_count;
	return(0);
}

int32_t ds4_ring_push(ds4_ring_t *r,const void *elem)
{
	uint8_t *dst;
	int32_t tail;
	if ( r == 0 )
		return(-1);
	if ( elem == 0 )
		return(-2);
	if ( r->count >= r->elem_count )
		return(-3);
	tail = r->tail;
	if ( tail < 0 )
		return(-4);
	if ( tail >= r->elem_count )
		return(-5);
	dst = (r->base + (tail * r->elem_size));
	memcpy(dst,elem,(size_t)r->elem_size);
	tail += 1;
	if ( tail >= r->elem_count )
		tail = 0;
	r->tail = tail;
	r->count += 1;
	return(0);
}

int32_t ds4_ring_pop(ds4_ring_t *r,void *out_elem)
{
	const uint8_t *src;
	int32_t head;
	if ( r == 0 )
		return(-1);
	if ( out_elem == 0 )
		return(-2);
	if ( r->count <= 0 )
		return(-3);
	head = r->head;
	if ( head < 0 )
		return(-4);
	if ( head >= r->elem_count )
		return(-5);
	src = (r->base + (head * r->elem_size));
	memcpy(out_elem,src,(size_t)r->elem_size);
	head += 1;
	if ( head >= r->elem_count )
		head = 0;
	r->head = head;
	r->count -= 1;
	return(0);
}
