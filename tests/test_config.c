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
	static const uint8_t buf2[] = "log_level=0 # comment\n# full line comment\n enable_cuda = yes\t# trailing\n";
	static const uint8_t buf3[] = "log_level=debug\nenable_cuda=0\n";
	static const uint8_t fbuf[] = "log_level=0\nenable_cuda=1\n";
	static const uint8_t capbuf[] = "log_level=1\n";
	char path[64];
	char out[64];
	int32_t fd,plen,n,out_len;
	uint8_t io_buf[64];
	uint8_t io_cap_buf[12];
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
	if ( ds4_config_parse_mem(&cfg,buf2,(int32_t)(sizeof(buf2) - 1)) < 0 )
		return(-8);
	if ( cfg.log_level != 0 )
		return(-9);
	if ( cfg.enable_cuda != 1 )
		return(-10);
	if ( ds4_config_defaults(&cfg) < 0 )
		return(-11);
	if ( ds4_config_parse_mem(&cfg,buf3,(int32_t)(sizeof(buf3) - 1)) < 0 )
		return(-12);
	if ( cfg.log_level != 3 )
		return(-13);
	if ( cfg.enable_cuda != 0 )
		return(-14);
	if ( ds4_config_defaults(&cfg) < 0 )
		return(-15);
	if ( setenv("DS4_LOG_LEVEL","warning",1) != 0 )
		return(-16);
	if ( setenv("DS4_ENABLE_CUDA","yes",1) != 0 )
		return(-17);
	if ( ds4_config_parse_env(&cfg) < 0 )
		return(-18);
	if ( cfg.log_level != 1 )
		return(-19);
	if ( cfg.enable_cuda != 1 )
		return(-20);
	unsetenv("DS4_LOG_LEVEL");
	unsetenv("DS4_ENABLE_CUDA");
	for (n=0; n<(int32_t)sizeof(path); n++)
		path[n] = 0;
	plen = ds4_cstr_len_i32("/tmp/ds4_cfg_XXXXXX");
	if ( plen <= 0 )
		return(-21);
	for (n=0; n<plen && n<((int32_t)sizeof(path) - 1); n++)
		path[n] = "/tmp/ds4_cfg_XXXXXX"[n];
	path[n] = 0;
	fd = mkstemp(path);
	if ( fd < 0 )
		return(-22);
	if ( ds4_write_all(fd,fbuf,(int32_t)(sizeof(fbuf) - 1)) < 0 )
	{
		close(fd);
		unlink(path);
		return(-23);
	}
	close(fd);
	unsetenv("DS4_LOG_LEVEL");
	unsetenv("DS4_ENABLE_CUDA");
	if ( setenv("DS4_LOG_LEVEL","2",1) != 0 )
	{
		unlink(path);
		return(-24);
	}
	if ( ds4_config_load(&cfg,path,io_buf,(int32_t)sizeof(io_buf),0) < 0 )
	{
		unlink(path);
		return(-25);
	}
	if ( cfg.log_level != 2 )
	{
		unlink(path);
		return(-26);
	}
	if ( cfg.enable_cuda != 1 )
	{
		unlink(path);
		return(-27);
	}
	if ( ds4_config_format(&cfg,out,(int32_t)sizeof(out)) < 0 )
	{
		unlink(path);
		return(-28);
	}
	if ( out[0] == 0 )
	{
		unlink(path);
		return(-29);
	}
	unlink(path);
	unsetenv("DS4_LOG_LEVEL");
	unsetenv("DS4_ENABLE_CUDA");
	for (n=0; n<(int32_t)sizeof(path); n++)
		path[n] = 0;
	plen = ds4_cstr_len_i32("/tmp/ds4_cfg_empty_XXXXXX");
	if ( plen <= 0 )
		return(-30);
	for (n=0; n<plen && n<((int32_t)sizeof(path) - 1); n++)
		path[n] = "/tmp/ds4_cfg_empty_XXXXXX"[n];
	path[n] = 0;
	fd = mkstemp(path);
	if ( fd < 0 )
		return(-31);
	close(fd);
	if ( ds4_config_load(&cfg,path,io_buf,(int32_t)sizeof(io_buf),0) < 0 )
	{
		unlink(path);
		return(-32);
	}
	if ( cfg.log_level != 2 )
	{
		unlink(path);
		return(-33);
	}
	unlink(path);
	for (n=0; n<(int32_t)sizeof(path); n++)
		path[n] = 0;
	plen = ds4_cstr_len_i32("/tmp/ds4_cfg_cap_XXXXXX");
	if ( plen <= 0 )
		return(-34);
	for (n=0; n<plen && n<((int32_t)sizeof(path) - 1); n++)
		path[n] = "/tmp/ds4_cfg_cap_XXXXXX"[n];
	path[n] = 0;
	fd = mkstemp(path);
	if ( fd < 0 )
		return(-35);
	if ( ds4_write_all(fd,capbuf,(int32_t)(sizeof(capbuf) - 1)) < 0 )
	{
		close(fd);
		unlink(path);
		return(-36);
	}
	close(fd);
	if ( ds4_config_defaults(&cfg) < 0 )
	{
		unlink(path);
		return(-37);
	}
	out_len = 0;
	if ( ds4_config_parse_file(&cfg,path,io_cap_buf,(int32_t)sizeof(io_cap_buf),&out_len) < 0 )
	{
		unlink(path);
		return(-38);
	}
	if ( out_len != (int32_t)sizeof(io_cap_buf) )
	{
		unlink(path);
		return(-39);
	}
	if ( cfg.log_level != 1 )
	{
		unlink(path);
		return(-40);
	}
	unlink(path);
	unsetenv("DS4_CONFIG_PATH");
	unsetenv("DS4_LOG_LEVEL");
	unsetenv("DS4_ENABLE_CUDA");
	for (n=0; n<(int32_t)sizeof(path); n++)
		path[n] = 0;
	plen = ds4_cstr_len_i32("/tmp/ds4_cfg_envpath_XXXXXX");
	if ( plen <= 0 )
		return(-41);
	for (n=0; n<plen && n<((int32_t)sizeof(path) - 1); n++)
		path[n] = "/tmp/ds4_cfg_envpath_XXXXXX"[n];
	path[n] = 0;
	fd = mkstemp(path);
	if ( fd < 0 )
		return(-42);
	if ( ds4_write_all(fd,fbuf,(int32_t)(sizeof(fbuf) - 1)) < 0 )
	{
		close(fd);
		unlink(path);
		return(-43);
	}
	close(fd);
	if ( setenv("DS4_CONFIG_PATH",path,1) != 0 )
	{
		unlink(path);
		return(-44);
	}
	if ( setenv("DS4_LOG_LEVEL","3",1) != 0 )
	{
		unlink(path);
		return(-45);
	}
	if ( ds4_config_load_auto(&cfg,0,io_buf,(int32_t)sizeof(io_buf),0) < 0 )
	{
		unlink(path);
		return(-46);
	}
	if ( cfg.log_level != 3 )
	{
		unlink(path);
		return(-47);
	}
	if ( cfg.enable_cuda != 1 )
	{
		unlink(path);
		return(-48);
	}
	unlink(path);
	unsetenv("DS4_CONFIG_PATH");
	unsetenv("DS4_LOG_LEVEL");
	return(0);
}
