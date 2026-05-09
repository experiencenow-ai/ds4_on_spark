#pragma once

#include "ds4/common.h"

typedef enum
{
	DS4_LOG_ERROR = 0,
	DS4_LOG_WARN = 1,
	DS4_LOG_INFO = 2,
	DS4_LOG_DEBUG = 3
} ds4_log_level_t;

typedef void (*ds4_log_sink_fn)(void *ctx,int32_t level,const char *msg);

DS4_EXTERN_C_BEGIN
const char *ds4_log_level_name(int32_t level);
int32_t ds4_log_set_level(int32_t level);
int32_t ds4_log_set_sink(ds4_log_sink_fn fn,void *ctx);
int32_t ds4_logf(int32_t level,const char *fmt,...);
DS4_EXTERN_C_END

#define DS4_LOGE(...) ds4_logf(DS4_LOG_ERROR,__VA_ARGS__)
#define DS4_LOGW(...) ds4_logf(DS4_LOG_WARN,__VA_ARGS__)
#define DS4_LOGI(...) ds4_logf(DS4_LOG_INFO,__VA_ARGS__)
#define DS4_LOGD(...) ds4_logf(DS4_LOG_DEBUG,__VA_ARGS__)

typedef struct
{
	char *buf;
	int32_t cap,used,truncated;
} ds4_log_buf_t;

DS4_EXTERN_C_BEGIN
int32_t ds4_log_buf_init(ds4_log_buf_t *lb,char *buf,int32_t cap);
void ds4_log_buf_sink(void *ctx,int32_t level,const char *msg);
DS4_EXTERN_C_END
