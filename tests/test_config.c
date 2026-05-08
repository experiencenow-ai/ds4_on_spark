#include "ds4/config.h"

#include <stdint.h>

#include "test_suite.h"

int32_t test_config(void)
{
	ds4_config_t cfg;
	static const uint8_t buf[] = "log_level=3\nenable_cuda=0\n";
	if ( ds4_config_defaults(&cfg) < 0 )
		return(-1);
	if ( ds4_config_parse_mem(&cfg,buf,(int32_t)(sizeof(buf) - 1)) < 0 )
		return(-2);
	if ( cfg.log_level != 3 )
		return(-3);
	if ( cfg.enable_cuda != 0 )
		return(-4);
	return(0);
}
