#include "ds4/arena.h"

#include <stdint.h>

#include "test_suite.h"

int32_t test_arena(void)
{
	_Alignas(16) uint8_t mem[64];
	_Alignas(16) uint8_t mem2[65];
	ds4_arena_t a;
	void *p0,*p1;
	int32_t mark0;
	if ( ds4_arena_init_ex(&a,mem2 + 1,64,16) >= 0 )
		return(-1);
	if ( ds4_arena_init_ex(&a,mem,(int32_t)sizeof(mem),16) < 0 )
		return(-2);
	if ( ds4_arena_mark(&a,&mark0) < 0 )
		return(-3);
	if ( mark0 != 0 )
		return(-4);
	if ( ds4_arena_alloc(&a,8,8,&p0) < 0 )
		return(-5);
	if ( p0 == 0 )
		return(-6);
	if ( ds4_arena_alloc(&a,32,16,&p1) < 0 )
		return(-7);
	if ( p1 == 0 )
		return(-8);
	if ( ds4_arena_release(&a,mark0) < 0 )
		return(-9);
	if ( a.used != 0 )
		return(-10);
	if ( ds4_arena_reset(&a) < 0 )
		return(-11);
	if ( a.used != 0 )
		return(-12);
	return(0);
}
