#include "ds4/cuda.h"

#include "test_suite.h"

int32_t test_cuda(void)
{
	ds4_cuda_status_t st0,st1,st2,st3,st4,st5;
	const char *s;
	void *dev;
	st0 = ds4_cuda_ok();
	if ( ds4_cuda_is_ok(st0) == 0 )
		return(-1);
	st1 = ds4_cuda_fail(123);
	if ( ds4_cuda_is_ok(st1) != 0 )
		return(-2);
	s = ds4_cuda_errstr(st0);
	if ( s == 0 )
		return(-3);
	s = ds4_cuda_errstr(st1);
	if ( s == 0 )
		return(-4);
	st2 = ds4_cuda_last_error();
	s = ds4_cuda_errstr(st2);
	if ( s == 0 )
		return(-5);
	st3 = ds4_cuda_peek_last_error();
	s = ds4_cuda_errstr(st3);
	if ( s == 0 )
		return(-6);
	st4 = ds4_cuda_device_synchronize();
	s = ds4_cuda_errstr(st4);
	if ( s == 0 )
		return(-7);
	st0 = ds4_cuda_check_i32(0,"ok","file",123);
	if ( ds4_cuda_is_ok(st0) == 0 )
		return(-8);
	st0 = DS4_CUDA_CALL(0);
	if ( ds4_cuda_is_ok(st0) == 0 )
		return(-9);
#if defined(DS4_HAS_CUDA)
	if ( ds4_cuda_is_enabled_build() != 1 )
		return(-10);
	st5 = ds4_cuda_init();
	if ( ds4_cuda_is_ok(st5) == 0 )
	{
		if ( st5.code != DS4_CUDA_ERR_NO_DEVICE )
			return(-12);
	}
	else
	{
		uint8_t h0[16],h1[16];
		int32_t i;
		dev = 0;
		for (i=0; i<(int32_t)sizeof(h0); i++)
		{
			h0[i] = (uint8_t)i;
			h1[i] = 0;
		}
		st0 = ds4_cuda_malloc(&dev,(int64_t)sizeof(h0));
		if ( ds4_cuda_is_ok(st0) == 0 || dev == 0 )
			return(-14);
		st0 = ds4_cuda_memset(dev,0,(int64_t)sizeof(h0));
		if ( ds4_cuda_is_ok(st0) == 0 )
			return(-15);
		st0 = ds4_cuda_memcpy_h2d(dev,h0,(int64_t)sizeof(h0));
		if ( ds4_cuda_is_ok(st0) == 0 )
		{
			ds4_cuda_free(dev);
			return(-16);
		}
		st0 = ds4_cuda_memcpy_d2h(h1,dev,(int64_t)sizeof(h1));
		if ( ds4_cuda_is_ok(st0) == 0 )
		{
			ds4_cuda_free(dev);
			return(-17);
		}
		for (i=0; i<(int32_t)sizeof(h0); i++)
		{
			if ( h0[i] != h1[i] )
			{
				ds4_cuda_free(dev);
				return(-18);
			}
		}
		st0 = ds4_cuda_free(dev);
		if ( ds4_cuda_is_ok(st0) == 0 )
			return(-19);
	}
#else
	if ( ds4_cuda_is_enabled_build() != 0 )
		return(-11);
	st5 = ds4_cuda_init();
	if ( st5.code != DS4_CUDA_ERR_DISABLED )
		return(-13);
	dev = (void *)0x1;
	st0 = ds4_cuda_malloc(&dev,16);
	if ( st0.code != DS4_CUDA_ERR_DISABLED )
		return(-20);
	if ( dev != 0 )
		return(-21);
#endif
	return(0);
}
