#include "ds4/ring.h"

#include <stdint.h>

#include "test_suite.h"

int32_t test_ring(void)
{
	uint8_t mem[64];
	uint8_t mem2[16];
	ds4_ring_t r;
	int32_t a,b,c,d,out,n,bytes;
	if ( ds4_ring_bytes_needed(4,(int32_t)sizeof(int32_t),&bytes) < 0 )
		return(-1);
	if ( bytes != (int32_t)sizeof(mem2) )
		return(-2);
	if ( ds4_ring_init(&r,mem2,4,(int32_t)sizeof(int32_t)) < 0 )
		return(-3);
	if ( ds4_ring_init(&r,mem,4,(int32_t)sizeof(int32_t)) < 0 )
		return(-4);
	a = 11;
	b = 22;
	c = 33;
	d = 44;
	if ( ds4_ring_push(&r,&a) < 0 )
		return(-5);
	if ( ds4_ring_push(&r,&b) < 0 )
		return(-6);
	if ( ds4_ring_push(&r,&c) < 0 )
		return(-7);
	if ( ds4_ring_push(&r,&d) < 0 )
		return(-8);
	if ( ds4_ring_count(&r,&n) < 0 )
		return(-9);
	if ( n != 4 )
		return(-10);
	a = 55;
	if ( ds4_ring_push(&r,&a) == 0 )
		return(-11);
	if ( ds4_ring_pop(&r,&out) < 0 )
		return(-12);
	if ( out != 11 )
		return(-13);
	if ( ds4_ring_pop(&r,&out) < 0 )
		return(-14);
	if ( out != 22 )
		return(-15);
	if ( ds4_ring_count(&r,&n) < 0 )
		return(-16);
	if ( n != 2 )
		return(-17);
	a = 55;
	b = 66;
	if ( ds4_ring_push(&r,&a) < 0 )
		return(-18);
	if ( ds4_ring_push(&r,&b) < 0 )
		return(-19);
	if ( ds4_ring_pop(&r,&out) < 0 )
		return(-20);
	if ( out != 33 )
		return(-21);
	if ( ds4_ring_pop(&r,&out) < 0 )
		return(-22);
	if ( out != 44 )
		return(-23);
	if ( ds4_ring_pop(&r,&out) < 0 )
		return(-24);
	if ( out != 55 )
		return(-25);
	if ( ds4_ring_pop(&r,&out) < 0 )
		return(-26);
	if ( out != 66 )
		return(-27);
	if ( ds4_ring_pop(&r,&out) == 0 )
		return(-28);
	if ( ds4_ring_reset(&r) < 0 )
		return(-29);
	if ( ds4_ring_count(&r,&n) < 0 )
		return(-30);
	if ( n != 0 )
		return(-31);
	if ( ds4_ring_init(&r,mem,2,INT32_MAX) == 0 )
		return(-32);
	return(0);
}
