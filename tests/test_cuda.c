#include "ds4/cuda.h"

#include "test_suite.h"

int32_t test_cuda(void)
{
	ds4_cuda_status_t st0,st1,st2;
	const char *s;
	st0 = ds4_cuda_ok();
	if ( ds4_cuda_is_ok(st0) == 0 )
		return(-1);
	st1 = ds4_cuda_fail(123);
	if ( ds4_cuda_is_ok(st1) != 0 )
		return(-2);
	s = ds4_cuda_errstr(st0);
	if ( s == 0 )
		return(-3);
	s = ds4_cuda_errstr(st1);
	if ( s == 0 )
		return(-4);
	st2 = ds4_cuda_last_error();
	s = ds4_cuda_errstr(st2);
	if ( s == 0 )
		return(-5);
	return(0);
}
