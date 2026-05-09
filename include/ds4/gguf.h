#pragma once

#include "ds4/common.h"

typedef struct
{
	const uint8_t *buf;
	int32_t len;
	uint32_t version;
	uint64_t tensor_count;
	uint64_t metadata_kv_count;
	uint32_t alignment;
	int32_t tensor_infos_off;
} ds4_gguf_view_t;

typedef struct
{
	const char *ptr;
	int32_t len;
} ds4_gguf_str_t;

typedef struct
{
	ds4_gguf_str_t key;
	int32_t value_type;
	const uint8_t *value;
	int32_t value_len;
} ds4_gguf_kv_view_t;

DS4_EXTERN_C_BEGIN
int32_t ds4_gguf_parse_mem(ds4_gguf_view_t *out,const uint8_t *buf,int32_t len);
int32_t ds4_gguf_kv_at(const ds4_gguf_view_t *g,int64_t idx,ds4_gguf_kv_view_t *out);
int32_t ds4_gguf_find_kv(const ds4_gguf_view_t *g,const char *key,ds4_gguf_kv_view_t *out);
int32_t ds4_gguf_kv_as_u32(const ds4_gguf_kv_view_t *kv,uint32_t *out);
int32_t ds4_gguf_kv_as_string(const ds4_gguf_kv_view_t *kv,ds4_gguf_str_t *out);
DS4_EXTERN_C_END
