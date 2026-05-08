#include <stdint.h>
#include <stdio.h>

#include "test_suite.h"

int main(void)
{
	int32_t err;
	err = 0;
	if ( test_arena() < 0 )
		err = -1;
	if ( test_config() < 0 )
		err = -2;
	if ( test_log() < 0 )
		err = -3;
	if ( test_ctx() < 0 )
		err = -4;
	if ( test_cuda() < 0 )
		err = -5;
	if ( err < 0 )
	{
		fprintf(stderr,"ds4_tests failed (%d)\n",err);
		return(1);
	}
	return(0);
}
