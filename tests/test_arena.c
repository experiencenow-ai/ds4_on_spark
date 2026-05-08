#include "ds4/arena.h"

#include <stdint.h>

#include "test_suite.h"

int32_t test_arena(void)
{
	uint8_t mem[64];
	ds4_arena_t a;
	void *p0,*p1;
	if ( ds4_arena_init(&a,mem,(int32_t)sizeof(mem)) < 0 )
		return(-1);
	if ( ds4_arena_alloc(&a,8,8,&p0) < 0 )
		return(-2);
	if ( p0 == 0 )
		return(-3);
	if ( ds4_arena_alloc(&a,32,16,&p1) < 0 )
		return(-4);
	if ( p1 == 0 )
		return(-5);
	return(0);
}
