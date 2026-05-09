#include "ds4/config.h"
#include "ds4/str.h"

#include <stdlib.h>
#include <stdio.h>

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

static int32_t ds4_parse_bool(const char *s,int32_t slen,int32_t *out)
{
	int32_t iv;
	if ( s == 0 )
		return(-1);
	if ( out == 0 )
		return(-2);
	if ( slen <= 0 )
		return(-3);
	if ( ds4_parse_i32(s,slen,&iv) == 0 )
	{
		if ( iv == 0 || iv == 1 )
		{
			*out = iv;
			return(0);
		}
		return(-4);
	}
	if ( ds4_span_eq_ci(s,slen,"true") != 0 || ds4_span_eq_ci(s,slen,"yes") != 0 || ds4_span_eq_ci(s,slen,"on") != 0 )
	{
		*out = 1;
		return(0);
	}
	if ( ds4_span_eq_ci(s,slen,"false") != 0 || ds4_span_eq_ci(s,slen,"no") != 0 || ds4_span_eq_ci(s,slen,"off") != 0 )
	{
		*out = 0;
		return(0);
	}
	return(-5);
}

int32_t ds4_config_defaults(ds4_config_t *cfg)
{
	if ( cfg == 0 )
		return(-1);
	cfg->log_level = 2;
	cfg->enable_cuda = 0;
	return(0);
}

int32_t ds4_config_parse_env(ds4_config_t *cfg)
{
	const char *v;
	int32_t vlen,iv;
	if ( cfg == 0 )
		return(-1);
	v = getenv("DS4_LOG_LEVEL");
	if ( v != 0 )
	{
		vlen = ds4_cstr_len_i32(v);
		if ( vlen <= 0 )
			return(-2);
		if ( ds4_parse_i32(v,vlen,&iv) < 0 )
			return(-3);
		if ( iv < DS4_LOG_LEVEL_MIN )
			return(-4);
		if ( iv > DS4_LOG_LEVEL_MAX )
			return(-5);
		cfg->log_level = iv;
	}
	v = getenv("DS4_ENABLE_CUDA");
	if ( v != 0 )
	{
		vlen = ds4_cstr_len_i32(v);
		if ( vlen <= 0 )
			return(-6);
		if ( ds4_parse_bool(v,vlen,&iv) < 0 )
			return(-7);
		cfg->enable_cuda = iv;
	}
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
		if ( iv < DS4_LOG_LEVEL_MIN )
			return(-7);
		if ( iv > DS4_LOG_LEVEL_MAX )
			return(-8);
		cfg->log_level = iv;
		return(0);
	}
	if ( ds4_span_eq(k,klen,"enable_cuda") != 0 )
	{
		if ( ds4_parse_bool(v,vlen,&iv) < 0 )
			return(-9);
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
	if ( len < 0 )
		return(-3);
	if ( len == 0 )
		return(0);
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

int32_t ds4_config_parse_file(ds4_config_t *cfg,const char *path,uint8_t *buf,int32_t cap,int32_t *out_len)
{
	FILE *fp;
	int32_t n,err,c;
	if ( cfg == 0 )
		return(-1);
	if ( path == 0 )
		return(-2);
	if ( buf == 0 )
		return(-3);
	if ( cap <= 0 )
		return(-4);
	fp = fopen(path,"rb");
	if ( fp == 0 )
		return(-5);
	n = (int32_t)fread(buf,1,(size_t)cap,fp);
	if ( n > cap )
	{
		fclose(fp);
		return(-6);
	}
	if ( ferror(fp) != 0 )
	{
		fclose(fp);
		return(-7);
	}
	if ( n == cap )
	{
		c = fgetc(fp);
		if ( c != EOF )
		{
			fclose(fp);
			return(-8);
		}
		if ( ferror(fp) != 0 )
		{
			fclose(fp);
			return(-9);
		}
	}
	fclose(fp);
	if ( out_len != 0 )
		*out_len = n;
	if ( n == 0 )
		return(0);
	err = ds4_config_parse_mem(cfg,buf,n);
	if ( err < 0 )
		return(-10);
	return(0);
}

int32_t ds4_config_load(ds4_config_t *cfg,const char *path,uint8_t *buf,int32_t cap,int32_t *out_len)
{
	if ( cfg == 0 )
		return(-1);
	if ( ds4_config_defaults(cfg) < 0 )
		return(-2);
	if ( path != 0 )
	{
		if ( path[0] != 0 )
		{
			if ( ds4_config_parse_file(cfg,path,buf,cap,out_len) < 0 )
				return(-3);
		}
	}
	if ( ds4_config_parse_env(cfg) < 0 )
		return(-4);
	return(0);
}

int32_t ds4_config_format(const ds4_config_t *cfg,char *out,int32_t cap)
{
	int32_t n;
	if ( cfg == 0 )
		return(-1);
	if ( out == 0 )
		return(-2);
	if ( cap <= 0 )
		return(-3);
	n = (int32_t)snprintf(out,(size_t)cap,"log_level=%d\nenable_cuda=%d\n",cfg->log_level,cfg->enable_cuda);
	if ( n < 0 )
		return(-4);
	out[cap - 1] = 0;
	if ( n >= cap )
		return(-5);
	return(n);
}
