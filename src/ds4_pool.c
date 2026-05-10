#include "ds4/pool.h"

#include <string.h>

static int32_t ds4_pool_read_i32(const uint8_t *p)
{
	int32_t v;
	memcpy(&v,p,sizeof(v));
	return(v);
}

static void ds4_pool_write_i32(uint8_t *p,int32_t v)
{
	memcpy(p,&v,sizeof(v));
}

int32_t ds4_pool_init(ds4_pool_t *p,uint8_t *mem,int32_t mem_size,int32_t block_size)
{
	int32_t i,count,next;
	if ( p == 0 )
		return(-1);
	if ( mem == 0 )
		return(-2);
	if ( mem_size <= 0 )
		return(-3);
	if ( block_size <= 0 )
		return(-4);
	if ( block_size < (int32_t)sizeof(int32_t) )
		return(-5);
	count = (mem_size / block_size);
	if ( count <= 0 )
		return(-6);
	p->base = mem;
	p->block_size = block_size;
	p->block_count = count;
	p->free_head = 0;
	for (i=0; i<count; i++)
	{
		next = (i + 1);
		if ( next >= count )
			next = -1;
		ds4_pool_write_i32(p->base + (i * block_size),next);
	}
	return(0);
}

int32_t ds4_pool_alloc(ds4_pool_t *p,void **out)
{
	int32_t head,next;
	if ( p == 0 )
		return(-1);
	if ( out == 0 )
		return(-2);
	head = p->free_head;
	if ( head < 0 )
		return(-3);
	if ( head >= p->block_count )
		return(-4);
	next = ds4_pool_read_i32(p->base + (head * p->block_size));
	p->free_head = next;
	*out = (void *)(p->base + (head * p->block_size));
	return(0);
}

int32_t ds4_pool_free(ds4_pool_t *p,void *ptr)
{
	uint8_t *uptr;
	int32_t off,idx;
	if ( p == 0 )
		return(-1);
	if ( ptr == 0 )
		return(-2);
	uptr = (uint8_t *)ptr;
	if ( uptr < p->base )
		return(-3);
	off = (int32_t)(uptr - p->base);
	if ( off < 0 )
		return(-4);
	if ( p->block_size <= 0 )
		return(-5);
	if ( (off % p->block_size) != 0 )
		return(-6);
	idx = (off / p->block_size);
	if ( idx < 0 )
		return(-7);
	if ( idx >= p->block_count )
		return(-8);
	ds4_pool_write_i32(p->base + (idx * p->block_size),p->free_head);
	p->free_head = idx;
	return(0);
}

int32_t ds4_pool_free_count(ds4_pool_t *p,int32_t *out)
{
	int32_t n,head;
	if ( p == 0 )
		return(-1);
	if ( out == 0 )
		return(-2);
	n = 0;
	head = p->free_head;
	for (; head>=0; )
	{
		if ( head >= p->block_count )
			return(-3);
		head = ds4_pool_read_i32(p->base + (head * p->block_size));
		n += 1;
		if ( n > p->block_count )
			return(-4);
	}
	*out = n;
	return(0);
}
