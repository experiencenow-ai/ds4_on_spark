#include "ds4/ds4.h"

ds4_version_t ds4_version(void)
{
	ds4_version_t v;
	v.v0 = 0;
	v.v1 = 0;
	v.v2 = 0;
	return(v);
}

int32_t ds4_ctx_apply_config(ds4_ctx_t *ctx,const ds4_config_t *cfg)
{
	if ( ctx == 0 )
		return(-1);
	if ( cfg == 0 )
		return(-2);
	if ( cfg->enable_cuda != 0 )
	{
		if ( ds4_cuda_is_enabled_build() == 0 )
			return(-3);
	}
	ctx->cfg = *cfg;
	if ( ds4_log_set_level(cfg->log_level) < 0 )
		return(-4);
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
	if ( ds4_arena_init(&ctx->arena,arena_mem,arena_size) < 0 )
		return(-5);
	if ( ds4_ctx_apply_config(ctx,cfg) < 0 )
		return(-6);
	return(0);
}
