#pragma once

#include "ds4/common.h"
#include "ds4/arena.h"
#include "ds4/pool.h"
#include "ds4/ring.h"
#include "ds4/config.h"
#include "ds4/gguf.h"
#include "ds4/log.h"
#include "ds4/log_ring.h"
#include "ds4/cuda.h"
#include "ds4/cuda_arena.h"

typedef struct
{
	ds4_config_t cfg;
	ds4_arena_t arena;
	ds4_log_ring_t log_ring;
	int32_t log_ring_ready;
	int32_t log_ring_attached;
} ds4_ctx_t;

DS4_EXTERN_C_BEGIN
int32_t ds4_ctx_init(ds4_ctx_t *ctx,const ds4_config_t *cfg,uint8_t *arena_mem,int32_t arena_size);
int32_t ds4_ctx_init_auto(ds4_ctx_t *ctx,const ds4_config_t *cfg,uint8_t *arena_mem,int32_t arena_size);
int32_t ds4_ctx_apply_config(ds4_ctx_t *ctx,const ds4_config_t *cfg);
int32_t ds4_ctx_deinit(ds4_ctx_t *ctx);
int32_t ds4_ctx_log_ring_init(ds4_ctx_t *ctx,ds4_log_entry_t *entries,int32_t entry_count);
int32_t ds4_ctx_log_ring_init_arena(ds4_ctx_t *ctx,int32_t entry_count);
int32_t ds4_ctx_log_ring_detach(ds4_ctx_t *ctx);
int32_t ds4_ctx_log_ring_count(ds4_ctx_t *ctx,int32_t *out_count);
int32_t ds4_ctx_log_ring_pop(ds4_ctx_t *ctx,ds4_log_entry_t *out);
DS4_EXTERN_C_END
