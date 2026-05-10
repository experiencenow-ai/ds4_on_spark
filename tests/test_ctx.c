#include "ds4/ds4.h"

#include <stdint.h>
#include <string.h>

#include "test_suite.h"

int32_t test_ctx(void)
{
	ds4_ctx_t ctx;
	ds4_config_t cfg;
	ds4_cuda_status_t st;
	uint8_t mem[128];
	ds4_log_entry_t log_entries[4],e;
	int32_t c;
	int32_t err;
	if ( ds4_config_defaults(&cfg) < 0 )
		return(-1);
	if ( ds4_ctx_init(&ctx,&cfg,mem,(int32_t)sizeof(mem)) < 0 )
		return(-2);
	if ( ctx.cfg.log_level != cfg.log_level )
		return(-3);
	if ( ctx.arena.base != mem )
		return(-4);
	cfg.enable_cuda = 1;
	err = ds4_ctx_apply_config(&ctx,&cfg);
	if ( ds4_cuda_is_enabled_build() == 0 )
	{
		if ( err >= 0 )
			return(-5);
	}
	else
	{
		st = ds4_cuda_init();
		if ( ds4_cuda_is_ok(st) == 0 )
		{
			if ( err >= 0 )
				return(-6);
		}
		else
		{
			if ( err < 0 )
				return(-7);
		}
	}
	cfg.enable_cuda = 0;
	if ( ds4_ctx_log_ring_init(&ctx,log_entries,(int32_t)(sizeof(log_entries) / sizeof(log_entries[0]))) < 0 )
		return(-8);
	cfg.log_ring_entries = (int32_t)(sizeof(log_entries) / sizeof(log_entries[0]));
	if ( ds4_ctx_apply_config(&ctx,&cfg) < 0 )
		return(-9);
	if ( DS4_LOGI("ctx log ring") < 0 )
		return(-10);
	if ( ds4_ctx_log_ring_count(&ctx,&c) < 0 )
		return(-11);
	if ( c <= 0 )
		return(-12);
	if ( ds4_ctx_log_ring_pop(&ctx,&e) < 0 )
		return(-13);
	if ( strcmp(e.msg,"ctx log ring") != 0 )
		return(-14);
	cfg.log_ring_entries = 0;
	if ( ds4_ctx_apply_config(&ctx,&cfg) < 0 )
		return(-15);
	return(0);
}
