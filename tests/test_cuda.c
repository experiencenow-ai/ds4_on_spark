#include "ds4/cuda.h"

#include "test_suite.h"

int32_t test_cuda(void)
{
	ds4_cuda_status_t st0,st1,st2,st3,st4,st5;
	ds4_cuda_device_info_t di;
	ds4_cuda_stream_t stream;
	ds4_cuda_event_t ev0,ev1;
	const char *s;
	void *dev,*host;
	int32_t dev_count,cur_dev;
	float ms;
	char msg0[128];
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
	if ( ds4_cuda_status_format(st0,msg0,(int32_t)sizeof(msg0)) <= 0 || msg0[0] == 0 )
		return(-200);
	if ( ds4_cuda_status_format(st1,msg0,(int32_t)sizeof(msg0)) <= 0 || msg0[0] == 0 )
		return(-201);
	if ( ds4_cuda_status_format(ds4_cuda_fail(DS4_CUDA_ERR_DISABLED),msg0,(int32_t)sizeof(msg0)) <= 0 || msg0[0] == 0 )
		return(-202);
	if ( ds4_cuda_status_format(st0,0,1) != -1 )
		return(-203);
	if ( ds4_cuda_status_format(st0,msg0,0) != -2 )
		return(-204);
	cur_dev = -2;
	st0 = ds4_cuda_get_device(&cur_dev);
	s = ds4_cuda_errstr(st0);
	if ( s == 0 )
		return(-60);
#if !DS4_HAS_CUDA
	if ( st0.code != DS4_CUDA_ERR_DISABLED )
		return(-63);
	if ( cur_dev != -1 )
		return(-64);
#endif
	st0 = ds4_cuda_set_device(-1);
	if ( st0.code != DS4_CUDA_ERR_INVALID_ARG )
		return(-61);
	st0 = ds4_cuda_set_device(0);
	s = ds4_cuda_errstr(st0);
	if ( s == 0 )
		return(-62);
	st2 = DS4_CUDA_CHECK_LAST_ERROR();
	s = ds4_cuda_errstr(st2);
	if ( s == 0 )
		return(-50);
	st3 = DS4_CUDA_CHECK_PEEK_LAST_ERROR();
	s = ds4_cuda_errstr(st3);
	if ( s == 0 )
		return(-51);
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
#if !DS4_HAS_CUDA
	st0 = DS4_CUDA_KERNEL_LAUNCH((void)0);
	if ( st0.code != DS4_CUDA_ERR_DISABLED )
		return(-301);
#endif
#if DS4_HAS_CUDA
	if ( ds4_cuda_is_enabled_build() != 1 )
		return(-10);
	st5 = ds4_cuda_init();
	if ( ds4_cuda_is_ok(st5) == 0 )
	{
		if ( st5.code != DS4_CUDA_ERR_NO_DEVICE )
			return(-12);
		dev_count = -1;
		st0 = ds4_cuda_device_count(&dev_count);
		if ( st0.code != DS4_CUDA_ERR_NO_DEVICE )
			return(-22);
		if ( dev_count != 0 )
			return(-23);
	}
	else
	{
		uint8_t h0[16],h1[16];
		int32_t i;
		dev_count = -1;
		st0 = ds4_cuda_device_count(&dev_count);
		if ( ds4_cuda_is_ok(st0) == 0 )
			return(-24);
		if ( dev_count <= 0 )
			return(-25);
		st0 = ds4_cuda_device_info(&di,0);
		if ( ds4_cuda_is_ok(st0) == 0 )
			return(-26);
		if ( di.dev != 0 )
			return(-27);
		if ( di.name[0] == 0 )
			return(-28);
		if ( di.total_global_mem <= 0 )
			return(-29);
		host = 0;
		st0 = ds4_cuda_malloc_host(&host,64);
		if ( ds4_cuda_is_ok(st0) == 0 || host == 0 )
			return(-33);
		((uint8_t *)host)[0] = 0x5a;
		st0 = ds4_cuda_free_host(host);
		if ( ds4_cuda_is_ok(st0) == 0 )
			return(-34);
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
		for (i=0; i<(int32_t)sizeof(h1); i++)
			h1[i] = 0;
		stream.h = 0;
		st0 = ds4_cuda_fill_u8(dev,(uint8_t)0xa5,(int64_t)sizeof(h1),stream);
		if ( ds4_cuda_is_ok(st0) == 0 )
		{
			ds4_cuda_free(dev);
			return(-108);
		}
		st0 = ds4_cuda_memcpy_d2h(h1,dev,(int64_t)sizeof(h1));
		if ( ds4_cuda_is_ok(st0) == 0 )
		{
			ds4_cuda_free(dev);
			return(-109);
		}
		for (i=0; i<(int32_t)sizeof(h1); i++)
		{
			if ( h1[i] != (uint8_t)0xa5 )
			{
				ds4_cuda_free(dev);
				return(-110);
			}
		}
		st0 = ds4_cuda_free(dev);
		if ( ds4_cuda_is_ok(st0) == 0 )
			return(-19);
		st0 = ds4_cuda_stream_synchronize((ds4_cuda_stream_t){0});
		if ( ds4_cuda_is_ok(st0) == 0 )
			return(-305);
		{
			ds4_cuda_event_t evd;
			evd.h = 0;
			st0 = ds4_cuda_event_create(&evd,DS4_CUDA_EVENT_FLAGS_DEFAULT);
			if ( ds4_cuda_is_ok(st0) == 0 || evd.h == 0 )
				return(-306);
			st0 = ds4_cuda_event_record(evd,(ds4_cuda_stream_t){0});
			if ( ds4_cuda_is_ok(st0) == 0 )
				return(-307);
			st0 = ds4_cuda_event_synchronize(evd);
			if ( ds4_cuda_is_ok(st0) == 0 )
				return(-308);
			st0 = ds4_cuda_event_destroy(&evd);
			if ( ds4_cuda_is_ok(st0) == 0 )
				return(-309);
		}
		stream.h = 0;
		st0 = ds4_cuda_stream_create(&stream,DS4_CUDA_STREAM_FLAGS_DEFAULT);
		if ( ds4_cuda_is_ok(st0) == 0 || stream.h == 0 )
			return(-38);
		{
			uint8_t ha0[16],ha1[16];
			int32_t ai;
			void *adev;
			for (ai=0; ai<(int32_t)sizeof(ha0); ai++)
			{
				ha0[ai] = (uint8_t)(0xa0 + ai);
				ha1[ai] = 0;
			}
			adev = 0;
			st0 = ds4_cuda_malloc(&adev,(int64_t)sizeof(ha0));
			if ( ds4_cuda_is_ok(st0) == 0 || adev == 0 )
				return(-101);
			st0 = ds4_cuda_memset_async(adev,0,(int64_t)sizeof(ha0),stream);
			if ( ds4_cuda_is_ok(st0) == 0 )
			{
				ds4_cuda_free(adev);
				return(-102);
			}
			st0 = ds4_cuda_memcpy_h2d_async(adev,ha0,(int64_t)sizeof(ha0),stream);
			if ( ds4_cuda_is_ok(st0) == 0 )
			{
				ds4_cuda_free(adev);
				return(-103);
			}
			st0 = ds4_cuda_memcpy_d2h_async(ha1,adev,(int64_t)sizeof(ha1),stream);
			if ( ds4_cuda_is_ok(st0) == 0 )
			{
				ds4_cuda_free(adev);
				return(-104);
			}
			st0 = ds4_cuda_stream_synchronize(stream);
			if ( ds4_cuda_is_ok(st0) == 0 )
			{
				ds4_cuda_free(adev);
				return(-105);
			}
			for (ai=0; ai<(int32_t)sizeof(ha0); ai++)
			{
				if ( ha0[ai] != ha1[ai] )
				{
					ds4_cuda_free(adev);
					return(-106);
				}
			}
			st0 = ds4_cuda_free(adev);
			if ( ds4_cuda_is_ok(st0) == 0 )
				return(-107);
		}
		ev0.h = 0;
		st0 = ds4_cuda_event_create(&ev0,DS4_CUDA_EVENT_FLAGS_DEFAULT);
		if ( ds4_cuda_is_ok(st0) == 0 || ev0.h == 0 )
			return(-39);
		ev1.h = 0;
		st0 = ds4_cuda_event_create(&ev1,DS4_CUDA_EVENT_FLAGS_DEFAULT);
		if ( ds4_cuda_is_ok(st0) == 0 || ev1.h == 0 )
			return(-40);
		st0 = ds4_cuda_event_record(ev0,stream);
		if ( ds4_cuda_is_ok(st0) == 0 )
			return(-41);
		st0 = ds4_cuda_event_record(ev1,stream);
		if ( ds4_cuda_is_ok(st0) == 0 )
			return(-42);
		st0 = ds4_cuda_stream_synchronize(stream);
		if ( ds4_cuda_is_ok(st0) == 0 )
			return(-43);
		ms = -1.0f;
		st0 = ds4_cuda_event_elapsed_ms(&ms,ev0,ev1);
		if ( ds4_cuda_is_ok(st0) == 0 )
			return(-44);
		if ( ms < 0.0f )
			return(-45);
		st0 = ds4_cuda_event_destroy(&ev1);
		if ( ds4_cuda_is_ok(st0) == 0 )
			return(-46);
		st0 = ds4_cuda_event_destroy(&ev0);
		if ( ds4_cuda_is_ok(st0) == 0 )
			return(-47);
		st0 = ds4_cuda_stream_destroy(&stream);
		if ( ds4_cuda_is_ok(st0) == 0 )
			return(-48);
	}
#else
	if ( ds4_cuda_is_enabled_build() != 0 )
		return(-11);
	st5 = ds4_cuda_init();
	if ( st5.code != DS4_CUDA_ERR_DISABLED )
		return(-13);
	dev_count = -1;
	st0 = ds4_cuda_device_count(&dev_count);
	if ( st0.code != DS4_CUDA_ERR_DISABLED )
		return(-30);
	if ( dev_count != 0 )
		return(-31);
	st0 = ds4_cuda_device_info(&di,0);
	if ( st0.code != DS4_CUDA_ERR_DISABLED )
		return(-32);
	dev = (void *)0x1;
	st0 = ds4_cuda_malloc(&dev,16);
	if ( st0.code != DS4_CUDA_ERR_DISABLED )
		return(-20);
	if ( dev != 0 )
		return(-21);
	host = (void *)0x1;
	st0 = ds4_cuda_malloc_host(&host,16);
	if ( st0.code != DS4_CUDA_ERR_DISABLED )
		return(-35);
	if ( host != 0 )
		return(-36);
	st0 = ds4_cuda_free_host((void *)0x1);
	if ( st0.code != DS4_CUDA_ERR_DISABLED )
		return(-37);
	stream.h = (void *)0x1;
	st0 = ds4_cuda_stream_create(&stream,DS4_CUDA_STREAM_FLAGS_DEFAULT);
	if ( st0.code != DS4_CUDA_ERR_DISABLED )
		return(-38);
	if ( stream.h != 0 )
		return(-39);
	st0 = ds4_cuda_memset_async((void *)0x1,0,16,stream);
	if ( st0.code != DS4_CUDA_ERR_DISABLED )
		return(-201);
	st0 = ds4_cuda_memcpy_h2d_async((void *)0x1,(void *)0x2,16,stream);
	if ( st0.code != DS4_CUDA_ERR_DISABLED )
		return(-202);
	st0 = ds4_cuda_memcpy_d2h_async((void *)0x1,(void *)0x2,16,stream);
	if ( st0.code != DS4_CUDA_ERR_DISABLED )
		return(-203);
	st0 = ds4_cuda_fill_u8((void *)0x1,(uint8_t)0xa5,16,stream);
	if ( st0.code != DS4_CUDA_ERR_DISABLED )
		return(-204);
	ev0.h = (void *)0x1;
	st0 = ds4_cuda_event_create(&ev0,DS4_CUDA_EVENT_FLAGS_DEFAULT);
	if ( st0.code != DS4_CUDA_ERR_DISABLED )
		return(-40);
	if ( ev0.h != 0 )
		return(-41);
	ev1.h = 0;
	ms = -1.0f;
	st0 = ds4_cuda_event_elapsed_ms(&ms,ev0,ev1);
	if ( st0.code != DS4_CUDA_ERR_DISABLED )
		return(-42);
	if ( ms != 0.0f )
		return(-43);
#endif
	return(0);
}
