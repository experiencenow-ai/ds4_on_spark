#include "ds4/cuda.h"

#include "test_suite.h"

int32_t test_cuda(void)
{
	ds4_cuda_status_t st;
	const char *s;
	st = ds4_cuda_last_error();
	if ( ds4_cuda_is_ok(st) != 0 )
		return(-1);
	s = ds4_cuda_errstr(st);
	if ( s == 0 )
		return(-2);
	return(0);
}

