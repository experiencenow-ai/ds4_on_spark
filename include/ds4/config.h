#pragma once

#include <stdint.h>

typedef struct
{
	int32_t log_level;
	int32_t enable_cuda;
} ds4_config_t;

int32_t ds4_config_defaults(ds4_config_t *cfg);
int32_t ds4_config_parse_kv(ds4_config_t *cfg,const char *k,int32_t klen,const char *v,int32_t vlen);
int32_t ds4_config_parse_mem(ds4_config_t *cfg,const uint8_t *buf,int32_t len);
int32_t ds4_config_parse_file(ds4_config_t *cfg,const char *path,uint8_t *buf,int32_t cap,int32_t *out_len);
