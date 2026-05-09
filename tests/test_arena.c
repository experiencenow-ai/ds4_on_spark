#include "ds4/arena.h"

#include <stdint.h>

#include "test_suite.h"

int32_t test_arena(void)
{
	uint8_t mem[64];
	ds4_arena_t a;
	void *p0,*p1;
	int32_t mark0;
	if ( ds4_arena_init(&a,mem,(int32_t)sizeof(mem)) < 0 )
		return(-1);
	if ( ds4_arena_mark(&a,&mark0) < 0 )
		return(-2);
	if ( mark0 != 0 )
		return(-3);
	if ( ds4_arena_alloc(&a,8,8,&p0) < 0 )
		return(-4);
	if ( p0 == 0 )
		return(-5);
	if ( ds4_arena_alloc(&a,32,16,&p1) < 0 )
		return(-6);
	if ( p1 == 0 )
		return(-7);
	if ( ds4_arena_release(&a,mark0) < 0 )
		return(-8);
	if ( a.used != 0 )
		return(-9);
	if ( ds4_arena_reset(&a) < 0 )
		return(-10);
	if ( a.used != 0 )
		return(-11);
	return(0);
}
