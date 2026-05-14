#include "ds4/expert_manifest.h"

#include <stdint.h>
#include <string.h>

#include "test_suite.h"

static void test_manifest_put_u32(uint8_t *p,uint32_t v)
{
	p[0] = (uint8_t)(v & 0xffu);
	p[1] = (uint8_t)((v >> 8) & 0xffu);
	p[2] = (uint8_t)((v >> 16) & 0xffu);
	p[3] = (uint8_t)((v >> 24) & 0xffu);
}

static void test_manifest_fill(uint8_t *buf,int32_t len)
{
	int32_t i;
	memset(buf,0,(size_t)len);
	memcpy(buf,DS4_EXPERT_MANIFEST_MAGIC,7);
	test_manifest_put_u32(buf + 8,(uint32_t)DS4_EXPERT_MANIFEST_HEADER_SIZE);
	test_manifest_put_u32(buf + 12,(uint32_t)DS4_EXPERT_MANIFEST_VERSION);
	test_manifest_put_u32(buf + 16,0);
	test_manifest_put_u32(buf + 20,3);
	test_manifest_put_u32(buf + 24,2);
	test_manifest_put_u32(buf + 28,5);
	test_manifest_put_u32(buf + 32,1);
	test_manifest_put_u32(buf + 36,2);
	for (i=0; i<DS4_EXPERT_MANIFEST_SHA256_HEX_LEN; i++)
		buf[40 + i] = (uint8_t)'a';
	buf[DS4_EXPERT_MANIFEST_HEADER_SIZE + 0] = 0x09;
	buf[DS4_EXPERT_MANIFEST_HEADER_SIZE + 1] = 0x10;
}

int32_t test_expert_manifest(void)
{
	uint8_t buf[DS4_EXPERT_MANIFEST_HEADER_SIZE + 2];
	ds4_expert_manifest_view_t m;
	int32_t owns,bytes;
	test_manifest_fill(buf,(int32_t)sizeof(buf));
	bytes = -1;
	if ( ds4_expert_manifest_required_bytes(2,5,&bytes) < 0 )
		return(-1);
	if ( bytes != (int32_t)sizeof(buf) )
		return(-2);
	if ( ds4_expert_manifest_parse(&m,buf,(int32_t)sizeof(buf)) < 0 )
		return(-3);
	if ( m.rank != 0 || m.world_size != 3 || m.num_layers != 2 || m.experts != 5 )
		return(-4);
	if ( strcmp(m.owner_table_sha256,"aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa") != 0 )
		return(-5);
	if ( ds4_expert_manifest_owns(&m,0,0,&owns) < 0 || owns != 1 )
		return(-6);
	if ( ds4_expert_manifest_owns(&m,0,3,&owns) < 0 || owns != 1 )
		return(-7);
	if ( ds4_expert_manifest_owns(&m,0,4,&owns) < 0 || owns != 0 )
		return(-8);
	if ( ds4_expert_manifest_owns(&m,1,4,&owns) < 0 || owns != 1 )
		return(-9);
	if ( ds4_expert_manifest_owns(&m,2,0,&owns) >= 0 )
		return(-10);
	buf[0] = (uint8_t)'X';
	if ( ds4_expert_manifest_parse(&m,buf,(int32_t)sizeof(buf)) >= 0 )
		return(-11);
	return(0);
}
