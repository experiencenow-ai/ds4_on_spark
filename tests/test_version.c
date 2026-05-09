#include "ds4/common.h"

#include <stdint.h>

#include "test_suite.h"

int32_t test_version(void)
{
	ds4_version_t v;
	v = ds4_version();
	if ( v.v0 != (uint32_t)DS4_VERSION_V0 )
		return(-1);
	if ( v.v1 != (uint32_t)DS4_VERSION_V1 )
		return(-2);
	if ( v.v2 != (uint32_t)DS4_VERSION_V2 )
		return(-3);
	return(0);
}
