#include "ds4/cuda_arena.h"

#include <string.h>

#include "test_suite.h"

int32_t test_cuda_arena(void)
{
	ds4_cuda_arena_t a;
	uint8_t mem[128];
	void *p0,*p1;
	if ( ds4_cuda_arena_init(&a,mem,(int64_t)sizeof(mem)) < 0 )
		return(-1);
	p0 = 0;
	if ( ds4_cuda_arena_alloc(&a,16,16,&p0) < 0 )
		return(-2);
	if ( p0 == 0 )
		return(-3);
	if ( ((uintptr_t)p0 & (uintptr_t)15) != 0 )
		return(-4);
	p1 = 0;
	if ( ds4_cuda_arena_alloc(&a,16,32,&p1) < 0 )
		return(-5);
	if ( p1 == 0 )
		return(-6);
	if ( ((uintptr_t)p1 & (uintptr_t)31) != 0 )
		return(-7);
	memset(mem,0,(int32_t)sizeof(mem));
	ds4_cuda_arena_reset(&a);
	p0 = 0;
	if ( ds4_cuda_arena_alloc(&a,8,8,&p0) < 0 )
		return(-8);
	if ( p0 != (void *)mem )
		return(-9);
	ds4_cuda_arena_deinit(&a);
	return(0);
}
