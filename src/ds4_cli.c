#include "ds4/ds4.h"

#include <inttypes.h>
#include <stdio.h>
#include <string.h>

#define DS4_CLI_ARENA_CAP (256*1024)

static int32_t ds4_cli_smoke_ctx(const ds4_config_t *cfg)
{
	ds4_ctx_t ctx;
	_Alignas(16) uint8_t arena_mem[DS4_CLI_ARENA_CAP];
	ds4_log_entry_t e;
	int32_t arena_size,c;
	if ( cfg == 0 )
		return(-1);
	arena_size = cfg->arena_size;
	if ( arena_size <= 0 )
		arena_size = (int32_t)sizeof(arena_mem);
	if ( arena_size > (int32_t)sizeof(arena_mem) )
		return(-2);
	if ( ds4_ctx_init_auto(&ctx,cfg,arena_mem,arena_size) < 0 )
		return(-3);
	if ( DS4_LOGI("ds4_cli smoke ctx") < 0 )
	{
		ds4_ctx_deinit(&ctx);
		return(-4);
	}
	if ( cfg->log_ring_entries > 0 )
	{
		if ( ds4_ctx_log_ring_count(&ctx,&c) < 0 )
		{
			ds4_ctx_deinit(&ctx);
			return(-5);
		}
		if ( c <= 0 )
		{
			ds4_ctx_deinit(&ctx);
			return(-6);
		}
		if ( ds4_ctx_log_ring_pop(&ctx,&e) < 0 )
		{
			ds4_ctx_deinit(&ctx);
			return(-7);
		}
		printf("log_ring: %s\n",e.msg);
	}
	ds4_ctx_deinit(&ctx);
	return(0);
}

static int32_t ds4_cli_smoke_cuda(const ds4_config_t *cfg)
{
	ds4_cuda_status_t st;
	ds4_cuda_device_info_t di;
	const char *s;
	int32_t build_has_cuda,dev_count,cur_dev,dev;
	if ( cfg == 0 )
		return(-1);
	build_has_cuda = ds4_cuda_is_enabled_build();
	printf("cuda build: %s\n",build_has_cuda != 0 ? "enabled" : "disabled");
	printf("cuda config: enable_cuda=%d cuda_device=%d\n",cfg->enable_cuda,cfg->cuda_device);
	if ( cfg->enable_cuda == 0 )
	{
		printf("cuda: disabled by config\n");
		return(0);
	}
	if ( build_has_cuda == 0 )
	{
		printf("cuda: unavailable (build)\n");
		return(-2);
	}
	st = ds4_cuda_init();
	if ( ds4_cuda_is_ok(st) == 0 )
	{
		s = ds4_cuda_errstr(st);
		printf("cuda: init failed: %s\n",s != 0 ? s : "?");
		return(-3);
	}
	dev_count = -1;
	st = ds4_cuda_device_count(&dev_count);
	if ( ds4_cuda_is_ok(st) == 0 )
	{
		s = ds4_cuda_errstr(st);
		printf("cuda: device_count failed: %s\n",s != 0 ? s : "?");
		return(-4);
	}
	cur_dev = -1;
	st = ds4_cuda_get_device(&cur_dev);
	if ( ds4_cuda_is_ok(st) == 0 )
	{
		s = ds4_cuda_errstr(st);
		printf("cuda: get_device failed: %s\n",s != 0 ? s : "?");
		return(-5);
	}
	dev = cfg->cuda_device;
	if ( dev == DS4_CUDA_DEVICE_AUTO )
		dev = cur_dev;
	memset(&di,0,(int32_t)sizeof(di));
	st = ds4_cuda_device_info(&di,dev);
	if ( ds4_cuda_is_ok(st) == 0 )
	{
		s = ds4_cuda_errstr(st);
		printf("cuda: device_info failed: %s\n",s != 0 ? s : "?");
		return(-6);
	}
	printf("cuda device: count=%d current=%d selected=%d name=%s cc=%d.%d mem=%" PRId64 "\n",dev_count,cur_dev,dev,di.name,di.major,di.minor,di.total_global_mem);
	return(0);
}

static void ds4_cli_usage(FILE *fp,const char *argv0)
{
	if ( fp == 0 )
		return;
	if ( argv0 == 0 )
		argv0 = "ds4_cli";
	fprintf(fp,"usage: %s [--config PATH|-] [--strict-config] [--log-level LVL] [--enable-cuda BOOL] [--cuda-device DEV] [--arena-size BYTES] [--cuda-arena-size BYTES] [--log-ring-entries N] [--dump-config] [--dump-config-keys] [--dump-config-help] [--dump-config-env] [--dump-config-env-help] [--version] [--smoke-ctx] [--smoke-cuda]\n",argv0);
	fprintf(fp,"  --config PATH     Load key=value config file (PATH or '-')\n");
	fprintf(fp,"                  (or set DS4_CONFIG for inline config text, DS4_CONFIG_PATH for a default config path)\n");
	fprintf(fp,"  --strict-config   Reject unknown keys in config file\n");
	fprintf(fp,"  --log-level LVL   Override log_level (0..3 or error/warn/info/debug)\n");
	fprintf(fp,"  --enable-cuda B   Override enable_cuda (0/1 or true/false etc)\n");
	fprintf(fp,"  --cuda            Set enable_cuda=1\n");
	fprintf(fp,"  --no-cuda         Set enable_cuda=0\n");
	fprintf(fp,"  --cuda-device D   Override cuda_device (-1=auto, >=0 fixed)\n");
	fprintf(fp,"  --arena-size B    Override arena_size (bytes)\n");
	fprintf(fp,"  --cuda-arena-size B Override cuda_arena_size (bytes)\n");
	fprintf(fp,"  --log-ring-entries N Override log_ring_entries (entries)\n");
	fprintf(fp,"  --dump-config     Print effective config to stdout\n");
	fprintf(fp,"  --dump-config-keys Print supported config keys to stdout\n");
	fprintf(fp,"  --dump-config-help Print supported config keys and value hints\n");
	fprintf(fp,"  --dump-config-env Print supported config environment variables to stdout\n");
	fprintf(fp,"  --dump-config-env-help Print supported config environment variables and hints\n");
	fprintf(fp,"  --version         Print ds4 version\n");
	fprintf(fp,"  --smoke-ctx       Init a ctx (static arena), log one line, print one log-ring entry\n");
	fprintf(fp,"  --smoke-cuda      Print CUDA build/config status and (if enabled) probe one device\n");
	fprintf(fp,"  --help            Show this help\n");
}

static int32_t ds4_cli_parse_args(int32_t argc,char **argv,const char **cfg_path,int32_t *strict_cfg,const char **log_level,const char **enable_cuda,const char **cuda_device,const char **arena_size,const char **cuda_arena_size,const char **log_ring_entries,int32_t *dump_cfg,int32_t *dump_keys,int32_t *dump_help,int32_t *dump_env,int32_t *dump_env_help,int32_t *print_ver,int32_t *smoke_ctx,int32_t *smoke_cuda)
{
	int32_t i;
	const char *a;
	if ( cfg_path == 0 )
		return(-1);
	if ( strict_cfg == 0 )
		return(-2);
	if ( log_level == 0 )
		return(-3);
	if ( enable_cuda == 0 )
		return(-4);
	if ( cuda_device == 0 )
		return(-5);
	if ( arena_size == 0 )
		return(-6);
	if ( cuda_arena_size == 0 )
		return(-7);
	if ( log_ring_entries == 0 )
		return(-8);
	if ( dump_cfg == 0 )
		return(-9);
	if ( dump_keys == 0 )
		return(-10);
	if ( dump_help == 0 )
		return(-11);
	if ( dump_env == 0 )
		return(-12);
	if ( dump_env_help == 0 )
		return(-13);
	if ( print_ver == 0 )
		return(-14);
	if ( smoke_ctx == 0 )
		return(-15);
	if ( smoke_cuda == 0 )
		return(-16);
	*cfg_path = 0;
	*strict_cfg = 0;
	*log_level = 0;
	*enable_cuda = 0;
	*cuda_device = 0;
	*arena_size = 0;
	*cuda_arena_size = 0;
	*log_ring_entries = 0;
	*dump_cfg = 0;
	*dump_keys = 0;
	*dump_help = 0;
	*dump_env = 0;
	*dump_env_help = 0;
	*print_ver = 0;
	*smoke_ctx = 0;
	*smoke_cuda = 0;
	for (i=1; i<argc; i++)
	{
		a = argv[i];
		if ( a == 0 )
			return(-10);
		if ( strcmp(a,"--help") == 0 || strcmp(a,"-h") == 0 )
			return(1);
		if ( strcmp(a,"--version") == 0 )
		{
			*print_ver = 1;
			continue;
		}
		if ( strcmp(a,"--dump-config") == 0 )
		{
			*dump_cfg = 1;
			continue;
		}
		if ( strcmp(a,"--dump-config-keys") == 0 )
		{
			*dump_keys = 1;
			continue;
		}
		if ( strcmp(a,"--dump-config-help") == 0 )
		{
			*dump_help = 1;
			continue;
		}
		if ( strcmp(a,"--dump-config-env") == 0 )
		{
			*dump_env = 1;
			continue;
		}
		if ( strcmp(a,"--dump-config-env-help") == 0 )
		{
			*dump_env_help = 1;
			continue;
		}
		if ( strcmp(a,"--config") == 0 )
		{
			if ( (i + 1) >= argc )
				return(-17);
			*cfg_path = argv[i + 1];
			i += 1;
			continue;
		}
		if ( strcmp(a,"--strict-config") == 0 )
		{
			*strict_cfg = 1;
			continue;
		}
		if ( strcmp(a,"--log-level") == 0 )
		{
			if ( (i + 1) >= argc )
				return(-18);
			*log_level = argv[i + 1];
			i += 1;
			continue;
		}
		if ( strcmp(a,"--enable-cuda") == 0 )
		{
			if ( (i + 1) >= argc )
				return(-19);
			*enable_cuda = argv[i + 1];
			i += 1;
			continue;
		}
		if ( strcmp(a,"--cuda-device") == 0 )
		{
			if ( (i + 1) >= argc )
				return(-20);
			*cuda_device = argv[i + 1];
			i += 1;
			continue;
		}
		if ( strcmp(a,"--arena-size") == 0 )
		{
			if ( (i + 1) >= argc )
				return(-21);
			*arena_size = argv[i + 1];
			i += 1;
			continue;
		}
		if ( strcmp(a,"--cuda-arena-size") == 0 )
		{
			if ( (i + 1) >= argc )
				return(-22);
			*cuda_arena_size = argv[i + 1];
			i += 1;
			continue;
		}
		if ( strcmp(a,"--log-ring-entries") == 0 )
		{
			if ( (i + 1) >= argc )
				return(-23);
			*log_ring_entries = argv[i + 1];
			i += 1;
			continue;
		}
		if ( strcmp(a,"--cuda") == 0 )
		{
			*enable_cuda = "1";
			continue;
		}
		if ( strcmp(a,"--no-cuda") == 0 )
		{
			*enable_cuda = "0";
			continue;
		}
		if ( strcmp(a,"--smoke-ctx") == 0 )
		{
			*smoke_ctx = 1;
			continue;
		}
		if ( strcmp(a,"--smoke-cuda") == 0 )
		{
			*smoke_cuda = 1;
			continue;
		}
		return(-24);
	}
	return(0);
}

static int32_t ds4_cli_dump_config_keys(void)
{
	const char *k;
	int32_t i,count;
	if ( ds4_config_known_key_count(&count) < 0 )
		return(-1);
	for (i=0; i<count; i++)
	{
		k = ds4_config_known_key(i);
		if ( k == 0 )
			return(-2);
		printf("%s\n",k);
	}
	return(0);
}

static int32_t ds4_cli_dump_config_help(void)
{
	const char *k,*h;
	int32_t i,count;
	if ( ds4_config_known_key_count(&count) < 0 )
		return(-1);
	for (i=0; i<count; i++)
	{
		k = ds4_config_known_key(i);
		if ( k == 0 )
			return(-2);
		h = ds4_config_known_key_help(i);
		if ( h == 0 )
			return(-3);
		printf("%s: %s\n",k,h);
	}
	return(0);
}

static int32_t ds4_cli_dump_config_env(void)
{
	const char *k;
	int32_t i,count;
	if ( ds4_config_env_var_count(&count) < 0 )
		return(-1);
	for (i=0; i<count; i++)
	{
		k = ds4_config_env_var(i);
		if ( k == 0 )
			return(-2);
		printf("%s\n",k);
	}
	return(0);
}

static int32_t ds4_cli_dump_config_env_help(void)
{
	const char *k,*h;
	int32_t i,count;
	if ( ds4_config_env_var_count(&count) < 0 )
		return(-1);
	for (i=0; i<count; i++)
	{
		k = ds4_config_env_var(i);
		if ( k == 0 )
			return(-2);
		h = ds4_config_env_var_help(i);
		if ( h == 0 )
			return(-3);
		printf("%s: %s\n",k,h);
	}
	return(0);
}

static int32_t ds4_cli_dump_config(const ds4_config_t *cfg)
{
	char out[128];
	int32_t n;
	if ( cfg == 0 )
		return(-1);
	n = ds4_config_format(cfg,out,(int32_t)sizeof(out));
	if ( n < 0 )
		return(-2);
	fputs(out,stdout);
	return(0);
}

static void ds4_cli_print_config_diag(const ds4_config_diag_t *d,int32_t strict_cfg,int32_t unknown)
{
	char diag_buf[128];
	int32_t n;
	diag_buf[0] = 0;
	n = ds4_config_diag_format(d,diag_buf,(int32_t)sizeof(diag_buf));
	if ( n < 0 || n >= (int32_t)sizeof(diag_buf) )
		diag_buf[0] = 0;
	if ( strict_cfg != 0 )
	{
		if ( unknown > 0 )
		{
			if ( diag_buf[0] != 0 )
				fprintf(stderr,"ds4_cli: failed to load config (strict): %d unknown keys (%s)\n",unknown,diag_buf);
			else
				fprintf(stderr,"ds4_cli: failed to load config (strict): %d unknown keys\n",unknown);
			return;
		}
		if ( diag_buf[0] != 0 )
			fprintf(stderr,"ds4_cli: failed to load config (strict): %s\n",diag_buf);
		else
			fprintf(stderr,"ds4_cli: failed to load config (strict)\n");
		return;
	}
	if ( diag_buf[0] != 0 )
		fprintf(stderr,"ds4_cli: failed to load config: %s\n",diag_buf);
	else
		fprintf(stderr,"ds4_cli: failed to load config\n");
}

int main(int argc,char **argv)
{
	ds4_config_t cfg;
	const char *cfg_path,*log_level,*enable_cuda,*cuda_device,*arena_size,*cuda_arena_size,*log_ring_entries;
	uint8_t cfg_buf[4096];
	ds4_config_diag_t diag;
	int32_t dump_cfg,dump_keys,dump_help,dump_env,dump_env_help,print_ver,strict_cfg,smoke_ctx,smoke_cuda,err,unknown;
	dump_cfg = 0;
	dump_keys = 0;
	dump_help = 0;
	dump_env = 0;
	dump_env_help = 0;
	print_ver = 0;
	strict_cfg = 0;
	smoke_ctx = 0;
	smoke_cuda = 0;
	unknown = -1;
	cfg_path = 0;
	log_level = 0;
	enable_cuda = 0;
	cuda_device = 0;
	arena_size = 0;
	cuda_arena_size = 0;
	log_ring_entries = 0;
	err = ds4_cli_parse_args((int32_t)argc,argv,&cfg_path,&strict_cfg,&log_level,&enable_cuda,&cuda_device,&arena_size,&cuda_arena_size,&log_ring_entries,&dump_cfg,&dump_keys,&dump_help,&dump_env,&dump_env_help,&print_ver,&smoke_ctx,&smoke_cuda);
	if ( err != 0 )
	{
		if ( err > 0 )
		{
			ds4_cli_usage(stdout,argv != 0 ? argv[0] : 0);
			return(0);
		}
		ds4_cli_usage(stderr,argv != 0 ? argv[0] : 0);
		return(2);
	}
	if ( dump_keys != 0 )
	{
		if ( ds4_cli_dump_config_keys() < 0 )
			return(1);
		return(0);
	}
	if ( dump_help != 0 )
	{
		if ( ds4_cli_dump_config_help() < 0 )
			return(1);
		return(0);
	}
	if ( dump_env != 0 )
	{
		if ( ds4_cli_dump_config_env() < 0 )
			return(1);
		return(0);
	}
	if ( dump_env_help != 0 )
	{
		if ( ds4_cli_dump_config_env_help() < 0 )
			return(1);
		return(0);
	}
	ds4_config_diag_init(&diag);
	unknown = -1;
	if ( strict_cfg != 0 )
		err = ds4_config_load_auto_ex_diag(&cfg,cfg_path,cfg_buf,(int32_t)sizeof(cfg_buf),0,DS4_CONFIG_PARSE_STRICT_UNKNOWN,&unknown,&diag);
	else
		err = ds4_config_load_auto_ex_diag(&cfg,cfg_path,cfg_buf,(int32_t)sizeof(cfg_buf),0,0,&unknown,&diag);
	if ( err < 0 )
	{
		ds4_cli_print_config_diag(&diag,strict_cfg,unknown);
		return(1);
	}
	if ( log_level != 0 )
	{
		err = ds4_config_parse_kv_cstr(&cfg,"log_level",log_level);
		if ( err != 0 )
			return(1);
	}
	if ( enable_cuda != 0 )
	{
		err = ds4_config_parse_kv_cstr(&cfg,"enable_cuda",enable_cuda);
		if ( err != 0 )
			return(1);
	}
	if ( cuda_device != 0 )
	{
		err = ds4_config_parse_kv_cstr(&cfg,"cuda_device",cuda_device);
		if ( err != 0 )
			return(1);
	}
	if ( arena_size != 0 )
	{
		err = ds4_config_parse_kv_cstr(&cfg,"arena_size",arena_size);
		if ( err != 0 )
			return(1);
	}
	if ( cuda_arena_size != 0 )
	{
		err = ds4_config_parse_kv_cstr(&cfg,"cuda_arena_size",cuda_arena_size);
		if ( err != 0 )
			return(1);
	}
	if ( log_ring_entries != 0 )
	{
		err = ds4_config_parse_kv_cstr(&cfg,"log_ring_entries",log_ring_entries);
		if ( err != 0 )
			return(1);
	}
	if ( ds4_config_validate(&cfg) < 0 )
	{
		fprintf(stderr,"ds4_cli: invalid config\n");
		return(1);
	}
	if ( smoke_ctx != 0 )
	{
		err = ds4_cli_smoke_ctx(&cfg);
		if ( err < 0 )
		{
			fprintf(stderr,"ds4_cli: smoke ctx failed (%d)\n",err);
			return(1);
		}
	}
	if ( smoke_cuda != 0 )
	{
		err = ds4_cli_smoke_cuda(&cfg);
		if ( err < 0 )
		{
			fprintf(stderr,"ds4_cli: smoke cuda failed (%d)\n",err);
			return(1);
		}
	}
	if ( print_ver != 0 )
	{
		ds4_version_t v;
		v = ds4_version();
		printf("%" PRIu32 ".%" PRIu32 ".%" PRIu32 "\n",v.v0,v.v1,v.v2);
	}
	if ( dump_cfg != 0 )
	{
		if ( ds4_cli_dump_config(&cfg) < 0 )
			return(1);
	}
	return(0);
}
