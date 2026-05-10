#include "ds4/config.h"
#include "ds4/str.h"

#include <stdint.h>
#include <stdlib.h>
#include <fcntl.h>
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
	static const uint8_t buf_cuda_dev0[] = "cuda_device=0\n";
	static const uint8_t buf_cuda_dev_bad[] = "cuda_device=-2\n";
	static const uint8_t buf_mem0[] = "arena_size=256\nlog_ring_entries=8\n";
	static const uint8_t buf_unknown0[] = "log_level=2\nunknown_key=1\nenable_cuda=0\n";
	static const uint8_t buf_over0[] = "log_level=2147483648\nenable_cuda=0\n";
	static const uint8_t buf_over1[] = "log_level=-2147483649\nenable_cuda=0\n";
	static const uint8_t buf_i32min[] = "log_level=-2147483648\nenable_cuda=0\n";
	static const uint8_t fbuf[] = "log_level=0\nenable_cuda=1\n";
	static const uint8_t capbuf[] = "log_level=1\n";
	char path[64];
	char out[128];
	int32_t fd,fdin,fd_save,plen,n,out_len;
	uint8_t io_buf[64];
	uint8_t io_cap_buf[12];
	int32_t unknown;
	if ( ds4_config_defaults(&cfg) < 0 )
		return(-1);
	if ( ds4_config_parse_kv_cstr(&cfg,"log_level","debug") != 0 )
		return(-60);
	if ( cfg.log_level != 3 )
		return(-61);
	if ( ds4_config_parse_kv_cstr(&cfg,"enable_cuda","true") != 0 )
		return(-62);
	if ( cfg.enable_cuda != 1 )
		return(-63);
	if ( ds4_config_parse_kv_cstr(&cfg,"arena_size","123") != 0 )
		return(-140);
	if ( cfg.arena_size != 123 )
		return(-141);
	if ( ds4_config_parse_kv_cstr(&cfg,"log_ring_entries","9") != 0 )
		return(-142);
	if ( cfg.log_ring_entries != 9 )
		return(-143);
	if ( ds4_config_parse_kv_cstr(&cfg,0,"1") >= 0 )
		return(-64);
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
		return(-110);
	if ( ds4_config_parse_mem(&cfg,buf_cuda_dev0,(int32_t)(sizeof(buf_cuda_dev0) - 1)) < 0 )
		return(-111);
	if ( cfg.cuda_device != 0 )
		return(-112);
	if ( ds4_config_defaults(&cfg) < 0 )
		return(-113);
	if ( ds4_config_parse_mem(&cfg,buf_cuda_dev_bad,(int32_t)(sizeof(buf_cuda_dev_bad) - 1)) >= 0 )
		return(-114);
	if ( ds4_config_defaults(&cfg) < 0 )
		return(-144);
	if ( ds4_config_parse_mem(&cfg,buf_mem0,(int32_t)(sizeof(buf_mem0) - 1)) < 0 )
		return(-145);
	if ( cfg.arena_size != 256 )
		return(-146);
	if ( cfg.log_ring_entries != 8 )
		return(-147);
	if ( ds4_config_defaults(&cfg) < 0 )
		return(-120);
	unknown = -1;
	if ( ds4_config_parse_mem_ex(&cfg,buf_unknown0,(int32_t)(sizeof(buf_unknown0) - 1),0,&unknown) < 0 )
		return(-121);
	if ( unknown != 1 )
		return(-122);
	if ( ds4_config_defaults(&cfg) < 0 )
		return(-123);
	unknown = -1;
	if ( ds4_config_parse_mem_ex(&cfg,buf_unknown0,(int32_t)(sizeof(buf_unknown0) - 1),DS4_CONFIG_PARSE_STRICT_UNKNOWN,&unknown) >= 0 )
		return(-124);
	if ( unknown != 1 )
		return(-1241);
	if ( ds4_config_defaults(&cfg) < 0 )
		return(-101);
	if ( ds4_config_parse_mem(&cfg,buf_over0,(int32_t)(sizeof(buf_over0) - 1)) >= 0 )
		return(-102);
	if ( ds4_config_defaults(&cfg) < 0 )
		return(-103);
	if ( ds4_config_parse_mem(&cfg,buf_over1,(int32_t)(sizeof(buf_over1) - 1)) >= 0 )
		return(-104);
	if ( ds4_config_defaults(&cfg) < 0 )
		return(-105);
	if ( ds4_config_parse_mem(&cfg,buf_i32min,(int32_t)(sizeof(buf_i32min) - 1)) >= 0 )
		return(-106);
	if ( ds4_config_defaults(&cfg) < 0 )
		return(-15);
	if ( setenv("DS4_LOG_LEVEL","warning",1) != 0 )
		return(-16);
	if ( setenv("DS4_ENABLE_CUDA","yes",1) != 0 )
		return(-17);
	if ( setenv("DS4_CUDA_DEVICE","3",1) != 0 )
		return(-115);
	if ( setenv("DS4_ARENA_SIZE","512",1) != 0 )
		return(-148);
	if ( setenv("DS4_LOG_RING_ENTRIES","7",1) != 0 )
		return(-149);
	if ( ds4_config_parse_env(&cfg) < 0 )
		return(-18);
	if ( cfg.log_level != 1 )
		return(-19);
	if ( cfg.enable_cuda != 1 )
		return(-20);
	if ( cfg.cuda_device != 3 )
		return(-116);
	if ( cfg.arena_size != 512 )
		return(-150);
	if ( cfg.log_ring_entries != 7 )
		return(-151);
	unsetenv("DS4_LOG_LEVEL");
	unsetenv("DS4_ENABLE_CUDA");
	unsetenv("DS4_CUDA_DEVICE");
	unsetenv("DS4_ARENA_SIZE");
	unsetenv("DS4_LOG_RING_ENTRIES");
	if ( ds4_config_defaults(&cfg) < 0 )
		return(-107);
	if ( setenv("DS4_ENABLE_CUDA","2147483648",1) != 0 )
		return(-108);
	if ( ds4_config_parse_env(&cfg) >= 0 )
		return(-109);
	unsetenv("DS4_ENABLE_CUDA");
	if ( ds4_config_defaults(&cfg) < 0 )
		return(-117);
	if ( setenv("DS4_CUDA_DEVICE","-2",1) != 0 )
		return(-118);
	if ( ds4_config_parse_env(&cfg) >= 0 )
		return(-119);
	unsetenv("DS4_CUDA_DEVICE");
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
	fdin = (int32_t)open(path,O_RDONLY);
	if ( fdin < 0 )
	{
		unlink(path);
		return(-130);
	}
	fd_save = (int32_t)dup(0);
	if ( fd_save < 0 )
	{
		close(fdin);
		unlink(path);
		return(-131);
	}
	if ( dup2(fdin,0) < 0 )
	{
		close(fdin);
		close(fd_save);
		unlink(path);
		return(-132);
	}
	close(fdin);
	if ( ds4_config_defaults(&cfg) < 0 )
	{
		dup2(fd_save,0);
		close(fd_save);
		unlink(path);
		return(-133);
	}
	out_len = -1;
	if ( ds4_config_parse_file(&cfg,"-",io_buf,(int32_t)sizeof(io_buf),&out_len) < 0 )
	{
		dup2(fd_save,0);
		close(fd_save);
		unlink(path);
		return(-134);
	}
	if ( dup2(fd_save,0) < 0 )
	{
		close(fd_save);
		unlink(path);
		return(-135);
	}
	close(fd_save);
	if ( out_len <= 0 )
	{
		unlink(path);
		return(-136);
	}
	if ( cfg.log_level != 0 )
	{
		unlink(path);
		return(-137);
	}
	if ( cfg.enable_cuda != 1 )
	{
		unlink(path);
		return(-138);
	}
	if ( cfg.cuda_device != DS4_CUDA_DEVICE_AUTO )
	{
		unlink(path);
		return(-139);
	}
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
	n = ds4_cstr_len_i32(out);
	if ( ds4_span_eq(out,n,"log_level=info\nenable_cuda=1\ncuda_device=-1\narena_size=0\nlog_ring_entries=0\n") == 0 )
	{
		unlink(path);
		return(-49);
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
	unknown = -1;
	if ( ds4_config_parse_file_ex(&cfg,path,io_cap_buf,(int32_t)sizeof(io_cap_buf),&out_len,0,&unknown) < 0 )
	{
		unlink(path);
		return(-125);
	}
	if ( unknown != 0 )
	{
		unlink(path);
		return(-126);
	}
	if ( ds4_config_defaults(&cfg) < 0 )
	{
		unlink(path);
		return(-127);
	}
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
	unknown = -1;
	if ( ds4_config_load_auto_ex(&cfg,0,io_buf,(int32_t)sizeof(io_buf),0,0,&unknown) < 0 )
	{
		unlink(path);
		return(-128);
	}
	if ( unknown != 0 )
	{
		unlink(path);
		return(-129);
	}
	unlink(path);
	unsetenv("DS4_CONFIG_PATH");
	unsetenv("DS4_LOG_LEVEL");
	return(0);
}
