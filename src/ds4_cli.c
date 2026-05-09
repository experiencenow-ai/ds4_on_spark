#include "ds4/ds4.h"

#include <inttypes.h>
#include <stdio.h>
#include <string.h>

static void ds4_cli_usage(FILE *fp,const char *argv0)
{
	if ( fp == 0 )
		return;
	if ( argv0 == 0 )
		argv0 = "ds4_cli";
	fprintf(fp,"usage: %s [--config PATH] [--dump-config] [--version]\n",argv0);
	fprintf(fp,"  --config PATH     Load key=value config file\n");
	fprintf(fp,"  --dump-config     Print effective config to stdout\n");
	fprintf(fp,"  --version         Print ds4 version\n");
	fprintf(fp,"  --help            Show this help\n");
}

static int32_t ds4_cli_parse_args(int32_t argc,char **argv,const char **cfg_path,int32_t *dump_cfg,int32_t *print_ver)
{
	int32_t i;
	const char *a;
	if ( cfg_path == 0 )
		return(-1);
	if ( dump_cfg == 0 )
		return(-2);
	if ( print_ver == 0 )
		return(-3);
	*cfg_path = 0;
	*dump_cfg = 0;
	*print_ver = 0;
	for (i=1; i<argc; i++)
	{
		a = argv[i];
		if ( a == 0 )
			return(-4);
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
		if ( strcmp(a,"--config") == 0 )
		{
			if ( (i + 1) >= argc )
				return(-5);
			*cfg_path = argv[i + 1];
			i += 1;
			continue;
		}
		return(-6);
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

int main(int argc,char **argv)
{
	ds4_config_t cfg;
	const char *cfg_path;
	uint8_t cfg_buf[4096];
	int32_t dump_cfg,print_ver,err;
	dump_cfg = 0;
	print_ver = 0;
	cfg_path = 0;
	err = ds4_cli_parse_args((int32_t)argc,argv,&cfg_path,&dump_cfg,&print_ver);
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
	if ( ds4_config_load_auto(&cfg,cfg_path,cfg_buf,(int32_t)sizeof(cfg_buf),0) < 0 )
	{
		fprintf(stderr,"ds4_cli: failed to load config\n");
		return(1);
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
