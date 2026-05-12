#include "ds4/log_ring.h"

#include <stdint.h>
#include <stdio.h>

#include "test_suite.h"

static int32_t ds4_cstr_eq(const char *a,const char *b)
{
	int32_t i;
	if ( a == 0 || b == 0 )
		return(0);
	for (i=0; a[i]!=0 || b[i]!=0; i++)
	{
		if ( a[i] != b[i] )
			return(0);
		if ( a[i] == 0 )
			return(1);
	}
	return(1);
}

int32_t test_log_ring(void)
{
	ds4_log_ring_t lr;
	ds4_log_entry_t entries[4],e;
	char expected[512];
	char fmt[512];
	char longmsg[300];
	int32_t err,c,d,i,expected_n;
	err = 0;
	if ( ds4_log_ring_init(&lr,entries,(int32_t)(sizeof(entries) / sizeof(entries[0]))) < 0 )
		err = -1;
	if ( err == 0 && ds4_log_set_sink(ds4_log_ring_sink,&lr) < 0 )
		err = -2;
	if ( err == 0 && ds4_log_set_level(DS4_LOG_DEBUG) < 0 )
		err = -3;
	if ( err == 0 && DS4_LOGI("a") < 0 )
		err = -4;
	if ( err == 0 && DS4_LOGI("b") < 0 )
		err = -5;
	if ( err == 0 && DS4_LOGI("c") < 0 )
		err = -6;
	if ( err == 0 && DS4_LOGI("d") < 0 )
		err = -7;
	if ( err == 0 && DS4_LOGI("e") < 0 )
		err = -8;
	if ( err == 0 && ds4_log_ring_count(&lr,&c) < 0 )
		err = -9;
	if ( err == 0 && c != 4 )
		err = -10;
	d = -1;
	if ( err == 0 && ds4_log_ring_dropped(&lr,&d) < 0 )
		err = -29;
	if ( err == 0 && d != 1 )
		err = -30;
	if ( err == 0 && ds4_log_ring_pop(&lr,&e) < 0 )
		err = -11;
	if ( err == 0 && ds4_cstr_eq(e.msg,"b") == 0 )
		err = -12;
	if ( err == 0 && ds4_log_entry_format(&e,fmt,(int32_t)sizeof(fmt)) < 0 )
		err = -19;
	if ( err == 0 && ds4_cstr_eq(fmt,"info: b") == 0 )
		err = -20;
	if ( err == 0 && ds4_log_ring_pop(&lr,&e) < 0 )
		err = -13;
	if ( err == 0 && ds4_cstr_eq(e.msg,"c") == 0 )
		err = -14;
	if ( err == 0 && ds4_log_ring_pop(&lr,&e) < 0 )
		err = -15;
	if ( err == 0 && ds4_cstr_eq(e.msg,"d") == 0 )
		err = -16;
	if ( err == 0 && ds4_log_ring_pop(&lr,&e) < 0 )
		err = -17;
	if ( err == 0 && ds4_cstr_eq(e.msg,"e") == 0 )
		err = -18;
	if ( err == 0 )
	{
		for (i=0; i<(int32_t)(sizeof(longmsg) - 1); i++)
			longmsg[i] = 'x';
		longmsg[sizeof(longmsg) - 1] = 0;
		if ( DS4_LOGI("%s",longmsg) < 0 )
			err = -21;
		if ( err == 0 && ds4_log_ring_count(&lr,&c) < 0 )
			err = -22;
		if ( err == 0 && c != 1 )
			err = -23;
		d = -1;
		if ( err == 0 && ds4_log_ring_dropped(&lr,&d) < 0 )
			err = -31;
		if ( err == 0 && d != 1 )
			err = -32;
		if ( err == 0 && ds4_log_ring_pop(&lr,&e) < 0 )
			err = -24;
		if ( err == 0 && e.truncated == 0 )
			err = -25;
		if ( err == 0 && ds4_log_entry_format(&e,fmt,(int32_t)sizeof(fmt)) < 0 )
			err = -26;
		if ( err == 0 )
		{
			expected_n = (int32_t)snprintf(expected,sizeof(expected),"info: %s [truncated]",e.msg);
			if ( expected_n < 0 )
				err = -27;
		}
		if ( err == 0 && ds4_cstr_eq(fmt,expected) == 0 )
			err = -28;
	}
	ds4_log_set_sink(0,0);
	return(err);
}
