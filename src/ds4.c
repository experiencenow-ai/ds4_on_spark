#include "ds4/ds4.h"

#include <inttypes.h>
#include <limits.h>
#include <stdarg.h>
#include <stdio.h>

ds4_version_t ds4_version(void)
{
	ds4_version_t v;
	v.v0 = (uint32_t)DS4_VERSION_V0;
	v.v1 = (uint32_t)DS4_VERSION_V1;
	v.v2 = (uint32_t)DS4_VERSION_V2;
	return(v);
}

static int32_t ds4_buf_appendf(char *out,int32_t cap,int32_t *io_used,const char *fmt,...)
{
	va_list ap;
	int32_t used;
	int32_t avail;
	int32_t n;
	if ( out == 0 )
		return(-1);
	if ( io_used == 0 )
		return(-2);
	if ( fmt == 0 )
		return(-3);
	if ( cap <= 0 )
		return(-4);
	used = *io_used;
	if ( used < 0 )
		used = 0;
	if ( used >= cap )
	{
		out[cap - 1] = 0;
		*io_used = (cap - 1);
		return(-5);
	}
	avail = (cap - used);
	va_start(ap,fmt);
	n = (int32_t)vsnprintf(out + used,(size_t)avail,fmt,ap);
	va_end(ap);
	if ( n < 0 )
		return(-6);
	out[cap - 1] = 0;
	if ( n >= avail )
	{
		*io_used = (cap - 1);
		return(-7);
	}
	*io_used = (used + n);
	return(0);
}

int32_t ds4_ctx_auto_arena_bytes(const ds4_config_t *cfg,int32_t *out_bytes)
{
	int64_t bytes64;
	if ( cfg == 0 )
		return(-1);
	if ( out_bytes == 0 )
		return(-2);
	*out_bytes = 0;
	if ( cfg->log_ring_entries <= 0 )
		return(0);
	bytes64 = ((int64_t)cfg->log_ring_entries * (int64_t)sizeof(ds4_log_entry_t));
	if ( bytes64 > (int64_t)INT32_MAX )
		return(-3);
	*out_bytes = (int32_t)bytes64;
	return(0);
}

int32_t ds4_ctx_format(const ds4_ctx_t *ctx,char *out,int32_t cap)
{
	int32_t used;
	int32_t n;
	int32_t rc;
	int32_t ring_cap;
	int32_t ring_count;
	int32_t ring_dropped;
	if ( ctx == 0 )
		return(-1);
	if ( out == 0 )
		return(-2);
	if ( cap <= 0 )
		return(-3);
	out[0] = 0;
	n = ds4_config_format(&ctx->cfg,out,cap);
	if ( n < 0 )
		return(-4);
	used = n;
	if ( ds4_buf_appendf(out,cap,&used,"arena_used=%d\n",ctx->arena.used) < 0 )
		return(-5);
	if ( ds4_buf_appendf(out,cap,&used,"log_ring_ready=%d\nlog_ring_attached=%d\n",ctx->log_ring_ready,ctx->log_ring_attached) < 0 )
		return(-6);
	if ( ctx->log_ring_ready != 0 )
	{
		ring_cap = -1;
		rc = ds4_ring_capacity((ds4_ring_t *)&ctx->log_ring.r,&ring_cap);
		if ( rc < 0 )
			ring_cap = -1;
		ring_count = -1;
		rc = ds4_log_ring_count((ds4_log_ring_t *)&ctx->log_ring,&ring_count);
		if ( rc < 0 )
			ring_count = -1;
		ring_dropped = -1;
		rc = ds4_log_ring_dropped((ds4_log_ring_t *)&ctx->log_ring,&ring_dropped);
		if ( rc < 0 )
			ring_dropped = -1;
		if ( ds4_buf_appendf(out,cap,&used,"log_ring_cap=%d\nlog_ring_count=%d\nlog_ring_dropped=%d\n",ring_cap,ring_count,ring_dropped) < 0 )
			return(-7);
	}
	if ( ds4_buf_appendf(out,cap,&used,"cuda_arena_owns=%d\ncuda_arena_size=%" PRId64 "\ncuda_arena_used=%" PRId64 "\n",ctx->cuda_arena.owns_base,ctx->cuda_arena.size,ctx->cuda_arena.used) < 0 )
		return(-8);
	return(0);
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

int32_t ds4_ctx_deinit(ds4_ctx_t *ctx)
{
	if ( ctx == 0 )
		return(-1);
	if ( ds4_ctx_log_ring_detach(ctx) < 0 )
		return(-2);
	if ( ds4_cuda_arena_deinit(&ctx->cuda_arena) != 0 )
		return(-3);
	ctx->log_ring_ready = 0;
	ctx->log_ring_attached = 0;
	ctx->log_ring = (ds4_log_ring_t){0};
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

int32_t ds4_ctx_log_ring_dropped(ds4_ctx_t *ctx,int32_t *out_dropped)
{
	if ( ctx == 0 )
		return(-1);
	if ( ctx->log_ring_ready == 0 )
		return(-2);
	return(ds4_log_ring_dropped(&ctx->log_ring,out_dropped));
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

static int32_t ds4_ctx_apply_cuda_arena(ds4_ctx_t *ctx,const ds4_config_t *cfg)
{
	ds4_cuda_status_t st;
	int32_t err;
	if ( ctx == 0 )
		return(-1);
	if ( cfg == 0 )
		return(-2);
	if ( cfg->cuda_arena_size <= 0 )
	{
		if ( ds4_cuda_arena_deinit(&ctx->cuda_arena) != 0 )
			return(-3);
		return(0);
	}
	if ( cfg->enable_cuda == 0 )
		return(-4);
	if ( ds4_cuda_arena_deinit(&ctx->cuda_arena) != 0 )
		return(-5);
	err = ds4_cuda_arena_init_malloc(&ctx->cuda_arena,(int64_t)cfg->cuda_arena_size);
	if ( err != 0 )
	{
		st = ds4_cuda_fail(err);
		DS4_LOGE("ds4_ctx_apply_cuda_arena: init_malloc(%d) failed: %s",cfg->cuda_arena_size,ds4_cuda_errstr(st));
		return(-6);
	}
	return(0);
}

int32_t ds4_ctx_apply_config(ds4_ctx_t *ctx,const ds4_config_t *cfg)
{
	ds4_cuda_status_t st;
	if ( ctx == 0 )
		return(-1);
	if ( cfg == 0 )
		return(-2);
	if ( ds4_config_validate(cfg) < 0 )
		return(-8);
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
		if ( ds4_ctx_apply_cuda_arena(ctx,cfg) < 0 )
			return(-9);
	}
	else
	{
		if ( ds4_ctx_apply_cuda_arena(ctx,cfg) < 0 )
			return(-10);
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
	ctx->cuda_arena = (ds4_cuda_arena_t){0};
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
	ctx->cuda_arena = (ds4_cuda_arena_t){0};
	if ( ds4_arena_init_ex(&ctx->arena,arena_mem,arena_size,16) < 0 )
		return(-5);
	if ( ds4_ctx_apply_config(ctx,cfg) < 0 )
		return(-6);
	return(0);
}
