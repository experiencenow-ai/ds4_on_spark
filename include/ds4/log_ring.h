#pragma once

#include "ds4/log.h"
#include "ds4/ring.h"

#define DS4_LOG_RING_MSG_CAP 256

typedef struct
{
	int32_t level;
	int32_t truncated;
	char msg[DS4_LOG_RING_MSG_CAP];
} ds4_log_entry_t;

typedef struct
{
	ds4_ring_t r;
	int32_t dropped;
} ds4_log_ring_t;

DS4_EXTERN_C_BEGIN
int32_t ds4_log_ring_init(ds4_log_ring_t *lr,ds4_log_entry_t *entries,int32_t entry_count);
int32_t ds4_log_ring_reset(ds4_log_ring_t *lr);
int32_t ds4_log_ring_count(ds4_log_ring_t *lr,int32_t *out_count);
int32_t ds4_log_ring_dropped(ds4_log_ring_t *lr,int32_t *out_dropped);
int32_t ds4_log_ring_pop(ds4_log_ring_t *lr,ds4_log_entry_t *out);
int32_t ds4_log_entry_format(const ds4_log_entry_t *e,char *out,int32_t cap);
int32_t ds4_log_ring_drain_format(ds4_log_ring_t *lr,char *out,int32_t cap,int32_t *out_truncated);
void ds4_log_ring_sink(void *ctx,int32_t level,const char *msg);
DS4_EXTERN_C_END
