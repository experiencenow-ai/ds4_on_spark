#pragma once

#include "ds4/common.h"
#include "ds4/arena.h"
#include "ds4/config.h"
#include "ds4/log.h"
#include "ds4/cuda.h"

typedef struct
{
	ds4_config_t cfg;
	ds4_arena_t arena;
} ds4_ctx_t;

int32_t ds4_ctx_init(ds4_ctx_t *ctx,const ds4_config_t *cfg,uint8_t *arena_mem,int32_t arena_size);
int32_t ds4_ctx_apply_config(ds4_ctx_t *ctx,const ds4_config_t *cfg);
