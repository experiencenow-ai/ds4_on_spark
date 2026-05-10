#include "ds4/ds4.h"

#include <stdint.h>

#include "test_suite.h"

int32_t test_ctx(void)
{
	ds4_ctx_t ctx;
	ds4_config_t cfg;
	ds4_cuda_status_t st;
	uint8_t mem[128];
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
	return(0);
}
