#include "ds4/cuda.h"

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
	if ( v < 0 || v > 2147483647L )
		return(-3);
	*out = (int32_t)v;
	return(0);
}

static int32_t apply_arg(ds4_cuda_expert_queue_dummy_config_t *cfg,const char *key,const char *value)
{
	int32_t v;
	if ( cfg == 0 || key == 0 || value == 0 )
		return(-1);
	if ( parse_i32(value,&v) < 0 )
		return(-2);
	if ( strcmp(key,"--tokens") == 0 )
		cfg->tokens = v;
	else if ( strcmp(key,"--topk") == 0 )
		cfg->topk = v;
	else if ( strcmp(key,"--experts") == 0 )
		cfg->n_experts = v;
	else if ( strcmp(key,"--hidden") == 0 )
		cfg->hidden_dim = v;
	else if ( strcmp(key,"--mid") == 0 )
		cfg->mid_dim = v;
	else if ( strcmp(key,"--out") == 0 )
		cfg->out_dim = v;
	else if ( strcmp(key,"--iterations") == 0 )
		cfg->iterations = v;
	else if ( strcmp(key,"--seed") == 0 )
		cfg->seed = (uint32_t)v;
	else
		return(-3);
	return(0);
}

static void usage(const char *argv0)
{
	fprintf(stderr,"usage: %s [--json] [--tokens N] [--topk N] [--experts N] [--hidden N] [--mid N] [--out N] [--iterations N] [--seed N]\n",argv0);
}

static void print_json(const ds4_cuda_expert_queue_dummy_result_t *r,int32_t cuda_code,const char *cuda_error)
{
	printf("{\n");
	printf("  \"ok\": %s,\n",cuda_code == 0 ? "true" : "false");
	printf("  \"cuda_code\": %d,\n",cuda_code);
	printf("  \"cuda_error\": \"%s\",\n",cuda_error);
	printf("  \"tokens\": %d,\n",r->tokens);
	printf("  \"topk\": %d,\n",r->topk);
	printf("  \"experts\": %d,\n",r->n_experts);
	printf("  \"hidden_dim\": %d,\n",r->hidden_dim);
	printf("  \"mid_dim\": %d,\n",r->mid_dim);
	printf("  \"out_dim\": %d,\n",r->out_dim);
	printf("  \"iterations\": %d,\n",r->iterations);
	printf("  \"gateup_ms\": %.6f,\n",r->gateup_ms);
	printf("  \"down_ms\": %.6f,\n",r->down_ms);
	printf("  \"total_ms\": %.6f,\n",r->total_ms);
	printf("  \"tokens_per_s\": %.6f,\n",r->tokens_per_s);
	printf("  \"expert_pairs_per_s\": %.6f,\n",r->expert_pairs_per_s);
	printf("  \"estimated_gib_per_s\": %.6f,\n",r->estimated_gib_per_s);
	printf("  \"estimated_bytes_moved\": %lld\n",(long long)r->estimated_bytes_moved);
	printf("}\n");
}

int main(int argc,char **argv)
{
	ds4_cuda_expert_queue_dummy_config_t cfg;
	ds4_cuda_expert_queue_dummy_result_t result;
	ds4_cuda_status_t st;
	const char *err;
	int32_t i,json;
	ds4_cuda_expert_queue_dummy_default_config(&cfg);
	json = 0;
	for (i=1; i<argc; i++)
	{
		if ( strcmp(argv[i],"--help") == 0 )
		{
			usage(argv[0]);
			return(0);
		}
		if ( strcmp(argv[i],"--json") == 0 )
		{
			json = 1;
			continue;
		}
		if ( i + 1 >= argc || apply_arg(&cfg,argv[i],argv[i + 1]) < 0 )
		{
			usage(argv[0]);
			return(2);
		}
		i++;
	}
	st = ds4_cuda_expert_queue_dummy_run(&cfg,&result);
	err = ds4_cuda_errstr(st);
	if ( err == 0 )
		err = "?";
	if ( json != 0 )
		print_json(&result,st.code,err);
	else
	{
		printf("ok=%d cuda_code=%d err=%s tokens=%d topk=%d experts=%d hidden=%d mid=%d out=%d iterations=%d gateup_ms=%.6f down_ms=%.6f total_ms=%.6f tokens_per_s=%.6f expert_pairs_per_s=%.6f estimated_gib_per_s=%.6f\n",
			st.code == 0 ? 1 : 0,st.code,err,result.tokens,result.topk,result.n_experts,result.hidden_dim,result.mid_dim,result.out_dim,result.iterations,result.gateup_ms,result.down_ms,result.total_ms,result.tokens_per_s,result.expert_pairs_per_s,result.estimated_gib_per_s);
	}
	if ( st.code != 0 )
		return(3);
	return(0);
}
