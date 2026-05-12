#include "ds4/cuda_arena.h"

#include <string.h>

#include "test_suite.h"

int32_t test_cuda_arena(void)
{
	ds4_cuda_arena_t a;
#if DS4_HAS_CUDA
	ds4_cuda_arena_t da;
	ds4_cuda_status_t st;
#endif
	_Alignas(32) uint8_t mem[128];
	void *p0,*p1,*p2;
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
	p2 = 0;
	if ( ds4_cuda_arena_alloc_n(&a,2,8,8,&p2) < 0 )
		return(-10);
	if ( p2 == 0 )
		return(-11);
	if ( ((uintptr_t)p2 & (uintptr_t)7) != 0 )
		return(-12);
	if ( ds4_cuda_arena_alloc_n(&a,(INT64_MAX / 2) + 1,2,8,&p2) != -5 )
		return(-13);
#if !DS4_HAS_CUDA
	{
		int64_t used0;
		used0 = a.used;
		p2 = (void *)1;
		if ( ds4_cuda_arena_alloc_zero(&a,8,8,&p2) != DS4_CUDA_ERR_DISABLED )
			return(-14);
		if ( p2 != 0 )
			return(-15);
		if ( a.used != used0 )
			return(-16);
	}
#endif
#if DS4_HAS_CUDA
	st = ds4_cuda_init();
	if ( ds4_cuda_is_ok(st) != 0 )
	{
		da = (ds4_cuda_arena_t){0};
		if ( ds4_cuda_arena_init_malloc(&da,64) < 0 )
			return(-17);
		p2 = 0;
		if ( ds4_cuda_arena_alloc_zero(&da,32,16,&p2) < 0 || p2 == 0 )
		{
			ds4_cuda_arena_deinit(&da);
			return(-18);
		}
		{
			uint8_t tmp[32];
			int32_t i;
			for (i=0; i<(int32_t)sizeof(tmp); i++)
				tmp[i] = 0xff;
			st = ds4_cuda_memcpy_d2h(tmp,p2,(int64_t)sizeof(tmp));
			if ( ds4_cuda_is_ok(st) == 0 )
			{
				ds4_cuda_arena_deinit(&da);
				return(-19);
			}
			for (i=0; i<(int32_t)sizeof(tmp); i++)
			{
				if ( tmp[i] != 0 )
				{
					ds4_cuda_arena_deinit(&da);
					return(-20);
				}
			}
		}
		if ( ds4_cuda_arena_deinit(&da) < 0 )
			return(-21);
	}
#endif
	ds4_cuda_arena_deinit(&a);
	return(0);
}
