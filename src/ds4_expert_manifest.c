#include "ds4/expert_manifest.h"

#include <limits.h>

static uint32_t ds4_manifest_le_u32(const uint8_t *p)
{
	uint32_t v0,v1,v2,v3;
	v0 = (uint32_t)p[0];
	v1 = ((uint32_t)p[1] << 8);
	v2 = ((uint32_t)p[2] << 16);
	v3 = ((uint32_t)p[3] << 24);
	return((uint32_t)(v0 | v1 | v2 | v3));
}

static int32_t ds4_manifest_read_i32(const uint8_t *p,int32_t *out)
{
	uint32_t u;
	if ( p == 0 )
		return(-1);
	if ( out == 0 )
		return(-2);
	u = ds4_manifest_le_u32(p);
	if ( u > (uint32_t)INT32_MAX )
		return(-3);
	*out = (int32_t)u;
	return(0);
}

static int32_t ds4_manifest_hex_char(uint8_t c)
{
	if ( c >= '0' && c <= '9' )
		return(1);
	if ( c >= 'a' && c <= 'f' )
		return(1);
	if ( c >= 'A' && c <= 'F' )
		return(1);
	return(0);
}

static int32_t ds4_manifest_check_hash(const uint8_t *p,char *out)
{
	int32_t i;
	if ( p == 0 )
		return(-1);
	if ( out == 0 )
		return(-2);
	for (i=0; i<DS4_EXPERT_MANIFEST_SHA256_HEX_LEN; i++)
	{
		if ( ds4_manifest_hex_char(p[i]) == 0 )
			return(-3);
		out[i] = (char)p[i];
	}
	out[DS4_EXPERT_MANIFEST_SHA256_HEX_LEN] = 0;
	return(0);
}

int32_t ds4_expert_manifest_required_bytes(int32_t num_layers,int32_t experts,int32_t *out_bytes)
{
	int32_t stride;
	int64_t payload,total;
	if ( out_bytes == 0 )
		return(-1);
	*out_bytes = 0;
	if ( num_layers <= 0 )
		return(-2);
	if ( experts <= 0 )
		return(-3);
	stride = ((experts + 7) / 8);
	payload = ((int64_t)stride * (int64_t)num_layers);
	total = ((int64_t)DS4_EXPERT_MANIFEST_HEADER_SIZE + payload);
	if ( total > (int64_t)INT32_MAX )
		return(-4);
	*out_bytes = (int32_t)total;
	return(0);
}

int32_t ds4_expert_manifest_parse(ds4_expert_manifest_view_t *m,const uint8_t *buf,int32_t len)
{
	int32_t header_size,version,rank,world_size,num_layers,experts,stride,payload,required;
	int32_t i;
	if ( m == 0 )
		return(-1);
	if ( buf == 0 )
		return(-2);
	if ( len < DS4_EXPERT_MANIFEST_HEADER_SIZE )
		return(-3);
	for (i=0; i<7; i++)
	{
		if ( buf[i] != (uint8_t)DS4_EXPERT_MANIFEST_MAGIC[i] )
			return(-4);
	}
	if ( buf[7] != 0 )
		return(-5);
	if ( ds4_manifest_read_i32(buf + 8,&header_size) < 0 )
		return(-6);
	if ( ds4_manifest_read_i32(buf + 12,&version) < 0 )
		return(-7);
	if ( ds4_manifest_read_i32(buf + 16,&rank) < 0 )
		return(-8);
	if ( ds4_manifest_read_i32(buf + 20,&world_size) < 0 )
		return(-9);
	if ( ds4_manifest_read_i32(buf + 24,&num_layers) < 0 )
		return(-10);
	if ( ds4_manifest_read_i32(buf + 28,&experts) < 0 )
		return(-11);
	if ( ds4_manifest_read_i32(buf + 32,&stride) < 0 )
		return(-12);
	if ( ds4_manifest_read_i32(buf + 36,&payload) < 0 )
		return(-13);
	if ( header_size != DS4_EXPERT_MANIFEST_HEADER_SIZE )
		return(-14);
	if ( version != DS4_EXPERT_MANIFEST_VERSION )
		return(-15);
	if ( world_size <= 0 )
		return(-16);
	if ( rank < 0 || rank >= world_size )
		return(-17);
	if ( num_layers <= 0 )
		return(-18);
	if ( experts <= 0 )
		return(-19);
	if ( stride != ((experts + 7) / 8) )
		return(-20);
	if ( (int64_t)payload != ((int64_t)stride * (int64_t)num_layers) )
		return(-21);
	if ( ds4_expert_manifest_required_bytes(num_layers,experts,&required) < 0 )
		return(-22);
	if ( len < required )
		return(-23);
	if ( ds4_manifest_check_hash(buf + 40,m->owner_table_sha256) < 0 )
		return(-24);
	m->rank = rank;
	m->world_size = world_size;
	m->num_layers = num_layers;
	m->experts = experts;
	m->layer_stride_bytes = stride;
	m->payload_bytes = payload;
	m->owned_bits = (buf + header_size);
	m->owned_bits_len = payload;
	return(0);
}

int32_t ds4_expert_manifest_owns(const ds4_expert_manifest_view_t *m,int32_t layer,int32_t expert,int32_t *out_owns)
{
	const uint8_t *row;
	uint8_t mask;
	if ( out_owns == 0 )
		return(-1);
	*out_owns = 0;
	if ( m == 0 )
		return(-2);
	if ( m->owned_bits == 0 )
		return(-3);
	if ( layer < 0 || layer >= m->num_layers )
		return(-4);
	if ( expert < 0 || expert >= m->experts )
		return(-5);
	row = (m->owned_bits + (layer * m->layer_stride_bytes));
	mask = (uint8_t)(1u << (expert & 7));
	if ( (row[expert >> 3] & mask) != 0 )
		*out_owns = 1;
	return(0);
}
