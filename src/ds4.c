#include "ds4/ds4.h"

ds4_version_t ds4_version(void)
{
	ds4_version_t v;
	v.v0 = (uint32_t)DS4_VERSION_V0;
	v.v1 = (uint32_t)DS4_VERSION_V1;
	v.v2 = (uint32_t)DS4_VERSION_V2;
	return(v);
}

int32_t ds4_ctx_log_ring_init(ds4_ctx_t *ctx,ds4_log_entry_t *entries,int32_t entry_count)
{
	if ( ctx == 0 )
		return(-1);
	ctx->log_ring_ready = 0;
	ctx->log_ring_attached = 0;
	if ( ds4_log_ring_init(&ctx->log_ring,entries,entry_count) < 0 )
		return(-2);
	ctx->log_ring_ready = 1;
	return(0);
}

int32_t ds4_ctx_log_ring_init_arena(ds4_ctx_t *ctx,int32_t entry_count)
{
	ds4_log_entry_t *entries;
	int64_t bytes64;
	int32_t bytes;
	if ( ctx == 0 )
		return(-1);
	if ( entry_count <= 0 )
		return(-2);
	bytes64 = ((int64_t)entry_count * (int64_t)sizeof(ds4_log_entry_t));
	if ( bytes64 > (int64_t)INT32_MAX )
		return(-3);
	bytes = (int32_t)bytes64;
	entries = 0;
	if ( ds4_arena_alloc(&ctx->arena,bytes,16,(void **)&entries) < 0 )
		return(-4);
	if ( entries == 0 )
		return(-5);
	return(ds4_ctx_log_ring_init(ctx,entries,entry_count));
}

int32_t ds4_ctx_log_ring_detach(ds4_ctx_t *ctx)
{
	if ( ctx == 0 )
		return(-1);
	if ( ctx->log_ring_attached != 0 )
	{
		ds4_log_set_sink(0,0);
		ctx->log_ring_attached = 0;
	}
	return(0);
}

int32_t ds4_ctx_log_ring_count(ds4_ctx_t *ctx,int32_t *out_count)
{
	if ( ctx == 0 )
		return(-1);
	if ( ctx->log_ring_ready == 0 )
		return(-2);
	return(ds4_log_ring_count(&ctx->log_ring,out_count));
}

int32_t ds4_ctx_log_ring_pop(ds4_ctx_t *ctx,ds4_log_entry_t *out)
{
	if ( ctx == 0 )
		return(-1);
	if ( ctx->log_ring_ready == 0 )
		return(-2);
	return(ds4_log_ring_pop(&ctx->log_ring,out));
}

static int32_t ds4_ctx_apply_log_ring(ds4_ctx_t *ctx,const ds4_config_t *cfg)
{
	int32_t cap;
	if ( ctx == 0 )
		return(-1);
	if ( cfg == 0 )
		return(-2);
	if ( cfg->log_ring_entries <= 0 )
	{
		if ( ctx->log_ring_attached != 0 )
		{
			ds4_log_set_sink(0,0);
			ctx->log_ring_attached = 0;
		}
		return(0);
	}
	if ( ctx->log_ring_ready == 0 )
		return(0);
	if ( ds4_ring_capacity(&ctx->log_ring.r,&cap) < 0 )
		return(-3);
	if ( cap < cfg->log_ring_entries )
		return(-4);
	ds4_log_set_sink(ds4_log_ring_sink,&ctx->log_ring);
	ctx->log_ring_attached = 1;
	return(0);
}

int32_t ds4_ctx_apply_config(ds4_ctx_t *ctx,const ds4_config_t *cfg)
{
	ds4_cuda_status_t st;
	if ( ctx == 0 )
		return(-1);
	if ( cfg == 0 )
		return(-2);
	ctx->cfg = *cfg;
	if ( ds4_log_set_level(cfg->log_level) < 0 )
		return(-3);
	if ( ds4_ctx_apply_log_ring(ctx,cfg) < 0 )
		return(-4);
	if ( cfg->enable_cuda != 0 )
	{
		if ( ds4_cuda_is_enabled_build() == 0 )
			return(-5);
		st = ds4_cuda_init();
		if ( ds4_cuda_is_ok(st) == 0 )
		{
			DS4_LOGE("ds4_ctx_apply_config: cuda init failed: %s",ds4_cuda_errstr(st));
			return(-6);
		}
		if ( cfg->cuda_device >= 0 )
		{
			st = ds4_cuda_set_device(cfg->cuda_device);
			if ( ds4_cuda_is_ok(st) == 0 )
			{
				DS4_LOGE("ds4_ctx_apply_config: cuda set_device(%d) failed: %s",cfg->cuda_device,ds4_cuda_errstr(st));
				return(-7);
			}
		}
	}
	return(0);
}

int32_t ds4_ctx_init_auto(ds4_ctx_t *ctx,const ds4_config_t *cfg,uint8_t *arena_mem,int32_t arena_size)
{
	ds4_config_t tmp;
	if ( ctx == 0 )
		return(-1);
	if ( cfg == 0 )
		return(-2);
	if ( arena_mem == 0 )
		return(-3);
	if ( arena_size <= 0 )
		return(-4);
	ctx->log_ring_ready = 0;
	ctx->log_ring_attached = 0;
	if ( ds4_arena_init_ex(&ctx->arena,arena_mem,arena_size,16) < 0 )
		return(-5);
	tmp = *cfg;
	if ( tmp.log_ring_entries > 0 )
	{
		if ( ds4_ctx_log_ring_init_arena(ctx,tmp.log_ring_entries) < 0 )
			return(-6);
	}
	if ( ds4_ctx_apply_config(ctx,&tmp) < 0 )
		return(-7);
	return(0);
}

int32_t ds4_ctx_init(ds4_ctx_t *ctx,const ds4_config_t *cfg,uint8_t *arena_mem,int32_t arena_size)
{
	if ( ctx == 0 )
		return(-1);
	if ( cfg == 0 )
		return(-2);
	if ( arena_mem == 0 )
		return(-3);
	if ( arena_size <= 0 )
		return(-4);
	ctx->log_ring_ready = 0;
	ctx->log_ring_attached = 0;
	if ( ds4_arena_init_ex(&ctx->arena,arena_mem,arena_size,16) < 0 )
		return(-5);
	if ( ds4_ctx_apply_config(ctx,cfg) < 0 )
		return(-6);
	return(0);
}
