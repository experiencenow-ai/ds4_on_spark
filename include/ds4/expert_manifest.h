#pragma once

#include "ds4/common.h"

#define DS4_EXPERT_MANIFEST_MAGIC "DS4EXM1"
#define DS4_EXPERT_MANIFEST_MAGIC_LEN 8
#define DS4_EXPERT_MANIFEST_VERSION 1
#define DS4_EXPERT_MANIFEST_HEADER_SIZE 128
#define DS4_EXPERT_MANIFEST_SHA256_HEX_LEN 64

typedef struct
{
	int32_t rank;
	int32_t world_size;
	int32_t num_layers;
	int32_t experts;
	int32_t layer_stride_bytes;
	int32_t payload_bytes;
	char owner_table_sha256[DS4_EXPERT_MANIFEST_SHA256_HEX_LEN + 1];
	const uint8_t *owned_bits;
	int32_t owned_bits_len;
} ds4_expert_manifest_view_t;

DS4_EXTERN_C_BEGIN
int32_t ds4_expert_manifest_required_bytes(int32_t num_layers,int32_t experts,int32_t *out_bytes);
int32_t ds4_expert_manifest_parse(ds4_expert_manifest_view_t *m,const uint8_t *buf,int32_t len);
int32_t ds4_expert_manifest_owns(const ds4_expert_manifest_view_t *m,int32_t layer,int32_t expert,int32_t *out_owns);
DS4_EXTERN_C_END
