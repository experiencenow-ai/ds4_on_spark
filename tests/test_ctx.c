#include "ds4/ds4.h"

#include <stdint.h>

#include "test_suite.h"

int32_t test_ctx(void)
{
	ds4_ctx_t ctx;
	ds4_config_t cfg;
	uint8_t mem[128];
	if ( ds4_config_defaults(&cfg) < 0 )
		return(-1);
	if ( ds4_ctx_init(&ctx,&cfg,mem,(int32_t)sizeof(mem)) < 0 )
		return(-2);
	if ( ctx.cfg.log_level != cfg.log_level )
		return(-3);
	if ( ctx.arena.base != mem )
		return(-4);
	return(0);
}

