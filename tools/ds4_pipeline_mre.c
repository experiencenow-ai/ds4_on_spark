#include "ds4/pipeline.h"

#include <stdint.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>

typedef struct
{
	int32_t role;
	const char *pipeline_id;
	const char *model_id;
	const char *runtime_id;
	const char *stage_node;
	const char *process_mode;
} mre_options_t;

typedef struct
{
	int32_t rank;
	uint64_t calls;
	uint64_t checksum;
} mre_process_ctx_t;

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

static void fnv_mix_u64(uint64_t *h,uint64_t v)
{
	int32_t i;
	if ( h == 0 )
		return;
	for (i=0; i<8; i++)
	{
		*h ^= ((v >> (i * 8)) & 0xff);
		*h *= 1099511628211ULL;
	}
}

static int32_t checksum_process(void *ctx,uint64_t seq,uint8_t *payload,uint64_t payload_bytes)
{
	mre_process_ctx_t *p;
	uint64_t mid,last;
	if ( ctx == 0 || payload == 0 || payload_bytes == 0 )
		return(-1);
	p = (mre_process_ctx_t *)ctx;
	mid = (payload_bytes / 2);
	last = (payload_bytes - 1);
	p->calls += 1;
	fnv_mix_u64(&p->checksum,seq);
	fnv_mix_u64(&p->checksum,payload_bytes);
	fnv_mix_u64(&p->checksum,(uint64_t)payload[0]);
	fnv_mix_u64(&p->checksum,(uint64_t)payload[mid]);
	fnv_mix_u64(&p->checksum,(uint64_t)payload[last]);
	payload[0] ^= (uint8_t)((seq + (uint64_t)p->rank + 1ULL) & 0xffU);
	payload[mid] ^= (uint8_t)(((seq >> 1) + (uint64_t)p->rank + 17ULL) & 0xffU);
	payload[last] ^= (uint8_t)(((seq >> 2) + (uint64_t)p->rank + 31ULL) & 0xffU);
	return(0);
}

static int32_t apply_arg(ds4_pipeline_stage_config_t *cfg,const char *key,const char *value,mre_options_t *opts)
{
	int32_t iv;
	uint64_t u64;
	if ( cfg == 0 || key == 0 || value == 0 || opts == 0 )
		return(-1);
	if ( strcmp(key,"--role") == 0 )
	{
		if ( strcmp(value,"rank") == 0 )
			opts->role = 0;
		else if ( strcmp(value,"sequential") == 0 )
			opts->role = 1;
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

static int32_t apply_str_arg(ds4_pipeline_stage_config_t *cfg,const char *key,const char *value,mre_options_t *opts)
{
	if ( cfg == 0 || key == 0 || value == 0 || opts == 0 )
		return(-1);
	if ( strcmp(key,"--listen-bind") == 0 )
		cfg->listen_bind = value;
	else if ( strcmp(key,"--next-bind") == 0 )
		cfg->next_bind = value;
	else if ( strcmp(key,"--next-host") == 0 )
		cfg->next_host = value;
	else if ( strcmp(key,"--pipeline-id") == 0 )
		opts->pipeline_id = value;
	else if ( strcmp(key,"--model-id") == 0 )
		opts->model_id = value;
	else if ( strcmp(key,"--runtime-id") == 0 )
		opts->runtime_id = value;
	else if ( strcmp(key,"--stage-node") == 0 )
		opts->stage_node = value;
	else if ( strcmp(key,"--process") == 0 )
		opts->process_mode = value;
	else
		return(-2);
	return(0);
}

static int32_t parse_args(ds4_pipeline_stage_config_t *cfg,int32_t argc,char **argv,mre_options_t *opts)
{
	int32_t i;
	if ( ds4_pipeline_stage_config_defaults(cfg) < 0 )
		return(-1);
	memset(opts,0,sizeof(*opts));
	opts->role = 0;
	opts->pipeline_id = "local-pipeline-mre";
	opts->model_id = "ds4-pipeline-mre";
	opts->runtime_id = "ds4_pipeline_mre";
	opts->stage_node = "";
	opts->process_mode = "none";
	for (i=1; i<argc; i++)
	{
		if ( strcmp(argv[i],"--help") == 0 )
			return(1);
		if ( i + 1 >= argc )
			return(-2);
		if ( apply_str_arg(cfg,argv[i],argv[i + 1],opts) == 0 )
		{
			i++;
			continue;
		}
		if ( apply_arg(cfg,argv[i],argv[i + 1],opts) < 0 )
			return(-3);
		i++;
	}
	return(0);
}

static void usage(const char *argv0)
{
	fprintf(stderr,"usage: %s --role rank|sequential --rank N --world-size N --items N --payload-bytes N [--stage-us N|--stage-ms N] [--listen-bind IP --listen-port P] [--next-bind IP --next-host IP --next-port P] [--pipeline-id ID --model-id ID --runtime-id ID --stage-node ID --process none|checksum]\n",argv0);
}

static void print_json_string(const char *s)
{
	const unsigned char *p;
	putchar('"');
	if ( s != 0 )
	{
		for (p=(const unsigned char *)s; *p!=0; p++)
		{
			if ( *p == '"' || *p == '\\' )
				printf("\\%c",*p);
			else if ( *p >= 32 && *p < 127 )
				putchar(*p);
			else
				printf("\\u%04x",(unsigned int)*p);
		}
	}
	putchar('"');
}

static void print_result(const ds4_pipeline_stage_result_t *r,int32_t rc,const mre_options_t *opts,const mre_process_ctx_t *pctx)
{
	printf("{\n");
	printf("  \"format\": \"ds4-pipeline-stage-result-v1\",\n");
	printf("  \"ok\": %s,\n",rc == 0 ? "true" : "false");
	printf("  \"rc\": %d,\n",rc);
	printf("  \"role\": ");
	print_json_string(opts->role == 0 ? "rank" : "sequential");
	printf(",\n");
	printf("  \"pipeline_id\": ");
	print_json_string(opts->pipeline_id);
	printf(",\n");
	printf("  \"model_id\": ");
	print_json_string(opts->model_id);
	printf(",\n");
	printf("  \"runtime_id\": ");
	print_json_string(opts->runtime_id);
	printf(",\n");
	printf("  \"stage_node\": ");
	print_json_string(opts->stage_node);
	printf(",\n");
	printf("  \"rank\": %d,\n",r->rank);
	printf("  \"world_size\": %d,\n",r->world_size);
	printf("  \"items\": %d,\n",r->items);
	printf("  \"payload_bytes\": %llu,\n",(unsigned long long)r->payload_bytes);
	printf("  \"total_payload_bytes\": %llu,\n",(unsigned long long)r->total_payload_bytes);
	printf("  \"elapsed_us\": %lld,\n",(long long)r->elapsed_us);
	printf("  \"active_us\": %lld,\n",(long long)r->active_us);
	printf("  \"items_per_s\": %.9f,\n",r->items_per_s);
	printf("  \"payload_GBps\": %.9f,\n",r->payload_GBps);
	printf("  \"process_mode\": ");
	print_json_string(opts->process_mode);
	printf(",\n");
	printf("  \"process_calls\": %llu,\n",(unsigned long long)pctx->calls);
	printf("  \"payload_checksum\": \"%016llx\"\n",(unsigned long long)pctx->checksum);
	printf("}\n");
}

int main(int argc,char **argv)
{
	ds4_pipeline_stage_config_t cfg;
	ds4_pipeline_stage_result_t result;
	mre_options_t opts;
	mre_process_ctx_t pctx;
	int32_t err,parse_err;
	parse_err = parse_args(&cfg,(int32_t)argc,argv,&opts);
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
	memset(&pctx,0,sizeof(pctx));
	pctx.rank = cfg.rank;
	pctx.checksum = 1469598103934665603ULL;
	if ( strcmp(opts.process_mode,"checksum") == 0 )
	{
		cfg.process = checksum_process;
		cfg.process_ctx = &pctx;
	}
	else if ( strcmp(opts.process_mode,"none") != 0 )
	{
		free(cfg.payload);
		return(5);
	}
	memset(&result,0,sizeof(result));
	if ( opts.role == 0 )
		err = ds4_pipeline_stage_run(&cfg,&result);
	else
		err = ds4_pipeline_sequential_run(&cfg,&result);
	print_result(&result,err,&opts,&pctx);
	free(cfg.payload);
	if ( err < 0 )
		return(4);
	return(0);
}
