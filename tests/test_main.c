#include <stdint.h>
#include <stdio.h>

#include "test_suite.h"

int main(void)
{
	int32_t err;
	err = 0;
	if ( test_arena() < 0 )
		err = -1;
	if ( test_pool() < 0 )
		err = -2;
	if ( test_ring() < 0 )
		err = -3;
	if ( test_version() < 0 )
		err = -4;
	if ( test_config() < 0 )
		err = -5;
	if ( test_log() < 0 )
		err = -6;
	if ( test_ctx() < 0 )
		err = -7;
	if ( test_cuda() < 0 )
		err = -8;
	if ( test_gguf() < 0 )
		err = -9;
	if ( err < 0 )
	{
		fprintf(stderr,"ds4_tests failed (%d)\n",err);
		return(1);
	}
	return(0);
}
