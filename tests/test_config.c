#include "ds4/config.h"
#include "ds4/str.h"

#include <stdint.h>
#include <stdlib.h>
#include <string.h>
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
	ds4_config_diag_t diag;
	static const uint8_t buf0[] = "log_level=3\nenable_cuda=false\n";
	static const uint8_t buf1[] = "enable_cuda=ON\n";
	static const uint8_t buf2[] = "log_level=0 # comment\n# full line comment\n enable_cuda = yes\t# trailing\n";
	static const uint8_t buf3[] = "log_level=debug\nenable_cuda=0\n";
	static const uint8_t buf_cuda_dev0[] = "cuda_device=0\n";
	static const uint8_t buf_cuda_dev_bad[] = "cuda_device=-2\n";
	static const uint8_t buf_mem0[] = "arena_size=256\nlog_ring_entries=8\n";
	static const uint8_t buf_mem1[] = "arena_size=2k\nlog_ring_entries=3k\n";
	static const uint8_t buf_multispark0[] = "rank=1\nworld_size=3\nexpert_owner_table_path=/tmp/owner.json\nexpert_manifest_path=/tmp/rank-001.json\n";
	static const uint8_t buf_mem_over2[] = "arena_size=3g\n";
	static const uint8_t buf_unknown0[] = "log_level=2\nunknown_key=1\nenable_cuda=0\n";
	static const uint8_t buf_over0[] = "log_level=2147483648\nenable_cuda=0\n";
	static const uint8_t buf_over1[] = "log_level=-2147483649\nenable_cuda=0\n";
	static const uint8_t buf_i32min[] = "log_level=-2147483648\nenable_cuda=0\n";
	static const uint8_t fbuf[] = "log_level=0\nenable_cuda=1\n";
	static const uint8_t capbuf[] = "log_level=1\n";
	static const uint8_t env_cfg0[] = "log_level=debug\n";
	static const uint8_t env_cfg_unknown0[] = "unknown_key=1\n";
	char path[64];
	char env_path[96];
	char out[1024];
	const char *k0,*h0,*env_name,*env_help;
	const char *ev;
	int32_t fd,fdin,fd_save,plen,n,out_len,env_len;
	uint8_t io_buf[64];
	uint8_t io_cap_buf[12];
	int32_t unknown,key_count,env_count,env_i,found_log_level,found_cfg_path,found_world_size,found_manifest_path;
	if ( ds4_config_defaults(&cfg) < 0 )
		return(-1);
	if ( cfg.rank != DS4_RANK_NONE )
		return(-18100);
	if ( cfg.world_size != 1 )
		return(-18101);
	if ( cfg.expert_owner_table_path[0] != 0 )
		return(-18102);
	if ( cfg.expert_manifest_path[0] != 0 )
		return(-18103);
	key_count = -1;
	if ( ds4_config_known_key_count(&key_count) < 0 )
		return(-1812);
	if ( key_count < 10 )
		return(-1813);
	if ( ds4_config_known_key(-1) != 0 )
		return(-1814);
	if ( ds4_config_known_key(key_count) != 0 )
		return(-1815);
	k0 = ds4_config_known_key(0);
	if ( k0 == 0 || strcmp(k0,"log_level") != 0 )
		return(-1816);
	if ( ds4_config_known_key_help(-1) != 0 )
		return(-1817);
	if ( ds4_config_known_key_help(key_count) != 0 )
		return(-1818);
	h0 = ds4_config_known_key_help(0);
	if ( h0 == 0 )
		return(-1819);
	if ( ds4_cstr_len_i32(h0) <= 0 )
		return(-1820);
	env_count = -1;
	if ( ds4_config_env_var_count(&env_count) < 0 )
		return(-18210);
	if ( env_count < 12 )
		return(-18211);
	if ( ds4_config_env_var(-1) != 0 )
		return(-18212);
	if ( ds4_config_env_var(env_count) != 0 )
		return(-18213);
	if ( ds4_config_env_var_help(-1) != 0 )
		return(-18214);
	if ( ds4_config_env_var_help(env_count) != 0 )
		return(-18215);
	found_log_level = 0;
	found_cfg_path = 0;
	found_world_size = 0;
	found_manifest_path = 0;
	for (env_i=0; env_i<env_count; env_i++)
	{
		env_name = ds4_config_env_var(env_i);
		if ( env_name == 0 )
			return(-18216);
		env_help = ds4_config_env_var_help(env_i);
		if ( env_help == 0 )
			return(-18217);
		if ( strcmp(env_name,"DS4_LOG_LEVEL") == 0 )
			found_log_level = 1;
		if ( strcmp(env_name,"DS4_CONFIG_PATH") == 0 )
			found_cfg_path = 1;
		if ( strcmp(env_name,"DS4_WORLD_SIZE") == 0 )
			found_world_size = 1;
		if ( strcmp(env_name,"DS4_EXPERT_MANIFEST_PATH") == 0 )
			found_manifest_path = 1;
	}
	if ( found_log_level == 0 )
		return(-18218);
	if ( found_cfg_path == 0 )
		return(-18219);
	if ( found_world_size == 0 )
		return(-18220);
	if ( found_manifest_path == 0 )
		return(-18221);
	ev = ds4_config_env_err_var(-3);
	if ( ev == 0 || strcmp(ev,"DS4_LOG_LEVEL") != 0 )
		return(-1821);
	ev = ds4_config_env_err_var(-7);
	if ( ev == 0 || strcmp(ev,"DS4_ENABLE_CUDA") != 0 )
		return(-1822);
	ev = ds4_config_env_err_var(-12);
	if ( ev == 0 || strcmp(ev,"DS4_CUDA_DEVICE") != 0 )
		return(-1823);
	ev = ds4_config_env_err_var(-15);
	if ( ev == 0 || strcmp(ev,"DS4_ARENA_SIZE") != 0 )
		return(-1824);
	ev = ds4_config_env_err_var(-21);
	if ( ev == 0 || strcmp(ev,"DS4_CUDA_ARENA_SIZE") != 0 )
		return(-1825);
	ev = ds4_config_env_err_var(-18);
	if ( ev == 0 || strcmp(ev,"DS4_LOG_RING_ENTRIES") != 0 )
		return(-1826);
	ev = ds4_config_env_err_var(-24);
	if ( ev == 0 || strcmp(ev,"DS4_WORLD_SIZE") != 0 )
		return(-1828);
	ev = ds4_config_env_err_var(-27);
	if ( ev == 0 || strcmp(ev,"DS4_RANK") != 0 )
		return(-1829);
	ev = ds4_config_env_err_var(-29);
	if ( ev == 0 || strcmp(ev,"DS4_EXPERT_OWNER_TABLE_PATH") != 0 )
		return(-1830);
	ev = ds4_config_env_err_var(-31);
	if ( ev == 0 || strcmp(ev,"DS4_EXPERT_MANIFEST_PATH") != 0 )
		return(-1831);
	if ( ds4_config_env_err_var(0) != 0 )
		return(-1827);
	if ( ds4_config_validate(&cfg) < 0 )
		return(-1800);
	cfg.log_level = -1;
	if ( ds4_config_validate(&cfg) >= 0 )
		return(-1801);
	cfg.log_level = 2;
	cfg.enable_cuda = 2;
	if ( ds4_config_validate(&cfg) >= 0 )
		return(-1802);
	cfg.enable_cuda = 0;
	cfg.cuda_device = -2;
	if ( ds4_config_validate(&cfg) >= 0 )
		return(-1803);
	cfg.cuda_device = DS4_CUDA_DEVICE_AUTO;
	cfg.arena_size = -1;
	if ( ds4_config_validate(&cfg) >= 0 )
		return(-1804);
	cfg.arena_size = 0;
	cfg.log_ring_entries = -1;
	if ( ds4_config_validate(&cfg) >= 0 )
		return(-1805);
	cfg.log_ring_entries = 0;
	cfg.cuda_arena_size = -1;
	if ( ds4_config_validate(&cfg) >= 0 )
		return(-1807);
	cfg.cuda_arena_size = 1;
	if ( ds4_config_validate(&cfg) >= 0 )
		return(-1808);
	cfg.enable_cuda = 1;
	if ( ds4_config_validate(&cfg) < 0 )
		return(-1809);
	cfg.enable_cuda = 0;
	cfg.cuda_arena_size = 0;
	cfg.rank = -2;
	if ( ds4_config_validate(&cfg) >= 0 )
		return(-18104);
	cfg.rank = 3;
	cfg.world_size = 3;
	if ( ds4_config_validate(&cfg) >= 0 )
		return(-18105);
	cfg.rank = 2;
	cfg.world_size = 3;
	if ( ds4_config_validate(&cfg) < 0 )
		return(-18106);
	cfg.rank = DS4_RANK_NONE;
	cfg.world_size = 0;
	if ( ds4_config_validate(&cfg) >= 0 )
		return(-18107);
	cfg.world_size = 1;
	if ( ds4_config_validate(0) >= 0 )
		return(-1806);
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
	if ( ds4_config_parse_kv_cstr(&cfg,"arena_size","64k") != 0 )
		return(-170);
	if ( cfg.arena_size != 65536 )
		return(-171);
	if ( ds4_config_parse_kv_cstr(&cfg,"arena_size","64KiB") != 0 )
		return(-1710);
	if ( cfg.arena_size != 65536 )
		return(-1711);
	if ( ds4_config_parse_kv_cstr(&cfg,"arena_size","1MiB") != 0 )
		return(-1712);
	if ( cfg.arena_size != 1048576 )
		return(-1713);
	if ( ds4_config_parse_kv_cstr(&cfg,"arena_size","1GiB") != 0 )
		return(-1714);
	if ( cfg.arena_size != 1073741824 )
		return(-1715);
	if ( ds4_config_parse_kv_cstr(&cfg,"cuda_arena_size","256") != 0 )
		return(-1810);
	if ( cfg.cuda_arena_size != 256 )
		return(-1811);
	if ( ds4_config_parse_kv_cstr(&cfg,"cuda_arena_size","1MiB") != 0 )
		return(-1812);
	if ( cfg.cuda_arena_size != 1048576 )
		return(-1813);
	if ( ds4_config_parse_kv_cstr(&cfg,"log_ring_entries","9") != 0 )
		return(-142);
	if ( cfg.log_ring_entries != 9 )
		return(-143);
	if ( ds4_config_parse_kv_cstr(&cfg,"log_ring_entries","2k") != 0 )
		return(-172);
	if ( cfg.log_ring_entries != 2048 )
		return(-173);
	if ( ds4_config_parse_kv_cstr(&cfg,"log_ring_entries","2KiB") != 0 )
		return(-1730);
	if ( cfg.log_ring_entries != 2048 )
		return(-1731);
	if ( ds4_config_parse_kv_cstr(&cfg,"world_size","3") != 0 )
		return(-1832);
	if ( cfg.world_size != 3 )
		return(-1833);
	if ( ds4_config_parse_kv_cstr(&cfg,"rank","1") != 0 )
		return(-1834);
	if ( cfg.rank != 1 )
		return(-1835);
	if ( ds4_config_parse_kv_cstr(&cfg,"expert_owner_table_path","/tmp/owner.json") != 0 )
		return(-1836);
	if ( strcmp(cfg.expert_owner_table_path,"/tmp/owner.json") != 0 )
		return(-1837);
	if ( ds4_config_parse_kv_cstr(&cfg,"expert_manifest_path","/tmp/rank-001.json") != 0 )
		return(-1838);
	if ( strcmp(cfg.expert_manifest_path,"/tmp/rank-001.json") != 0 )
		return(-1839);
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
		return(-174);
	if ( ds4_config_parse_mem(&cfg,buf_mem1,(int32_t)(sizeof(buf_mem1) - 1)) < 0 )
		return(-175);
	if ( cfg.arena_size != 2048 )
		return(-176);
	if ( cfg.log_ring_entries != 3072 )
		return(-177);
	if ( ds4_config_defaults(&cfg) < 0 )
		return(-178);
	if ( ds4_config_parse_mem(&cfg,buf_multispark0,(int32_t)(sizeof(buf_multispark0) - 1)) < 0 )
		return(-1840);
	if ( cfg.rank != 1 || cfg.world_size != 3 )
		return(-1841);
	if ( strcmp(cfg.expert_owner_table_path,"/tmp/owner.json") != 0 )
		return(-1842);
	if ( strcmp(cfg.expert_manifest_path,"/tmp/rank-001.json") != 0 )
		return(-1843);
	if ( ds4_config_defaults(&cfg) < 0 )
		return(-1844);
	if ( ds4_config_parse_mem(&cfg,buf_mem_over2,(int32_t)(sizeof(buf_mem_over2) - 1)) >= 0 )
		return(-179);
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
		return(-152);
	if ( ds4_config_defaults(&cfg) < 0 )
		return(-201);
	unknown = -1;
	if ( ds4_config_parse_mem_ex_diag(&cfg,buf_unknown0,(int32_t)(sizeof(buf_unknown0) - 1),DS4_CONFIG_PARSE_STRICT_UNKNOWN,&unknown,&diag) >= 0 )
		return(-202);
	if ( unknown != 1 )
		return(-203);
	if ( diag.stage != DS4_CONFIG_DIAG_STAGE_MEM )
		return(-204);
	if ( diag.line != 2 )
		return(-205);
	if ( diag.err != -11 )
		return(-206);
	if ( diag.unknown != 1 )
		return(-207);
	if ( strcmp(ds4_config_diag_stage_name(diag.stage),"mem") != 0 )
		return(-208);
	n = ds4_config_diag_format(&diag,out,(int32_t)sizeof(out));
	if ( n < 0 )
		return(-209);
	if ( strcmp(out,"stage=mem line=2 err=-11 unknown=1") != 0 )
		return(-210);
	unsetenv("DS4_CONFIG_PATH");
	unsetenv("DS4_CONFIG");
	if ( setenv("DS4_CONFIG",(const char *)env_cfg_unknown0,1) != 0 )
		return(-2150);
	unknown = -1;
	ds4_config_diag_init(&diag);
	if ( ds4_config_load_auto_ex_diag(&cfg,0,io_buf,(int32_t)sizeof(io_buf),0,DS4_CONFIG_PARSE_STRICT_UNKNOWN,&unknown,&diag) >= 0 )
	{
		unsetenv("DS4_CONFIG");
		return(-2151);
	}
	if ( unknown != 1 )
	{
		unsetenv("DS4_CONFIG");
		return(-2152);
	}
	if ( diag.stage != DS4_CONFIG_DIAG_STAGE_ENV_CONFIG )
	{
		unsetenv("DS4_CONFIG");
		return(-2153);
	}
	if ( diag.line != 1 )
	{
		unsetenv("DS4_CONFIG");
		return(-2154);
	}
	if ( diag.err != -11 )
	{
		unsetenv("DS4_CONFIG");
		return(-2155);
	}
	if ( diag.unknown != 1 )
	{
		unsetenv("DS4_CONFIG");
		return(-2156);
	}
	if ( strcmp(ds4_config_diag_stage_name(diag.stage),"env_config") != 0 )
	{
		unsetenv("DS4_CONFIG");
		return(-2157);
	}
	n = ds4_config_diag_format(&diag,out,(int32_t)sizeof(out));
	if ( n < 0 )
	{
		unsetenv("DS4_CONFIG");
		return(-2158);
	}
	if ( strcmp(out,"stage=env_config line=1 err=-11 unknown=1") != 0 )
	{
		unsetenv("DS4_CONFIG");
		return(-2159);
	}
	unsetenv("DS4_CONFIG");
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
	if ( setenv("DS4_ARENA_SIZE","512k",1) != 0 )
		return(-148);
	if ( setenv("DS4_CUDA_ARENA_SIZE","256k",1) != 0 )
		return(-1520);
	if ( setenv("DS4_LOG_RING_ENTRIES","4k",1) != 0 )
		return(-149);
	if ( setenv("DS4_WORLD_SIZE","3",1) != 0 )
		return(-1845);
	if ( setenv("DS4_RANK","2",1) != 0 )
		return(-1846);
	if ( setenv("DS4_EXPERT_OWNER_TABLE_PATH","/tmp/env-owner.json",1) != 0 )
		return(-1847);
	if ( setenv("DS4_EXPERT_MANIFEST_PATH","/tmp/env-rank-002.json",1) != 0 )
		return(-1848);
	if ( ds4_config_parse_env(&cfg) < 0 )
		return(-18);
	if ( cfg.log_level != 1 )
		return(-19);
	if ( cfg.enable_cuda != 1 )
		return(-20);
	if ( cfg.cuda_device != 3 )
		return(-116);
	if ( cfg.arena_size != 524288 )
		return(-150);
	if ( cfg.cuda_arena_size != 262144 )
		return(-1521);
	if ( cfg.log_ring_entries != 4096 )
		return(-151);
	if ( cfg.world_size != 3 )
		return(-1849);
	if ( cfg.rank != 2 )
		return(-1850);
	if ( strcmp(cfg.expert_owner_table_path,"/tmp/env-owner.json") != 0 )
		return(-1851);
	if ( strcmp(cfg.expert_manifest_path,"/tmp/env-rank-002.json") != 0 )
		return(-1852);
	unsetenv("DS4_LOG_LEVEL");
	unsetenv("DS4_ENABLE_CUDA");
	unsetenv("DS4_CUDA_DEVICE");
	unsetenv("DS4_ARENA_SIZE");
	unsetenv("DS4_CUDA_ARENA_SIZE");
	unsetenv("DS4_LOG_RING_ENTRIES");
	unsetenv("DS4_WORLD_SIZE");
	unsetenv("DS4_RANK");
	unsetenv("DS4_EXPERT_OWNER_TABLE_PATH");
	unsetenv("DS4_EXPERT_MANIFEST_PATH");
	if ( ds4_config_defaults(&cfg) < 0 )
		return(-153);
	if ( setenv("DS4_LOG_LEVEL","",1) != 0 )
		return(-154);
	if ( setenv("DS4_ENABLE_CUDA","",1) != 0 )
		return(-155);
	if ( setenv("DS4_CUDA_DEVICE","",1) != 0 )
		return(-156);
	if ( setenv("DS4_ARENA_SIZE","",1) != 0 )
		return(-157);
	if ( setenv("DS4_CUDA_ARENA_SIZE","",1) != 0 )
		return(-1522);
	if ( setenv("DS4_LOG_RING_ENTRIES","",1) != 0 )
		return(-158);
	if ( ds4_config_parse_env(&cfg) < 0 )
		return(-159);
	if ( cfg.log_level != 2 )
		return(-160);
	if ( cfg.enable_cuda != 0 )
		return(-161);
	if ( cfg.cuda_device != DS4_CUDA_DEVICE_AUTO )
		return(-162);
	if ( cfg.arena_size != 0 )
		return(-163);
	if ( cfg.cuda_arena_size != 0 )
		return(-1523);
	if ( cfg.log_ring_entries != 0 )
		return(-164);
	unsetenv("DS4_LOG_LEVEL");
	unsetenv("DS4_ENABLE_CUDA");
	unsetenv("DS4_CUDA_DEVICE");
	unsetenv("DS4_ARENA_SIZE");
	unsetenv("DS4_CUDA_ARENA_SIZE");
	unsetenv("DS4_LOG_RING_ENTRIES");
	if ( ds4_config_defaults(&cfg) < 0 )
		return(-165);
	if ( setenv("DS4_LOG_LEVEL"," \t ",1) != 0 )
		return(-166);
	if ( setenv("DS4_ENABLE_CUDA"," \t ",1) != 0 )
		return(-167);
	if ( setenv("DS4_CUDA_DEVICE"," \t ",1) != 0 )
		return(-168);
	if ( setenv("DS4_ARENA_SIZE"," \t ",1) != 0 )
		return(-169);
	if ( setenv("DS4_CUDA_ARENA_SIZE"," \t ",1) != 0 )
		return(-1524);
	if ( setenv("DS4_LOG_RING_ENTRIES"," \t ",1) != 0 )
		return(-170);
	if ( ds4_config_parse_env(&cfg) < 0 )
		return(-171);
	if ( cfg.log_level != 2 )
		return(-172);
	if ( cfg.enable_cuda != 0 )
		return(-173);
	if ( cfg.cuda_device != DS4_CUDA_DEVICE_AUTO )
		return(-174);
	if ( cfg.arena_size != 0 )
		return(-175);
	if ( cfg.cuda_arena_size != 0 )
		return(-1525);
	if ( cfg.log_ring_entries != 0 )
		return(-176);
	unsetenv("DS4_LOG_LEVEL");
	unsetenv("DS4_ENABLE_CUDA");
	unsetenv("DS4_CUDA_DEVICE");
	unsetenv("DS4_ARENA_SIZE");
	unsetenv("DS4_CUDA_ARENA_SIZE");
	unsetenv("DS4_LOG_RING_ENTRIES");
	if ( ds4_config_defaults(&cfg) < 0 )
		return(-177);
	if ( setenv("DS4_LOG_LEVEL","  warning  ",1) != 0 )
		return(-178);
	if ( setenv("DS4_ENABLE_CUDA","  yes  ",1) != 0 )
		return(-179);
	if ( setenv("DS4_CUDA_DEVICE"," 3 ",1) != 0 )
		return(-180);
	if ( setenv("DS4_ARENA_SIZE"," 512 ",1) != 0 )
		return(-181);
	if ( setenv("DS4_CUDA_ARENA_SIZE"," 256 ",1) != 0 )
		return(-1526);
	if ( setenv("DS4_LOG_RING_ENTRIES"," 7 ",1) != 0 )
		return(-182);
	if ( ds4_config_parse_env(&cfg) < 0 )
		return(-183);
	if ( cfg.log_level != 1 )
		return(-184);
	if ( cfg.enable_cuda != 1 )
		return(-185);
	if ( cfg.cuda_device != 3 )
		return(-186);
	if ( cfg.arena_size != 512 )
		return(-187);
	if ( cfg.cuda_arena_size != 256 )
		return(-1527);
	if ( cfg.log_ring_entries != 7 )
		return(-188);
	unsetenv("DS4_LOG_LEVEL");
	unsetenv("DS4_ENABLE_CUDA");
	unsetenv("DS4_CUDA_DEVICE");
	unsetenv("DS4_ARENA_SIZE");
	unsetenv("DS4_CUDA_ARENA_SIZE");
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
	if ( ds4_span_eq(out,n,"log_level=info\nenable_cuda=1\ncuda_device=-1\narena_size=0\ncuda_arena_size=0\nlog_ring_entries=0\nrank=-1\nworld_size=1\nexpert_owner_table_path=\nexpert_manifest_path=\n") == 0 )
	{
		unlink(path);
		return(-49);
	}
	unsetenv("DS4_LOG_LEVEL");
	if ( setenv("DS4_CONFIG",(const char *)env_cfg0,1) != 0 )
	{
		unlink(path);
		return(-189);
	}
	if ( ds4_config_load(&cfg,path,io_buf,(int32_t)sizeof(io_buf),0) < 0 )
	{
		unsetenv("DS4_CONFIG");
		unlink(path);
		return(-190);
	}
	if ( cfg.log_level != 3 )
	{
		unsetenv("DS4_CONFIG");
		unlink(path);
		return(-191);
	}
	if ( setenv("DS4_LOG_LEVEL","1",1) != 0 )
	{
		unsetenv("DS4_CONFIG");
		unlink(path);
		return(-192);
	}
	if ( ds4_config_load(&cfg,path,io_buf,(int32_t)sizeof(io_buf),0) < 0 )
	{
		unsetenv("DS4_CONFIG");
		unsetenv("DS4_LOG_LEVEL");
		unlink(path);
		return(-193);
	}
	if ( cfg.log_level != 1 )
	{
		unsetenv("DS4_CONFIG");
		unsetenv("DS4_LOG_LEVEL");
		unlink(path);
		return(-194);
	}
	unsetenv("DS4_CONFIG");
	unsetenv("DS4_LOG_LEVEL");
	unlink(path);
	for (n=0; n<(int32_t)sizeof(path); n++)
		path[n] = 0;
	plen = ds4_cstr_len_i32("/tmp/ds4_cfg_unknown_XXXXXX");
	if ( plen <= 0 )
		return(-160);
	for (n=0; n<plen && n<((int32_t)sizeof(path) - 1); n++)
		path[n] = "/tmp/ds4_cfg_unknown_XXXXXX"[n];
	path[n] = 0;
	fd = mkstemp(path);
	if ( fd < 0 )
		return(-161);
	if ( ds4_write_all(fd,buf_unknown0,(int32_t)(sizeof(buf_unknown0) - 1)) < 0 )
	{
		close(fd);
		unlink(path);
		return(-162);
	}
	close(fd);
	if ( ds4_config_defaults(&cfg) < 0 )
	{
		unlink(path);
		return(-163);
	}
	out_len = 0;
	unknown = -1;
	ds4_config_diag_init(&diag);
	if ( ds4_config_parse_file_ex_diag(&cfg,path,io_buf,(int32_t)sizeof(io_buf),&out_len,DS4_CONFIG_PARSE_STRICT_UNKNOWN,&unknown,&diag) >= 0 )
	{
		unlink(path);
		return(-164);
	}
	if ( unknown != 1 )
	{
		unlink(path);
		return(-165);
	}
	if ( diag.stage != DS4_CONFIG_DIAG_STAGE_FILE )
	{
		unlink(path);
		return(-208);
	}
	if ( diag.line != 2 )
	{
		unlink(path);
		return(-209);
	}
	if ( diag.err != -11 )
	{
		unlink(path);
		return(-210);
	}
	if ( diag.unknown != 1 )
	{
		unlink(path);
		return(-211);
	}
	unlink(path);
	unsetenv("DS4_CONFIG");
	if ( setenv("DS4_CONFIG",(const char *)env_cfg_unknown0,1) != 0 )
		return(-212);
	unknown = -1;
	if ( ds4_config_load_ex(&cfg,0,io_buf,(int32_t)sizeof(io_buf),0,DS4_CONFIG_PARSE_STRICT_UNKNOWN,&unknown) >= 0 )
	{
		unsetenv("DS4_CONFIG");
		return(-213);
	}
	if ( unknown != 1 )
	{
		unsetenv("DS4_CONFIG");
		return(-214);
	}
	unsetenv("DS4_CONFIG");
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
	env_len = ds4_cstr_len_i32(path);
	if ( env_len <= 0 )
	{
		unlink(path);
		return(-189);
	}
	if ( (env_len + 5) >= (int32_t)sizeof(env_path) )
	{
		unlink(path);
		return(-190);
	}
	env_path[0] = ' ';
	env_path[1] = ' ';
	for (n=0; n<env_len; n++)
		env_path[2 + n] = path[n];
	env_path[2 + env_len] = ' ';
	env_path[3 + env_len] = '\t';
	env_path[4 + env_len] = 0;
	if ( setenv("DS4_CONFIG_PATH",env_path,1) != 0 )
	{
		unlink(path);
		return(-191);
	}
	if ( ds4_config_load_auto(&cfg,0,io_buf,(int32_t)sizeof(io_buf),0) < 0 )
	{
		unlink(path);
		return(-192);
	}
	if ( cfg.log_level != 3 )
	{
		unlink(path);
		return(-193);
	}
	if ( cfg.enable_cuda != 1 )
	{
		unlink(path);
		return(-194);
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
