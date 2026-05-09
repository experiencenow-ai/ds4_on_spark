#include "ds4/config.h"
#include "ds4/str.h"

#include <stdint.h>
#include <stdlib.h>
#include <unistd.h>

#include "test_suite.h"

static int32_t ds4_write_all(int32_t fd,const uint8_t *buf,int32_t len)
{
	int32_t off,rc;
	if ( fd < 0 )
		return(-1);
	if ( buf == 0 )
		return(-2);
	if ( len < 0 )
		return(-3);
	off = 0;
	for (; off<len; )
	{
		rc = (int32_t)write(fd,buf + off,(size_t)(len - off));
		if ( rc <= 0 )
			return(-4);
		off += rc;
	}
	return(0);
}

int32_t test_config(void)
{
	ds4_config_t cfg;
	static const uint8_t buf0[] = "log_level=3\nenable_cuda=false\n";
	static const uint8_t buf1[] = "enable_cuda=ON\n";
	static const uint8_t fbuf[] = "log_level=0\nenable_cuda=1\n";
	char path[64];
	char out[64];
	int32_t fd,plen,n;
	uint8_t io_buf[64];
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
	if ( ds4_config_defaults(&cfg) < 0 )
		return(-7);
	if ( setenv("DS4_LOG_LEVEL","1",1) != 0 )
		return(-8);
	if ( setenv("DS4_ENABLE_CUDA","yes",1) != 0 )
		return(-9);
	if ( ds4_config_parse_env(&cfg) < 0 )
		return(-10);
	if ( cfg.log_level != 1 )
		return(-11);
	if ( cfg.enable_cuda != 1 )
		return(-12);
	unsetenv("DS4_LOG_LEVEL");
	unsetenv("DS4_ENABLE_CUDA");
	for (n=0; n<(int32_t)sizeof(path); n++)
		path[n] = 0;
	plen = ds4_cstr_len_i32("/tmp/ds4_cfg_XXXXXX");
	if ( plen <= 0 )
		return(-13);
	for (n=0; n<plen && n<((int32_t)sizeof(path) - 1); n++)
		path[n] = "/tmp/ds4_cfg_XXXXXX"[n];
	path[n] = 0;
	fd = mkstemp(path);
	if ( fd < 0 )
		return(-14);
	if ( ds4_write_all(fd,fbuf,(int32_t)(sizeof(fbuf) - 1)) < 0 )
	{
		close(fd);
		unlink(path);
		return(-15);
	}
	close(fd);
	unsetenv("DS4_LOG_LEVEL");
	unsetenv("DS4_ENABLE_CUDA");
	if ( setenv("DS4_LOG_LEVEL","2",1) != 0 )
	{
		unlink(path);
		return(-16);
	}
	if ( ds4_config_load(&cfg,path,io_buf,(int32_t)sizeof(io_buf),0) < 0 )
	{
		unlink(path);
		return(-17);
	}
	if ( cfg.log_level != 2 )
	{
		unlink(path);
		return(-18);
	}
	if ( cfg.enable_cuda != 1 )
	{
		unlink(path);
		return(-19);
	}
	if ( ds4_config_format(&cfg,out,(int32_t)sizeof(out)) < 0 )
	{
		unlink(path);
		return(-20);
	}
	if ( out[0] == 0 )
	{
		unlink(path);
		return(-21);
	}
	unlink(path);
	unsetenv("DS4_LOG_LEVEL");
	return(0);
}
