#include "ds4/arena.h"

#include <stdint.h>

#include "test_suite.h"

int32_t test_arena(void)
{
	_Alignas(16) uint8_t mem[96];
	_Alignas(16) uint8_t mem2[65];
	ds4_arena_t a;
	uint8_t *z;
	uint32_t *z2;
	void *p0,*p1,*p2;
	int32_t mark0;
	int32_t i;
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
	if ( ds4_arena_alloc_n(&a,2,4,4,&p2) < 0 )
		return(-9);
	if ( p2 == 0 )
		return(-10);
	if ( ds4_arena_alloc_zero(&a,8,8,(void **)&z) < 0 )
		return(-11);
	if ( z == 0 )
		return(-12);
	for (i=0; i<8; i++)
		if ( z[i] != 0 )
			return(-13);
	z2 = 0;
	if ( ds4_arena_alloc_zero_n(&a,2,(int32_t)sizeof(uint32_t),4,(void **)&z2) < 0 )
		return(-18);
	if ( z2 == 0 )
		return(-19);
	for (i=0; i<2; i++)
		if ( z2[i] != 0 )
			return(-20);
	if ( ds4_arena_release(&a,mark0) < 0 )
		return(-14);
	if ( a.used != 0 )
		return(-15);
	if ( ds4_arena_reset(&a) < 0 )
		return(-16);
	if ( a.used != 0 )
		return(-17);
	return(0);
}
