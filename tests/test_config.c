#include "ds4/config.h"

#include <stdint.h>

#include "test_suite.h"

int32_t test_config(void)
{
	ds4_config_t cfg;
	static const uint8_t buf0[] = "log_level=3\nenable_cuda=false\n";
	static const uint8_t buf1[] = "enable_cuda=ON\n";
	if ( ds4_config_defaults(&cfg) < 0 )
		return(-1);
	if ( ds4_config_parse_mem(&cfg,buf0,(int32_t)(sizeof(buf0) - 1)) < 0 )
		return(-2);
	if ( cfg.log_level != 3 )
		return(-3);
	if ( cfg.enable_cuda != 0 )
		return(-4);
	if ( ds4_config_parse_mem(&cfg,buf1,(int32_t)(sizeof(buf1) - 1)) < 0 )
		return(-5);
	if ( cfg.enable_cuda != 1 )
		return(-6);
	return(0);
}
