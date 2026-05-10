#include "ds4/config.h"
#include "ds4/log.h"
#include "ds4/str.h"

#include <stdlib.h>
#include <stdio.h>

static int32_t ds4_parse_i32(const char *s,int32_t slen,int32_t *out)
{
	int32_t i,neg;
	int64_t acc,limit;
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
	if ( i >= slen )
		return(-4);
	limit = (int64_t)INT32_MAX;
	if ( neg != 0 )
		limit = ((int64_t)INT32_MAX + (int64_t)1);
	acc = 0;
	for (; i<slen; i++)
	{
		int32_t digit;
		if ( (s[i] < '0') || (s[i] > '9') )
			return(-5);
		digit = (int32_t)(s[i] - '0');
		if ( acc > ((limit - (int64_t)digit) / (int64_t)10) )
			return(-6);
		acc = ((acc * (int64_t)10) + (int64_t)digit);
	}
	if ( neg != 0 )
	{
		if ( acc == ((int64_t)INT32_MAX + (int64_t)1) )
		{
			*out = INT32_MIN;
			return(0);
		}
		*out = (int32_t)(-acc);
		return(0);
	}
	*out = (int32_t)acc;
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

static int32_t ds4_parse_log_level(const char *s,int32_t slen,int32_t *out)
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
		if ( iv < DS4_LOG_LEVEL_MIN )
			return(-4);
		if ( iv > DS4_LOG_LEVEL_MAX )
			return(-5);
		*out = iv;
		return(0);
	}
	if ( ds4_span_eq_ci(s,slen,"error") != 0 )
	{
		*out = 0;
		return(0);
	}
	if ( ds4_span_eq_ci(s,slen,"warn") != 0 || ds4_span_eq_ci(s,slen,"warning") != 0 )
	{
		*out = 1;
		return(0);
	}
	if ( ds4_span_eq_ci(s,slen,"info") != 0 )
	{
		*out = 2;
		return(0);
	}
	if ( ds4_span_eq_ci(s,slen,"debug") != 0 )
	{
		*out = 3;
		return(0);
	}
	return(-6);
}

int32_t ds4_config_defaults(ds4_config_t *cfg)
{
	if ( cfg == 0 )
		return(-1);
	cfg->log_level = 2;
	cfg->enable_cuda = 0;
	cfg->cuda_device = DS4_CUDA_DEVICE_AUTO;
	cfg->arena_size = 0;
	cfg->log_ring_entries = 0;
	return(0);
}

static int32_t ds4_trim_env_value(const char *v,const char **out_v,int32_t *out_len)
{
	int32_t vlen,i,j;
	if ( out_v == 0 )
		return(-1);
	if ( out_len == 0 )
		return(-2);
	*out_v = 0;
	*out_len = 0;
	if ( v == 0 )
		return(0);
	vlen = ds4_cstr_len_i32(v);
	if ( vlen <= 0 )
		return(0);
	for (i=0; i<vlen; i++)
	{
		if ( v[i]!=' ' && v[i]!='\t' && v[i]!='\r' && v[i]!='\n' )
			break;
	}
	j = (vlen - 1);
	for (; j>=i; j--)
	{
		if ( v[j]!=' ' && v[j]!='\t' && v[j]!='\r' && v[j]!='\n' )
			break;
	}
	if ( j < i )
		return(0);
	*out_v = &v[i];
	*out_len = ((j - i) + 1);
	return(1);
}

int32_t ds4_config_parse_env(ds4_config_t *cfg)
{
	const char *v;
	const char *tv;
	int32_t tvlen,iv,rv;
	if ( cfg == 0 )
		return(-1);
	v = getenv("DS4_LOG_LEVEL");
	if ( v != 0 )
	{
		rv = ds4_trim_env_value(v,&tv,&tvlen);
		if ( rv < 0 )
			return(-2);
		if ( rv != 0 )
		{
			if ( ds4_parse_log_level(tv,tvlen,&iv) < 0 )
				return(-3);
			cfg->log_level = iv;
		}
	}
	v = getenv("DS4_ENABLE_CUDA");
	if ( v != 0 )
	{
		rv = ds4_trim_env_value(v,&tv,&tvlen);
		if ( rv < 0 )
			return(-6);
		if ( rv != 0 )
		{
			if ( ds4_parse_bool(tv,tvlen,&iv) < 0 )
				return(-7);
			cfg->enable_cuda = iv;
		}
	}
	v = getenv("DS4_CUDA_DEVICE");
	if ( v != 0 )
	{
		rv = ds4_trim_env_value(v,&tv,&tvlen);
		if ( rv < 0 )
			return(-10);
		if ( rv != 0 )
		{
			if ( ds4_parse_i32(tv,tvlen,&iv) < 0 )
				return(-11);
			if ( iv < DS4_CUDA_DEVICE_AUTO )
				return(-12);
			cfg->cuda_device = iv;
		}
	}
	v = getenv("DS4_ARENA_SIZE");
	if ( v != 0 )
	{
		rv = ds4_trim_env_value(v,&tv,&tvlen);
		if ( rv < 0 )
			return(-13);
		if ( rv != 0 )
		{
			if ( ds4_parse_i32(tv,tvlen,&iv) < 0 )
				return(-14);
			if ( iv < 0 )
				return(-15);
			cfg->arena_size = iv;
		}
	}
	v = getenv("DS4_LOG_RING_ENTRIES");
	if ( v != 0 )
	{
		rv = ds4_trim_env_value(v,&tv,&tvlen);
		if ( rv < 0 )
			return(-16);
		if ( rv != 0 )
		{
			if ( ds4_parse_i32(tv,tvlen,&iv) < 0 )
				return(-17);
			if ( iv < 0 )
				return(-18);
			cfg->log_ring_entries = iv;
		}
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
		if ( ds4_parse_log_level(v,vlen,&iv) < 0 )
			return(-6);
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
	if ( ds4_span_eq(k,klen,"cuda_device") != 0 )
	{
		if ( ds4_parse_i32(v,vlen,&iv) < 0 )
			return(-12);
		if ( iv < DS4_CUDA_DEVICE_AUTO )
			return(-13);
		cfg->cuda_device = iv;
		return(0);
	}
	if ( ds4_span_eq(k,klen,"arena_size") != 0 )
	{
		if ( ds4_parse_i32(v,vlen,&iv) < 0 )
			return(-16);
		if ( iv < 0 )
			return(-17);
		cfg->arena_size = iv;
		return(0);
	}
	if ( ds4_span_eq(k,klen,"log_ring_entries") != 0 )
	{
		if ( ds4_parse_i32(v,vlen,&iv) < 0 )
			return(-20);
		if ( iv < 0 )
			return(-21);
		cfg->log_ring_entries = iv;
		return(0);
	}
	return(1);
}

int32_t ds4_config_parse_kv_cstr(ds4_config_t *cfg,const char *k,const char *v)
{
	int32_t klen,vlen;
	if ( cfg == 0 )
		return(-1);
	if ( k == 0 )
		return(-2);
	if ( v == 0 )
		return(-3);
	klen = ds4_cstr_len_i32(k);
	if ( klen <= 0 )
		return(-4);
	vlen = ds4_cstr_len_i32(v);
	if ( vlen <= 0 )
		return(-5);
	return(ds4_config_parse_kv(cfg,k,klen,v,vlen));
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

static int32_t ds4_strip_inline_comment(const uint8_t *buf,int32_t *l0,int32_t *l1)
{
	int32_t i,end,t0,t1;
	if ( buf == 0 )
		return(-1);
	if ( l0 == 0 )
		return(-2);
	if ( l1 == 0 )
		return(-3);
	end = *l1;
	for (i=*l0; i<end; i++)
	{
		if ( buf[i] != '#' )
			continue;
		if ( i == *l0 || ds4_is_space(buf[i - 1]) != 0 )
			end = i;
		break;
	}
	if ( ds4_trim(buf + *l0,(end - *l0),&t0,&t1) < 0 )
		return(-4);
	*l0 = (*l0 + t0);
	*l1 = (*l0 + (t1 - t0));
	return(0);
}

int32_t ds4_config_parse_mem_ex(ds4_config_t *cfg,const uint8_t *buf,int32_t len,int32_t flags,int32_t *out_unknown)
{
	int32_t i,j,line0,line1,eq,t0,t1,key0,key1,val0,val1,end1,unknown,rv;
	if ( cfg == 0 )
		return(-1);
	if ( buf == 0 )
		return(-2);
	if ( len < 0 )
		return(-3);
	if ( (flags & ~DS4_CONFIG_PARSE_STRICT_UNKNOWN) != 0 )
		return(-4);
	unknown = 0;
	if ( out_unknown != 0 )
		*out_unknown = 0;
	if ( len == 0 )
		return(0);
	line0 = 0;
	for (i=0; i<=len; i++)
	{
		if ( (i == len) || (buf[i] == '\n') )
		{
			line1 = i;
			if ( ds4_trim(buf + line0,(line1 - line0),&t0,&t1) < 0 )
				return(-5);
			key0 = (line0 + t0);
			key1 = (line0 + t1);
			if ( ds4_strip_inline_comment(buf,&key0,&key1) < 0 )
				return(-6);
			if ( key0 == key1 )
			{
				line0 = (i + 1);
				continue;
			}
			end1 = key1;
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
				return(-7);
			if ( ds4_trim(buf + key0,(eq - key0),&t0,&t1) < 0 )
				return(-8);
			key0 = (key0 + t0);
			key1 = (key0 + (t1 - t0));
			if ( ds4_trim(buf + (eq + 1),(end1 - (eq + 1)),&t0,&t1) < 0 )
				return(-9);
			val0 = ((eq + 1) + t0);
			val1 = ((eq + 1) + t1);
			rv = ds4_config_parse_kv(cfg,(const char *)(buf + key0),(key1 - key0),(const char *)(buf + val0),(val1 - val0));
			if ( rv < 0 )
				return(-10);
			if ( rv > 0 )
			{
				unknown += 1;
				if ( out_unknown != 0 )
					*out_unknown = unknown;
				if ( (flags & DS4_CONFIG_PARSE_STRICT_UNKNOWN) != 0 )
					return(-11);
			}
			line0 = (i + 1);
		}
	}
	if ( out_unknown != 0 )
		*out_unknown = unknown;
	return(0);
}

int32_t ds4_config_parse_mem(ds4_config_t *cfg,const uint8_t *buf,int32_t len)
{
	int32_t err;
	err = ds4_config_parse_mem_ex(cfg,buf,len,0,0);
	if ( err == -5 )
		return(-4);
	if ( err == -6 )
		return(-5);
	if ( err == -7 )
		return(-6);
	if ( err == -8 )
		return(-7);
	if ( err == -9 )
		return(-8);
	if ( err == -10 )
		return(-9);
	return(err);
}

int32_t ds4_config_parse_file_ex(ds4_config_t *cfg,const char *path,uint8_t *buf,int32_t cap,int32_t *out_len,int32_t flags,int32_t *out_unknown)
{
	FILE *fp;
	int32_t n,err,c,unknown,close_fp;
	if ( cfg == 0 )
		return(-1);
	if ( path == 0 )
		return(-2);
	if ( buf == 0 )
		return(-3);
	if ( cap <= 0 )
		return(-4);
	if ( (flags & ~DS4_CONFIG_PARSE_STRICT_UNKNOWN) != 0 )
		return(-5);
	unknown = 0;
	if ( out_unknown != 0 )
		*out_unknown = 0;
	close_fp = 0;
	if ( path[0] == '-' && path[1] == 0 )
		fp = stdin;
	else
	{
		fp = fopen(path,"rb");
		close_fp = 1;
	}
	if ( fp == 0 )
		return(-6);
	n = (int32_t)fread(buf,1,(size_t)cap,fp);
	if ( n > cap )
	{
		if ( close_fp != 0 )
			fclose(fp);
		return(-7);
	}
	if ( ferror(fp) != 0 )
	{
		if ( close_fp != 0 )
			fclose(fp);
		return(-8);
	}
	if ( n == cap )
	{
		c = fgetc(fp);
		if ( c != EOF )
		{
			if ( close_fp != 0 )
				fclose(fp);
			return(-9);
		}
		if ( ferror(fp) != 0 )
		{
			if ( close_fp != 0 )
				fclose(fp);
			return(-10);
		}
	}
	if ( close_fp != 0 )
		fclose(fp);
	if ( out_len != 0 )
		*out_len = n;
	if ( n == 0 )
		return(0);
	err = ds4_config_parse_mem_ex(cfg,buf,n,flags,&unknown);
	if ( err < 0 )
	{
		if ( out_unknown != 0 )
			*out_unknown = unknown;
		return(-11);
	}
	if ( out_unknown != 0 )
		*out_unknown = unknown;
	return(0);
}

int32_t ds4_config_parse_file(ds4_config_t *cfg,const char *path,uint8_t *buf,int32_t cap,int32_t *out_len)
{
	int32_t err;
	err = ds4_config_parse_file_ex(cfg,path,buf,cap,out_len,0,0);
	if ( err == -6 )
		return(-5);
	if ( err == -7 )
		return(-6);
	if ( err == -8 )
		return(-7);
	if ( err == -9 )
		return(-8);
	if ( err == -10 )
		return(-9);
	if ( err == -11 )
		return(-10);
	return(err);
}

int32_t ds4_config_load_ex(ds4_config_t *cfg,const char *path,uint8_t *buf,int32_t cap,int32_t *out_len,int32_t flags,int32_t *out_unknown)
{
	int32_t unknown;
	if ( cfg == 0 )
		return(-1);
	if ( (flags & ~DS4_CONFIG_PARSE_STRICT_UNKNOWN) != 0 )
		return(-2);
	unknown = 0;
	if ( out_unknown != 0 )
		*out_unknown = 0;
	if ( ds4_config_defaults(cfg) < 0 )
		return(-3);
	if ( path != 0 )
	{
		if ( path[0] != 0 )
		{
			if ( ds4_config_parse_file_ex(cfg,path,buf,cap,out_len,flags,&unknown) < 0 )
			{
				if ( out_unknown != 0 )
					*out_unknown = unknown;
				return(-4);
			}
		}
	}
	if ( ds4_config_parse_env(cfg) < 0 )
		return(-5);
	if ( out_unknown != 0 )
		*out_unknown = unknown;
	return(0);
}

int32_t ds4_config_load(ds4_config_t *cfg,const char *path,uint8_t *buf,int32_t cap,int32_t *out_len)
{
	int32_t err;
	err = ds4_config_load_ex(cfg,path,buf,cap,out_len,0,0);
	if ( err == -3 )
		return(-2);
	if ( err == -4 )
		return(-3);
	if ( err == -5 )
		return(-4);
	return(err);
}

int32_t ds4_config_load_auto_ex(ds4_config_t *cfg,const char *path,uint8_t *buf,int32_t cap,int32_t *out_len,int32_t flags,int32_t *out_unknown)
{
	const char *env_path;
	if ( cfg == 0 )
		return(-1);
	if ( (flags & ~DS4_CONFIG_PARSE_STRICT_UNKNOWN) != 0 )
		return(-2);
	if ( path != 0 )
	{
		if ( path[0] != 0 )
			return(ds4_config_load_ex(cfg,path,buf,cap,out_len,flags,out_unknown));
	}
	env_path = getenv("DS4_CONFIG_PATH");
	if ( env_path != 0 )
	{
		if ( env_path[0] != 0 )
			return(ds4_config_load_ex(cfg,env_path,buf,cap,out_len,flags,out_unknown));
	}
	return(ds4_config_load_ex(cfg,0,buf,cap,out_len,flags,out_unknown));
}

int32_t ds4_config_load_auto(ds4_config_t *cfg,const char *path,uint8_t *buf,int32_t cap,int32_t *out_len)
{
	const char *env_path;
	if ( cfg == 0 )
		return(-1);
	if ( path != 0 )
	{
		if ( path[0] != 0 )
			return(ds4_config_load(cfg,path,buf,cap,out_len));
	}
	env_path = getenv("DS4_CONFIG_PATH");
	if ( env_path != 0 )
	{
		if ( env_path[0] != 0 )
			return(ds4_config_load(cfg,env_path,buf,cap,out_len));
	}
	return(ds4_config_load(cfg,0,buf,cap,out_len));
}

int32_t ds4_config_format(const ds4_config_t *cfg,char *out,int32_t cap)
{
	const char *lvl;
	int32_t n;
	if ( cfg == 0 )
		return(-1);
	if ( out == 0 )
		return(-2);
	if ( cap <= 0 )
		return(-3);
	lvl = 0;
	if ( cfg->log_level >= DS4_LOG_LEVEL_MIN && cfg->log_level <= DS4_LOG_LEVEL_MAX )
		lvl = ds4_log_level_name(cfg->log_level);
	if ( lvl != 0 )
		n = (int32_t)snprintf(out,(size_t)cap,"log_level=%s\nenable_cuda=%d\ncuda_device=%d\narena_size=%d\nlog_ring_entries=%d\n",lvl,cfg->enable_cuda,cfg->cuda_device,cfg->arena_size,cfg->log_ring_entries);
	else
		n = (int32_t)snprintf(out,(size_t)cap,"log_level=%d\nenable_cuda=%d\ncuda_device=%d\narena_size=%d\nlog_ring_entries=%d\n",cfg->log_level,cfg->enable_cuda,cfg->cuda_device,cfg->arena_size,cfg->log_ring_entries);
	if ( n < 0 )
		return(-4);
	out[cap - 1] = 0;
	if ( n >= cap )
		return(-5);
	return(n);
}
