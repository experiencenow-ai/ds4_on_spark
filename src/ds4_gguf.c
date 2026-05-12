#include "ds4/gguf.h"
#include "ds4/str.h"

#define DS4_GGUF_MAGIC_U32 0x46554747u

#define DS4_GGUF_TYPE_UINT8 0
#define DS4_GGUF_TYPE_INT8 1
#define DS4_GGUF_TYPE_UINT16 2
#define DS4_GGUF_TYPE_INT16 3
#define DS4_GGUF_TYPE_UINT32 4
#define DS4_GGUF_TYPE_INT32 5
#define DS4_GGUF_TYPE_FLOAT32 6
#define DS4_GGUF_TYPE_BOOL 7
#define DS4_GGUF_TYPE_STRING 8
#define DS4_GGUF_TYPE_ARRAY 9
#define DS4_GGUF_TYPE_UINT64 10
#define DS4_GGUF_TYPE_INT64 11
#define DS4_GGUF_TYPE_FLOAT64 12

static int32_t ds4_gguf_u32le(const uint8_t *buf,int32_t len,int32_t off,uint32_t *out)
{
	uint32_t v;
	if ( buf == 0 )
		return(-1);
	if ( out == 0 )
		return(-2);
	if ( len < 0 )
		return(-3);
	if ( off < 0 )
		return(-4);
	if ( off > (len - 4) )
		return(-5);
	v = (uint32_t)buf[off + 0];
	v |= ((uint32_t)buf[off + 1] << 8);
	v |= ((uint32_t)buf[off + 2] << 16);
	v |= ((uint32_t)buf[off + 3] << 24);
	*out = v;
	return(0);
}

static int32_t ds4_gguf_u64le(const uint8_t *buf,int32_t len,int32_t off,uint64_t *out)
{
	uint64_t v;
	if ( buf == 0 )
		return(-1);
	if ( out == 0 )
		return(-2);
	if ( len < 0 )
		return(-3);
	if ( off < 0 )
		return(-4);
	if ( off > (len - 8) )
		return(-5);
	v = (uint64_t)buf[off + 0];
	v |= ((uint64_t)buf[off + 1] << 8);
	v |= ((uint64_t)buf[off + 2] << 16);
	v |= ((uint64_t)buf[off + 3] << 24);
	v |= ((uint64_t)buf[off + 4] << 32);
	v |= ((uint64_t)buf[off + 5] << 40);
	v |= ((uint64_t)buf[off + 6] << 48);
	v |= ((uint64_t)buf[off + 7] << 56);
	*out = v;
	return(0);
}

static int32_t ds4_gguf_take_u32le(const uint8_t *buf,int32_t len,int32_t *off,uint32_t *out)
{
	uint32_t v;
	int32_t o;
	if ( off == 0 )
		return(-1);
	if ( ds4_gguf_u32le(buf,len,*off,&v) < 0 )
		return(-2);
	o = (*off + 4);
	if ( o < 0 )
		return(-3);
	*off = o;
	*out = v;
	return(0);
}

static int32_t ds4_gguf_take_u64le(const uint8_t *buf,int32_t len,int32_t *off,uint64_t *out)
{
	uint64_t v;
	int32_t o;
	if ( off == 0 )
		return(-1);
	if ( ds4_gguf_u64le(buf,len,*off,&v) < 0 )
		return(-2);
	o = (*off + 8);
	if ( o < 0 )
		return(-3);
	*off = o;
	*out = v;
	return(0);
}

static int32_t ds4_gguf_take_str(const uint8_t *buf,int32_t len,int32_t *off,ds4_gguf_str_t *out)
{
	uint64_t n;
	int32_t o,ni;
	if ( out == 0 )
		return(-1);
	if ( ds4_gguf_take_u64le(buf,len,off,&n) < 0 )
		return(-2);
	if ( n > (uint64_t)INT32_MAX )
		return(-3);
	ni = (int32_t)n;
	o = *off;
	if ( o < 0 )
		return(-4);
	if ( ni < 0 )
		return(-5);
	if ( o > (len - ni) )
		return(-6);
	out->ptr = (const char *)(buf + o);
	out->len = ni;
	*off = (o + ni);
	return(0);
}

static int32_t ds4_gguf_take_value(const uint8_t *buf,int32_t len,int32_t *off,int32_t value_type,const uint8_t **value,int32_t *value_len)
{
	int32_t o,base;
	uint64_t n;
	uint32_t t_u32;
	int32_t t;
	int64_t bytes64;
	int32_t bytes;
	if ( buf == 0 )
		return(-1);
	if ( off == 0 )
		return(-2);
	if ( value == 0 )
		return(-3);
	if ( value_len == 0 )
		return(-4);
	o = *off;
	if ( o < 0 )
		return(-5);
	base = o;
	if ( value_type == DS4_GGUF_TYPE_UINT8 || value_type == DS4_GGUF_TYPE_INT8 || value_type == DS4_GGUF_TYPE_BOOL )
		o += 1;
	else if ( value_type == DS4_GGUF_TYPE_UINT16 || value_type == DS4_GGUF_TYPE_INT16 )
		o += 2;
	else if ( value_type == DS4_GGUF_TYPE_UINT32 || value_type == DS4_GGUF_TYPE_INT32 || value_type == DS4_GGUF_TYPE_FLOAT32 )
		o += 4;
	else if ( value_type == DS4_GGUF_TYPE_UINT64 || value_type == DS4_GGUF_TYPE_INT64 || value_type == DS4_GGUF_TYPE_FLOAT64 )
		o += 8;
	else if ( value_type == DS4_GGUF_TYPE_STRING )
	{
		if ( ds4_gguf_take_u64le(buf,len,&o,&n) < 0 )
			return(-6);
		if ( n > (uint64_t)INT32_MAX )
			return(-7);
		if ( o > (len - (int32_t)n) )
			return(-8);
		o += (int32_t)n;
	}
	else if ( value_type == DS4_GGUF_TYPE_ARRAY )
	{
		if ( ds4_gguf_take_u32le(buf,len,&o,&t_u32) < 0 )
			return(-9);
		t = (int32_t)t_u32;
		if ( ds4_gguf_take_u64le(buf,len,&o,&n) < 0 )
			return(-10);
		if ( n > (uint64_t)INT32_MAX )
			return(-11);
		if ( t == DS4_GGUF_TYPE_UINT8 || t == DS4_GGUF_TYPE_INT8 || t == DS4_GGUF_TYPE_BOOL )
		{
			bytes64 = (int64_t)n;
			if ( bytes64 > (int64_t)INT32_MAX )
				return(-17);
			bytes = (int32_t)bytes64;
			if ( o > (len - bytes) )
				return(-18);
			o += bytes;
		}
		else if ( t == DS4_GGUF_TYPE_UINT16 || t == DS4_GGUF_TYPE_INT16 )
		{
			bytes64 = ((int64_t)n * 2);
			if ( bytes64 > (int64_t)INT32_MAX )
				return(-19);
			bytes = (int32_t)bytes64;
			if ( o > (len - bytes) )
				return(-20);
			o += bytes;
		}
		else if ( t == DS4_GGUF_TYPE_UINT32 || t == DS4_GGUF_TYPE_INT32 || t == DS4_GGUF_TYPE_FLOAT32 )
		{
			bytes64 = ((int64_t)n * 4);
			if ( bytes64 > (int64_t)INT32_MAX )
				return(-21);
			bytes = (int32_t)bytes64;
			if ( o > (len - bytes) )
				return(-22);
			o += bytes;
		}
		else if ( t == DS4_GGUF_TYPE_UINT64 || t == DS4_GGUF_TYPE_INT64 || t == DS4_GGUF_TYPE_FLOAT64 )
		{
			bytes64 = ((int64_t)n * 8);
			if ( bytes64 > (int64_t)INT32_MAX )
				return(-23);
			bytes = (int32_t)bytes64;
			if ( o > (len - bytes) )
				return(-24);
			o += bytes;
		}
		else if ( t == DS4_GGUF_TYPE_STRING )
		{
			int32_t i;
			for (i=0; i<(int32_t)n; i++)
			{
				ds4_gguf_str_t s;
				if ( ds4_gguf_take_str(buf,len,&o,&s) < 0 )
					return(-12);
			}
		}
		else
			return(-13);
	}
	else
		return(-14);
	if ( o < base )
		return(-15);
	if ( o > len )
		return(-16);
	*value = (buf + base);
	*value_len = (o - base);
	*off = o;
	return(0);
}

static int32_t ds4_gguf_scan_kv_at(const uint8_t *buf,int32_t len,int64_t kv_count,int64_t idx,ds4_gguf_kv_view_t *out)
{
	int32_t off;
	int64_t i;
	uint32_t value_type_u32;
	ds4_gguf_str_t key;
	const uint8_t *val;
	int32_t vlen;
	if ( buf == 0 )
		return(-1);
	if ( out == 0 )
		return(-2);
	if ( len < 24 )
		return(-3);
	if ( kv_count < 0 )
		return(-4);
	if ( idx < 0 )
		return(-5);
	if ( idx >= kv_count )
		return(-6);
	off = 24;
	for (i=0; i<idx; i++)
	{
		if ( ds4_gguf_take_str(buf,len,&off,&key) < 0 )
			return(-7);
		if ( ds4_gguf_take_u32le(buf,len,&off,&value_type_u32) < 0 )
			return(-8);
		if ( ds4_gguf_take_value(buf,len,&off,(int32_t)value_type_u32,&val,&vlen) < 0 )
			return(-9);
	}
	if ( ds4_gguf_take_str(buf,len,&off,&key) < 0 )
		return(-10);
	if ( ds4_gguf_take_u32le(buf,len,&off,&value_type_u32) < 0 )
		return(-11);
	if ( ds4_gguf_take_value(buf,len,&off,(int32_t)value_type_u32,&val,&vlen) < 0 )
		return(-12);
	out->key = key;
	out->value_type = (int32_t)value_type_u32;
	out->value = val;
	out->value_len = vlen;
	return(0);
}

int32_t ds4_gguf_parse_mem(ds4_gguf_view_t *out,const uint8_t *buf,int32_t len)
{
	int32_t off;
	int64_t i,kv_i64;
	uint32_t magic,version_u32,value_type_u32;
	uint64_t tensor_count,kv_count;
	ds4_gguf_str_t key;
	const uint8_t *val;
	int32_t vlen;
	uint32_t align_u32;
	if ( out == 0 )
		return(-1);
	if ( buf == 0 )
		return(-2);
	if ( len < 0 )
		return(-3);
	if ( len < 24 )
		return(-4);
	off = 0;
	if ( ds4_gguf_take_u32le(buf,len,&off,&magic) < 0 )
		return(-5);
	if ( magic != DS4_GGUF_MAGIC_U32 )
		return(-6);
	if ( ds4_gguf_take_u32le(buf,len,&off,&version_u32) < 0 )
		return(-7);
	if ( version_u32 != 3 )
		return(-8);
	if ( ds4_gguf_take_u64le(buf,len,&off,&tensor_count) < 0 )
		return(-9);
	if ( ds4_gguf_take_u64le(buf,len,&off,&kv_count) < 0 )
		return(-10);
	if ( kv_count > (uint64_t)INT64_MAX )
		return(-11);
	kv_i64 = (int64_t)kv_count;
	out->buf = buf;
	out->len = len;
	out->version = version_u32;
	out->tensor_count = tensor_count;
	out->metadata_kv_count = kv_count;
	out->alignment = 32;
	for (i=0; i<kv_i64; i++)
	{
		if ( ds4_gguf_take_str(buf,len,&off,&key) < 0 )
			return(-12);
		if ( ds4_gguf_take_u32le(buf,len,&off,&value_type_u32) < 0 )
			return(-13);
		if ( ds4_gguf_take_value(buf,len,&off,(int32_t)value_type_u32,&val,&vlen) < 0 )
			return(-14);
		if ( ds4_span_eq(key.ptr,key.len,"general.alignment") != 0 )
		{
			if ( value_type_u32 == DS4_GGUF_TYPE_UINT32 )
			{
				if ( vlen != 4 )
					return(-15);
				if ( ds4_gguf_u32le(val,vlen,0,&align_u32) < 0 )
					return(-16);
				if ( (align_u32 & 7u) != 0 )
					return(-17);
				out->alignment = align_u32;
			}
		}
	}
	out->tensor_infos_off = off;
	return(0);
}

int32_t ds4_gguf_kv_at(const ds4_gguf_view_t *g,int64_t idx,ds4_gguf_kv_view_t *out)
{
	int64_t kv_count;
	if ( g == 0 )
		return(-1);
	if ( out == 0 )
		return(-2);
	if ( g->metadata_kv_count > (uint64_t)INT64_MAX )
		return(-3);
	kv_count = (int64_t)g->metadata_kv_count;
	if ( ds4_gguf_scan_kv_at(g->buf,g->len,kv_count,idx,out) < 0 )
		return(-4);
	return(0);
}

int32_t ds4_gguf_find_kv(const ds4_gguf_view_t *g,const char *key,ds4_gguf_kv_view_t *out)
{
	int64_t i;
	ds4_gguf_kv_view_t kv;
	int32_t keylen;
	if ( g == 0 )
		return(-1);
	if ( key == 0 )
		return(-2);
	if ( out == 0 )
		return(-3);
	if ( g->metadata_kv_count > (uint64_t)INT64_MAX )
		return(-4);
	keylen = ds4_cstr_len_i32(key);
	if ( keylen <= 0 )
		return(-5);
	for (i=0; i<(int64_t)g->metadata_kv_count; i++)
	{
		if ( ds4_gguf_kv_at(g,i,&kv) < 0 )
			return(-6);
		if ( kv.key.len != keylen )
			continue;
		if ( ds4_span_eq(kv.key.ptr,kv.key.len,key) != 0 )
		{
			*out = kv;
			return(0);
		}
	}
	return(1);
}

int32_t ds4_gguf_kv_as_u32(const ds4_gguf_kv_view_t *kv,uint32_t *out)
{
	uint32_t v;
	if ( kv == 0 )
		return(-1);
	if ( out == 0 )
		return(-2);
	if ( kv->value_type != DS4_GGUF_TYPE_UINT32 )
		return(-3);
	if ( kv->value_len != 4 )
		return(-4);
	if ( ds4_gguf_u32le(kv->value,kv->value_len,0,&v) < 0 )
		return(-5);
	*out = v;
	return(0);
}

int32_t ds4_gguf_kv_as_string(const ds4_gguf_kv_view_t *kv,ds4_gguf_str_t *out)
{
	int32_t off;
	if ( kv == 0 )
		return(-1);
	if ( out == 0 )
		return(-2);
	if ( kv->value_type != DS4_GGUF_TYPE_STRING )
		return(-3);
	off = 0;
	if ( ds4_gguf_take_str(kv->value,kv->value_len,&off,out) < 0 )
		return(-4);
	if ( off != kv->value_len )
		return(-5);
	return(0);
}
