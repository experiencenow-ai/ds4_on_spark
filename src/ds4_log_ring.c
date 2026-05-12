#include "ds4/log_ring.h"
#include "ds4/str.h"

#include <stddef.h>
#include <stdio.h>

static void ds4_log_ring_entry_from_msg(ds4_log_entry_t *e,int32_t level,const char *msg)
{
	int32_t i,n,copy;
	if ( e == 0 )
		return;
	if ( msg == 0 )
		msg = "";
	e->level = level;
	e->truncated = 0;
	n = ds4_cstr_len_i32(msg);
	copy = n;
	if ( copy >= (DS4_LOG_RING_MSG_CAP - 1) )
	{
		copy = (DS4_LOG_RING_MSG_CAP - 1);
		e->truncated = 1;
	}
	for (i=0; i<copy; i++)
		e->msg[i] = msg[i];
	e->msg[copy] = 0;
}

int32_t ds4_log_entry_format(const ds4_log_entry_t *e,char *out,int32_t cap)
{
	const char *lvl,*msg,*suffix;
	int32_t n;
	if ( out == 0 )
		return(-1);
	if ( cap <= 0 )
		return(-2);
	out[0] = 0;
	if ( e == 0 )
		return(-3);
	lvl = ds4_log_level_name(e->level);
	if ( lvl == 0 )
		lvl = "?";
	msg = e->msg;
	if ( msg == 0 )
		msg = "";
	suffix = "";
	if ( e->truncated != 0 )
		suffix = " [truncated]";
	n = (int32_t)snprintf(out,(size_t)cap,"%s: %s%s",lvl,msg,suffix);
	if ( n < 0 )
	{
		out[0] = 0;
		return(-4);
	}
	out[cap - 1] = 0;
	if ( n >= cap )
		return(-5);
	return(n);
}

int32_t ds4_log_ring_init(ds4_log_ring_t *lr,ds4_log_entry_t *entries,int32_t entry_count)
{
	if ( lr == 0 )
		return(-1);
	if ( entries == 0 )
		return(-2);
	if ( entry_count <= 0 )
		return(-3);
	if ( ds4_ring_init(&lr->r,(uint8_t *)entries,entry_count,(int32_t)sizeof(ds4_log_entry_t)) < 0 )
		return(-4);
	return(0);
}

int32_t ds4_log_ring_count(ds4_log_ring_t *lr,int32_t *out_count)
{
	if ( lr == 0 )
		return(-1);
	return(ds4_ring_count(&lr->r,out_count));
}

int32_t ds4_log_ring_pop(ds4_log_ring_t *lr,ds4_log_entry_t *out)
{
	if ( lr == 0 )
		return(-1);
	if ( out == 0 )
		return(-2);
	return(ds4_ring_pop(&lr->r,out));
}

void ds4_log_ring_sink(void *ctx,int32_t level,const char *msg)
{
	ds4_log_ring_t *lr;
	ds4_log_entry_t e,drop;
	int32_t rv;
	lr = (ds4_log_ring_t *)ctx;
	if ( lr == 0 )
		return;
	ds4_log_ring_entry_from_msg(&e,level,msg);
	rv = ds4_ring_push(&lr->r,&e);
	if ( rv == 0 )
		return;
	if ( rv != -3 )
		return;
	if ( ds4_ring_pop(&lr->r,&drop) < 0 )
		return;
	ds4_ring_push(&lr->r,&e);
}
