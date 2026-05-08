#include "ds4/log.h"
#include "ds4/common.h"

#include <stdarg.h>
#include <stdio.h>

static int32_t g_level = 2;
static ds4_log_sink_fn g_sink = 0;
static void *g_sink_ctx = 0;

static void ds4_default_sink(void *ctx,int32_t level,const char *msg)
{
	DS4_UNUSED(ctx);
	DS4_UNUSED(level);
	if ( msg == 0 )
		return;
	fputs(msg,stderr);
	fputc('\n',stderr);
}

int32_t ds4_log_set_level(int32_t level)
{
	if ( level < 0 )
		return(-1);
	if ( level > 3 )
		return(-2);
	g_level = level;
	return(0);
}

int32_t ds4_log_set_sink(ds4_log_sink_fn fn,void *ctx)
{
	g_sink = fn;
	g_sink_ctx = ctx;
	return(0);
}

int32_t ds4_logf(int32_t level,const char *fmt,...)
{
	char buf[512];
	va_list ap;
	int32_t n;
	ds4_log_sink_fn sink;
	if ( fmt == 0 )
		return(-1);
	if ( level > g_level )
		return(0);
	va_start(ap,fmt);
	n = (int32_t)vsnprintf(buf,sizeof(buf),fmt,ap);
	va_end(ap);
	if ( n < 0 )
		return(-2);
	buf[sizeof(buf)-1] = 0;
	sink = g_sink;
	if ( sink == 0 )
		sink = ds4_default_sink;
	sink(g_sink_ctx,level,buf);
	return(0);
}
