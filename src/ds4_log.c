#include "ds4/log.h"
#include "ds4/common.h"
#include "ds4/str.h"

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

int32_t ds4_log_buf_init(ds4_log_buf_t *lb,char *buf,int32_t cap)
{
	if ( lb == 0 )
		return(-1);
	lb->buf = buf;
	lb->cap = cap;
	lb->used = 0;
	lb->truncated = 0;
	if ( buf == 0 )
		return(-2);
	if ( cap <= 0 )
		return(-3);
	buf[0] = 0;
	return(0);
}

void ds4_log_buf_sink(void *ctx,int32_t level,const char *msg)
{
	ds4_log_buf_t *lb;
	int32_t msglen,i,avail,copylen;
	DS4_UNUSED(level);
	lb = (ds4_log_buf_t *)ctx;
	if ( lb == 0 )
		return;
	if ( lb->buf == 0 )
		return;
	if ( lb->cap <= 0 )
		return;
	if ( msg == 0 )
		msg = "";
	if ( lb->used < 0 )
		lb->used = 0;
	if ( lb->used >= lb->cap )
	{
		lb->truncated = 1;
		lb->buf[lb->cap - 1] = 0;
		return;
	}
	avail = (lb->cap - lb->used - 1);
	if ( avail <= 0 )
	{
		lb->truncated = 1;
		lb->buf[lb->cap - 1] = 0;
		return;
	}
	msglen = ds4_cstr_len_i32(msg);
	copylen = msglen;
	if ( copylen > avail )
	{
		copylen = avail;
		lb->truncated = 1;
	}
	for (i=0; i<copylen; i++)
		lb->buf[lb->used + i] = msg[i];
	lb->used += copylen;
	avail = (lb->cap - lb->used - 1);
	if ( avail > 0 )
	{
		lb->buf[lb->used] = '\n';
		lb->used += 1;
	}
	else
		lb->truncated = 1;
	lb->buf[lb->used] = 0;
}
