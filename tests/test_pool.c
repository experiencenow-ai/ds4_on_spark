#include "ds4/pool.h"

#include <stdint.h>

#include "test_suite.h"

int32_t test_pool(void)
{
	uint8_t mem[64];
	ds4_pool_t p;
	void *a,*b,*c;
	uint8_t *ua;
	int32_t bytes,free0,free1,i,used;
	if ( ds4_pool_bytes_needed(4,16,&bytes) < 0 )
		return(-1);
	if ( bytes != (int32_t)sizeof(mem) )
		return(-2);
	if ( ds4_pool_init(&p,mem,(int32_t)sizeof(mem),16) < 0 )
		return(-3);
	if ( ds4_pool_validate(&p) < 0 )
		return(-4);
	if ( ds4_pool_free_count(&p,&free0) < 0 )
		return(-5);
	if ( free0 != 4 )
		return(-6);
	if ( ds4_pool_alloc_zero(&p,&a) < 0 )
		return(-7);
	ua = (uint8_t *)a;
	for (i=0; i<16; i++)
		if ( ua[i] != 0 )
			return(-24);
	if ( ds4_pool_alloc(&p,&b) < 0 )
		return(-8);
	if ( ds4_pool_alloc(&p,&c) < 0 )
		return(-9);
	if ( a == 0 || b == 0 || c == 0 )
		return(-10);
	if ( ds4_pool_validate(&p) < 0 )
		return(-11);
	if ( ds4_pool_free_count(&p,&free1) < 0 )
		return(-12);
	if ( free1 != 1 )
		return(-13);
	if ( ds4_pool_used_count(&p,&used) < 0 )
		return(-14);
	if ( used != 3 )
		return(-15);
	if ( ds4_pool_free(&p,b) < 0 )
		return(-16);
	if ( ds4_pool_validate(&p) < 0 )
		return(-17);
	if ( ds4_pool_free_count(&p,&free1) < 0 )
		return(-18);
	if ( free1 != 2 )
		return(-19);
	if ( ds4_pool_used_count(&p,&used) < 0 )
		return(-20);
	if ( used != 2 )
		return(-21);
	if ( ds4_pool_reset(&p) < 0 )
		return(-22);
	if ( ds4_pool_validate(&p) < 0 )
		return(-23);
	if ( ds4_pool_free_count(&p,&free1) < 0 )
		return(-25);
	if ( free1 != 4 )
		return(-26);
	if ( ds4_pool_used_count(&p,&used) < 0 )
		return(-27);
	if ( used != 0 )
		return(-28);
	if ( ds4_pool_free(&p,c) < 0 )
		return(-29);
	if ( ds4_pool_free(&p,c) < 0 )
		return(-30);
	if ( ds4_pool_validate(&p) >= 0 )
		return(-31);
	return(0);
}
