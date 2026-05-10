#include "ds4/log.h"

#include <stdint.h>

#include "test_suite.h"

static int32_t ds4_cstr_starts_with(const char *s,const char *p)
{
	int32_t i;
	if ( s == 0 )
		return(0);
	if ( p == 0 )
		return(0);
	for (i=0; p[i]!=0; i++)
	{
		if ( s[i] == 0 )
			return(0);
		if ( s[i] != p[i] )
			return(0);
	}
	return(1);
}

int32_t test_log(void)
{
	ds4_log_buf_t lb;
	char buf[64];
	int32_t used0;
	if ( ds4_log_buf_init(&lb,buf,(int32_t)sizeof(buf)) < 0 )
		return(-1);
	if ( ds4_log_set_sink(ds4_log_buf_sink,&lb) < 0 )
		return(-2);
	if ( ds4_log_set_level(DS4_LOG_INFO) < 0 )
		return(-3);
	if ( DS4_LOGI("hello") < 0 )
		return(-4);
	if ( ds4_cstr_starts_with(buf,"hello\n") == 0 )
		return(-5);
	used0 = lb.used;
	if ( DS4_LOGD("skip") < 0 )
		return(-6);
	if ( lb.used != used0 )
		return(-7);
	if ( ds4_log_set_level(DS4_LOG_DEBUG) < 0 )
		return(-8);
	if ( DS4_LOGD("dbg") < 0 )
		return(-9);
	if ( lb.used <= used0 )
		return(-10);
	if ( ds4_log_buf_init(&lb,buf,(int32_t)sizeof(buf)) < 0 )
		return(-11);
	if ( ds4_log_set_sink(ds4_log_buf_sink_prefixed,&lb) < 0 )
		return(-12);
	if ( ds4_log_set_level(DS4_LOG_INFO) < 0 )
		return(-13);
	if ( DS4_LOGI("hello") < 0 )
		return(-14);
	if ( ds4_cstr_starts_with(buf,"info: hello\n") == 0 )
		return(-15);
	return(0);
}
