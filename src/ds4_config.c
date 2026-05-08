#include "ds4/config.h"

static int32_t ds4_span_eq(const char *a,int32_t alen,const char *b)
{
	int32_t i;
	if ( a == 0 )
		return(0);
	if ( alen <= 0 )
		return(0);
	for (i=0; b[i]!=0; i++)
	{
		if ( i >= alen )
			return(0);
		if ( a[i] != b[i] )
			return(0);
	}
	if ( i != alen )
		return(0);
	return(1);
}

static int32_t ds4_parse_i32(const char *s,int32_t slen,int32_t *out)
{
	int32_t i,neg,v;
	if ( s == 0 )
		return(-1);
	if ( out == 0 )
		return(-2);
	if ( slen <= 0 )
		return(-3);
	neg = 0;
	i = 0;
	if ( s[0] == '-' )
	{
		neg = 1;
		i = 1;
	}
	v = 0;
	for (; i<slen; i++)
	{
		if ( (s[i] < '0') || (s[i] > '9') )
			return(-4);
		v = ((v * 10) + (s[i] - '0'));
	}
	if ( neg != 0 )
		v = -v;
	*out = v;
	return(0);
}

int32_t ds4_config_defaults(ds4_config_t *cfg)
{
	if ( cfg == 0 )
		return(-1);
	cfg->log_level = 2;
	cfg->enable_cuda = 0;
	return(0);
}

int32_t ds4_config_parse_kv(ds4_config_t *cfg,const char *k,int32_t klen,const char *v,int32_t vlen)
{
	int32_t iv;
	if ( cfg == 0 )
		return(-1);
	if ( k == 0 )
		return(-2);
	if ( v == 0 )
		return(-3);
	if ( klen <= 0 )
		return(-4);
	if ( vlen <= 0 )
		return(-5);
	if ( ds4_span_eq(k,klen,"log_level") != 0 )
	{
		if ( ds4_parse_i32(v,vlen,&iv) < 0 )
			return(-6);
		cfg->log_level = iv;
		return(0);
	}
	if ( ds4_span_eq(k,klen,"enable_cuda") != 0 )
	{
		if ( ds4_parse_i32(v,vlen,&iv) < 0 )
			return(-7);
		cfg->enable_cuda = iv;
		return(0);
	}
	return(1);
}

static int32_t ds4_is_space(uint8_t c)
{
	if ( c == ' ' || c == '\t' || c == '\r' )
		return(1);
	return(0);
}

static int32_t ds4_trim(const uint8_t *buf,int32_t len,int32_t *l0,int32_t *l1)
{
	int32_t a,b;
	if ( buf == 0 )
		return(-1);
	if ( l0 == 0 )
		return(-2);
	if ( l1 == 0 )
		return(-3);
	a = 0;
	b = len;
	for (; a<b && ds4_is_space(buf[a])!=0; a++)
		;
	for (; b>a && ds4_is_space(buf[b-1])!=0; b--)
		;
	*l0 = a;
	*l1 = b;
	return(0);
}

int32_t ds4_config_parse_mem(ds4_config_t *cfg,const uint8_t *buf,int32_t len)
{
	int32_t i,j,line0,line1,eq,t0,t1,key0,key1,val0,val1;
	if ( cfg == 0 )
		return(-1);
	if ( buf == 0 )
		return(-2);
	if ( len <= 0 )
		return(-3);
	line0 = 0;
	for (i=0; i<=len; i++)
	{
		if ( (i == len) || (buf[i] == '\n') )
		{
			line1 = i;
			if ( ds4_trim(buf + line0,(line1 - line0),&t0,&t1) < 0 )
				return(-4);
			key0 = (line0 + t0);
			key1 = (line0 + t1);
			if ( key0 == key1 )
			{
				line0 = (i + 1);
				continue;
			}
			if ( buf[key0] == '#' )
			{
				line0 = (i + 1);
				continue;
			}
			eq = -1;
			for (j=key0; j<key1; j++)
			{
				if ( buf[j] == '=' )
				{
					eq = j;
					break;
				}
			}
			if ( eq < 0 )
				return(-5);
			if ( ds4_trim(buf + key0,(eq - key0),&t0,&t1) < 0 )
				return(-6);
			key0 = (key0 + t0);
			key1 = (key0 + (t1 - t0));
			if ( ds4_trim(buf + (eq + 1),(line1 - (eq + 1)),&t0,&t1) < 0 )
				return(-7);
			val0 = ((eq + 1) + t0);
			val1 = ((eq + 1) + t1);
			if ( ds4_config_parse_kv(cfg,(const char *)(buf + key0),(key1 - key0),(const char *)(buf + val0),(val1 - val0)) < 0 )
				return(-8);
			line0 = (i + 1);
		}
	}
	return(0);
}
