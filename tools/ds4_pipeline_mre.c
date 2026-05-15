#include "ds4/pipeline.h"

#include <stdint.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>

static int32_t parse_i32(const char *s,int32_t *out)
{
	char *end;
	long v;
	if ( s == 0 || out == 0 )
		return(-1);
	end = 0;
	v = strtol(s,&end,10);
	if ( end == s || end == 0 || *end != 0 )
		return(-2);
	if ( v < -2147483647L || v > 2147483647L )
		return(-3);
	*out = (int32_t)v;
	return(0);
}

static int32_t parse_u64(const char *s,uint64_t *out)
{
	char *end;
	unsigned long long v;
	if ( s == 0 || out == 0 )
		return(-1);
	end = 0;
	v = strtoull(s,&end,10);
	if ( end == s || end == 0 || *end != 0 )
		return(-2);
	*out = (uint64_t)v;
	return(0);
}

static int32_t apply_arg(ds4_pipeline_stage_config_t *cfg,const char *key,const char *value,int32_t *role)
{
	int32_t iv;
	uint64_t u64;
	if ( cfg == 0 || key == 0 || value == 0 || role == 0 )
		return(-1);
	if ( strcmp(key,"--role") == 0 )
	{
		if ( strcmp(value,"rank") == 0 )
			*role = 0;
		else if ( strcmp(value,"sequential") == 0 )
			*role = 1;
		else
			return(-2);
		return(0);
	}
	if ( strcmp(key,"--payload-bytes") == 0 )
	{
		if ( parse_u64(value,&u64) < 0 )
			return(-3);
		cfg->payload_bytes = u64;
		return(0);
	}
	if ( parse_i32(value,&iv) < 0 )
		return(-4);
	if ( strcmp(key,"--rank") == 0 )
		cfg->rank = iv;
	else if ( strcmp(key,"--world-size") == 0 )
		cfg->world_size = iv;
	else if ( strcmp(key,"--items") == 0 )
		cfg->items = iv;
	else if ( strcmp(key,"--stage-us") == 0 )
		cfg->stage_us = iv;
	else if ( strcmp(key,"--stage-ms") == 0 )
		cfg->stage_us = (iv * 1000);
	else if ( strcmp(key,"--listen-port") == 0 )
		cfg->listen_port = iv;
	else if ( strcmp(key,"--next-port") == 0 )
		cfg->next_port = iv;
	else if ( strcmp(key,"--socket-buffer-bytes") == 0 )
		cfg->socket_buffer_bytes = iv;
	else
		return(-5);
	return(0);
}

static int32_t apply_str_arg(ds4_pipeline_stage_config_t *cfg,const char *key,const char *value)
{
	if ( cfg == 0 || key == 0 || value == 0 )
		return(-1);
	if ( strcmp(key,"--listen-bind") == 0 )
		cfg->listen_bind = value;
	else if ( strcmp(key,"--next-bind") == 0 )
		cfg->next_bind = value;
	else if ( strcmp(key,"--next-host") == 0 )
		cfg->next_host = value;
	else
		return(-2);
	return(0);
}

static int32_t parse_args(ds4_pipeline_stage_config_t *cfg,int32_t argc,char **argv,int32_t *role)
{
	int32_t i;
	if ( ds4_pipeline_stage_config_defaults(cfg) < 0 )
		return(-1);
	*role = 0;
	for (i=1; i<argc; i++)
	{
		if ( strcmp(argv[i],"--help") == 0 )
			return(1);
		if ( i + 1 >= argc )
			return(-2);
		if ( apply_str_arg(cfg,argv[i],argv[i + 1]) == 0 )
		{
			i++;
			continue;
		}
		if ( apply_arg(cfg,argv[i],argv[i + 1],role) < 0 )
			return(-3);
		i++;
	}
	return(0);
}

static void usage(const char *argv0)
{
	fprintf(stderr,"usage: %s --role rank|sequential --rank N --world-size N --items N --payload-bytes N [--stage-us N|--stage-ms N] [--listen-bind IP --listen-port P] [--next-bind IP --next-host IP --next-port P]\n",argv0);
}

static void print_result(const ds4_pipeline_stage_result_t *r,int32_t rc)
{
	printf("{\n");
	printf("  \"ok\": %s,\n",rc == 0 ? "true" : "false");
	printf("  \"rc\": %d,\n",rc);
	printf("  \"rank\": %d,\n",r->rank);
	printf("  \"world_size\": %d,\n",r->world_size);
	printf("  \"items\": %d,\n",r->items);
	printf("  \"payload_bytes\": %llu,\n",(unsigned long long)r->payload_bytes);
	printf("  \"total_payload_bytes\": %llu,\n",(unsigned long long)r->total_payload_bytes);
	printf("  \"elapsed_us\": %lld,\n",(long long)r->elapsed_us);
	printf("  \"active_us\": %lld,\n",(long long)r->active_us);
	printf("  \"items_per_s\": %.9f,\n",r->items_per_s);
	printf("  \"payload_GBps\": %.9f\n",r->payload_GBps);
	printf("}\n");
}

int main(int argc,char **argv)
{
	ds4_pipeline_stage_config_t cfg;
	ds4_pipeline_stage_result_t result;
	int32_t role,err,parse_err;
	parse_err = parse_args(&cfg,(int32_t)argc,argv,&role);
	if ( parse_err != 0 )
	{
		usage(argv[0]);
		if ( parse_err > 0 )
			return(0);
		return(2);
	}
	cfg.payload = calloc(1,(size_t)cfg.payload_bytes);
	if ( cfg.payload == 0 )
		return(3);
	memset(&result,0,sizeof(result));
	if ( role == 0 )
		err = ds4_pipeline_stage_run(&cfg,&result);
	else
		err = ds4_pipeline_sequential_run(&cfg,&result);
	print_result(&result,err);
	free(cfg.payload);
	if ( err < 0 )
		return(4);
	return(0);
}
