#pragma once

#include "ds4/common.h"

typedef struct
{
	int32_t log_level;
	int32_t enable_cuda;
	int32_t cuda_device;
	int32_t arena_size;
	int32_t cuda_arena_size;
	int32_t log_ring_entries;
} ds4_config_t;

typedef struct
{
	int32_t stage;
	int32_t line;
	int32_t err;
	int32_t unknown;
} ds4_config_diag_t;

#define DS4_CONFIG_DIAG_STAGE_NONE 0
#define DS4_CONFIG_DIAG_STAGE_MEM 1
#define DS4_CONFIG_DIAG_STAGE_FILE 2
#define DS4_CONFIG_DIAG_STAGE_LOAD 3

#define DS4_CONFIG_PARSE_STRICT_UNKNOWN 1

#define DS4_LOG_LEVEL_MIN 0
#define DS4_LOG_LEVEL_MAX 3

#define DS4_CUDA_DEVICE_AUTO (-1)

DS4_EXTERN_C_BEGIN
int32_t ds4_config_diag_init(ds4_config_diag_t *d);
int32_t ds4_config_defaults(ds4_config_t *cfg);
int32_t ds4_config_validate(const ds4_config_t *cfg);
int32_t ds4_config_parse_kv(ds4_config_t *cfg,const char *k,int32_t klen,const char *v,int32_t vlen);
int32_t ds4_config_parse_kv_cstr(ds4_config_t *cfg,const char *k,const char *v);
int32_t ds4_config_parse_mem(ds4_config_t *cfg,const uint8_t *buf,int32_t len);
int32_t ds4_config_parse_mem_ex(ds4_config_t *cfg,const uint8_t *buf,int32_t len,int32_t flags,int32_t *out_unknown);
int32_t ds4_config_parse_mem_ex_diag(ds4_config_t *cfg,const uint8_t *buf,int32_t len,int32_t flags,int32_t *out_unknown,ds4_config_diag_t *diag);
int32_t ds4_config_parse_file(ds4_config_t *cfg,const char *path,uint8_t *buf,int32_t cap,int32_t *out_len);
int32_t ds4_config_parse_file_ex(ds4_config_t *cfg,const char *path,uint8_t *buf,int32_t cap,int32_t *out_len,int32_t flags,int32_t *out_unknown);
int32_t ds4_config_parse_file_ex_diag(ds4_config_t *cfg,const char *path,uint8_t *buf,int32_t cap,int32_t *out_len,int32_t flags,int32_t *out_unknown,ds4_config_diag_t *diag);
int32_t ds4_config_parse_env(ds4_config_t *cfg);
int32_t ds4_config_load(ds4_config_t *cfg,const char *path,uint8_t *buf,int32_t cap,int32_t *out_len);
int32_t ds4_config_load_auto(ds4_config_t *cfg,const char *path,uint8_t *buf,int32_t cap,int32_t *out_len);
int32_t ds4_config_load_ex(ds4_config_t *cfg,const char *path,uint8_t *buf,int32_t cap,int32_t *out_len,int32_t flags,int32_t *out_unknown);
int32_t ds4_config_load_auto_ex(ds4_config_t *cfg,const char *path,uint8_t *buf,int32_t cap,int32_t *out_len,int32_t flags,int32_t *out_unknown);
int32_t ds4_config_load_auto_ex_diag(ds4_config_t *cfg,const char *path,uint8_t *buf,int32_t cap,int32_t *out_len,int32_t flags,int32_t *out_unknown,ds4_config_diag_t *diag);
int32_t ds4_config_format(const ds4_config_t *cfg,char *out,int32_t cap);
DS4_EXTERN_C_END
