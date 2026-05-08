#pragma once

#include <stdint.h>

typedef enum
{
	DS4_LOG_ERROR = 0,
	DS4_LOG_WARN = 1,
	DS4_LOG_INFO = 2,
	DS4_LOG_DEBUG = 3
} ds4_log_level_t;

typedef void (*ds4_log_sink_fn)(void *ctx,int32_t level,const char *msg);

int32_t ds4_log_set_level(int32_t level);
int32_t ds4_log_set_sink(ds4_log_sink_fn fn,void *ctx);
int32_t ds4_logf(int32_t level,const char *fmt,...);
