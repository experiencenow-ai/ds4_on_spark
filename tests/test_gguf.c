#include "ds4/gguf.h"
#include "ds4/str.h"

#include <stdint.h>

#include "test_suite.h"

static void ds4_put_u32le(uint8_t *buf,int32_t off,uint32_t v)
{
	buf[off + 0] = (uint8_t)(v & 255u);
	buf[off + 1] = (uint8_t)((v >> 8) & 255u);
	buf[off + 2] = (uint8_t)((v >> 16) & 255u);
	buf[off + 3] = (uint8_t)((v >> 24) & 255u);
}

static void ds4_put_u64le(uint8_t *buf,int32_t off,uint64_t v)
{
	buf[off + 0] = (uint8_t)(v & 255u);
	buf[off + 1] = (uint8_t)((v >> 8) & 255u);
	buf[off + 2] = (uint8_t)((v >> 16) & 255u);
	buf[off + 3] = (uint8_t)((v >> 24) & 255u);
	buf[off + 4] = (uint8_t)((v >> 32) & 255u);
	buf[off + 5] = (uint8_t)((v >> 40) & 255u);
	buf[off + 6] = (uint8_t)((v >> 48) & 255u);
	buf[off + 7] = (uint8_t)((v >> 56) & 255u);
}

int32_t test_gguf(void)
{
	ds4_gguf_view_t g;
	ds4_gguf_kv_view_t kv;
	uint8_t buf0[24];
	uint8_t buf1[96];
	uint32_t v;
	int32_t i,off,klen;
	const char *k;
	for (i=0; i<(int32_t)sizeof(buf0); i++)
		buf0[i] = 0;
	ds4_put_u32le(buf0,0,0x46554747u);
	ds4_put_u32le(buf0,4,3u);
	ds4_put_u64le(buf0,8,0u);
	ds4_put_u64le(buf0,16,0u);
	if ( ds4_gguf_parse_mem(&g,buf0,(int32_t)sizeof(buf0)) < 0 )
		return(-1);
	if ( g.version != 3u )
		return(-2);
	if ( g.tensor_count != 0u )
		return(-3);
	if ( g.metadata_kv_count != 0u )
		return(-4);
	if ( g.alignment != 32u )
		return(-5);
	if ( ds4_gguf_find_kv(&g,"general.alignment",&kv) != 1 )
		return(-6);
	for (i=0; i<(int32_t)sizeof(buf1); i++)
		buf1[i] = 0;
	ds4_put_u32le(buf1,0,0x46554747u);
	ds4_put_u32le(buf1,4,3u);
	ds4_put_u64le(buf1,8,0u);
	ds4_put_u64le(buf1,16,1u);
	off = 24;
	k = "general.alignment";
	klen = ds4_cstr_len_i32(k);
	ds4_put_u64le(buf1,off,(uint64_t)klen);
	off += 8;
	for (i=0; i<klen; i++)
		buf1[off + i] = (uint8_t)k[i];
	off += klen;
	ds4_put_u32le(buf1,off,4u);
	off += 4;
	ds4_put_u32le(buf1,off,64u);
	off += 4;
	if ( ds4_gguf_parse_mem(&g,buf1,off) < 0 )
		return(-7);
	if ( g.metadata_kv_count != 1u )
		return(-8);
	if ( g.alignment != 64u )
		return(-9);
	if ( ds4_gguf_kv_at(&g,0,&kv) < 0 )
		return(-10);
	if ( kv.key.len != klen )
		return(-11);
	if ( ds4_span_eq(kv.key.ptr,kv.key.len,k) == 0 )
		return(-12);
	if ( ds4_gguf_kv_as_u32(&kv,&v) < 0 )
		return(-13);
	if ( v != 64u )
		return(-14);
	if ( ds4_gguf_find_kv(&g,k,&kv) < 0 )
		return(-15);
	if ( ds4_gguf_kv_as_u32(&kv,&v) < 0 )
		return(-16);
	if ( v != 64u )
		return(-17);
	return(0);
}
