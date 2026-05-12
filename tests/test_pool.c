#include "ds4/pool.h"

#include <stdint.h>

#include "test_suite.h"

int32_t test_pool(void)
{
	uint8_t mem[64];
	ds4_pool_t p;
	void *a,*b,*c;
	int32_t free0,free1,used;
	if ( ds4_pool_init(&p,mem,(int32_t)sizeof(mem),16) < 0 )
		return(-1);
	if ( ds4_pool_free_count(&p,&free0) < 0 )
		return(-2);
	if ( free0 != 4 )
		return(-3);
	if ( ds4_pool_alloc(&p,&a) < 0 )
		return(-4);
	if ( ds4_pool_alloc(&p,&b) < 0 )
		return(-5);
	if ( ds4_pool_alloc(&p,&c) < 0 )
		return(-6);
	if ( a == 0 || b == 0 || c == 0 )
		return(-7);
	if ( ds4_pool_free_count(&p,&free1) < 0 )
		return(-8);
	if ( free1 != 1 )
		return(-9);
	if ( ds4_pool_used_count(&p,&used) < 0 )
		return(-10);
	if ( used != 3 )
		return(-11);
	if ( ds4_pool_free(&p,b) < 0 )
		return(-12);
	if ( ds4_pool_free_count(&p,&free1) < 0 )
		return(-13);
	if ( free1 != 2 )
		return(-14);
	if ( ds4_pool_used_count(&p,&used) < 0 )
		return(-15);
	if ( used != 2 )
		return(-16);
	if ( ds4_pool_reset(&p) < 0 )
		return(-17);
	if ( ds4_pool_free_count(&p,&free1) < 0 )
		return(-18);
	if ( free1 != 4 )
		return(-19);
	if ( ds4_pool_used_count(&p,&used) < 0 )
		return(-20);
	if ( used != 0 )
		return(-21);
	return(0);
}
