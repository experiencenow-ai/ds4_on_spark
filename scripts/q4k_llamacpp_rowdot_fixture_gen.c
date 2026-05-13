#include <errno.h>
#include <inttypes.h>
#include <math.h>
#include <stdint.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>

#include "ggml-quants.h"

typedef struct
{
	const char *out_path;
	const char *up_repo;
	const char *up_ref;
	const char *up_commit;
	int32_t vectors;
	uint32_t seed_block0;
	uint32_t seed_x0;
} fixture_cfg_t;

static uint32_t xorshift32(uint32_t x)
{
	x ^= x << 13;
	x ^= x >> 17;
	x ^= x << 5;
	return(x);
}

static float f32_round(float x)
{
	union { float f; uint32_t u; } v;
	v.f = x;
	return(v.f);
}

static void rng_bytes(uint32_t seed,uint8_t *out,int32_t n)
{
	int32_t i;
	uint32_t s = seed;
	for (i=0; i<n; i++)
	{
		s = xorshift32(s);
		out[i] = (uint8_t)(s & 0xFFu);
	}
}

static void gen_x_vec(uint32_t seed_x,float *out,int32_t n)
{
	int32_t i;
	uint32_t s = seed_x;
	for (i=0; i<n; i++)
	{
		s = xorshift32(s);
		float t = f32_round((float)(s & 0x00FFFFFFu) / (float)0x01000000u);
		out[i] = f32_round(f32_round(t * 6.0f) - 3.0f);
	}
}

static int32_t hex_encode(const uint8_t *src,int32_t n,char *dst,int32_t dst_cap)
{
	static const char h[] = "0123456789abcdef";
	int32_t i;
	if (dst_cap < ((n * 2) + 1))
		return(-1);
	for (i=0; i<n; i++)
	{
		dst[i*2+0] = h[(src[i] >> 4) & 0xF];
		dst[i*2+1] = h[src[i] & 0xF];
	}
	dst[n*2] = 0;
	return(0);
}

static int32_t parse_i32_arg(const char *s,int32_t *out)
{
	char *end = 0;
	long v;
	errno = 0;
	v = strtol(s,&end,10);
	if (errno != 0 || end == s || *end != 0)
		return(-1);
	if (v < INT32_MIN || v > INT32_MAX)
		return(-2);
	*out = (int32_t)v;
	return(0);
}

static int32_t parse_u32_arg(const char *s,uint32_t *out)
{
	char *end = 0;
	unsigned long v;
	errno = 0;
	v = strtoul(s,&end,10);
	if (errno != 0 || end == s || *end != 0)
		return(-1);
	if (v > 0xFFFFFFFFul)
		return(-2);
	*out = (uint32_t)v;
	return(0);
}

static int32_t parse_args(int argc,char **argv,fixture_cfg_t *cfg)
{
	int32_t i;
	for (i=1; i<argc; i++)
	{
		if (strcmp(argv[i],"--out") == 0 && i+1 < argc)
			cfg->out_path = argv[++i];
		else if (strcmp(argv[i],"--up-ref") == 0 && i+1 < argc)
			cfg->up_ref = argv[++i];
		else if (strcmp(argv[i],"--up-commit") == 0 && i+1 < argc)
			cfg->up_commit = argv[++i];
		else if (strcmp(argv[i],"--vectors") == 0 && i+1 < argc)
		{
			if (parse_i32_arg(argv[++i],&cfg->vectors) != 0 || cfg->vectors <= 0)
			{
				fprintf(stderr,"bad --vectors\n");
				return(-1);
			}
		}
		else if (strcmp(argv[i],"--seed-block0") == 0 && i+1 < argc)
		{
			if (parse_u32_arg(argv[++i],&cfg->seed_block0) != 0)
			{
				fprintf(stderr,"bad --seed-block0\n");
				return(-2);
			}
		}
		else if (strcmp(argv[i],"--seed-x0") == 0 && i+1 < argc)
		{
			if (parse_u32_arg(argv[++i],&cfg->seed_x0) != 0)
			{
				fprintf(stderr,"bad --seed-x0\n");
				return(-3);
			}
		}
		else
		{
			fprintf(stderr,"usage: %s --out <path> [--vectors N] [--up-ref REF] [--up-commit SHA]\n",argv[0]);
			return(-4);
		}
	}
	return(0);
}

static int32_t write_fixture(FILE *fp,const fixture_cfg_t *cfg)
{
	int32_t i,j;
	fprintf(fp,"{\n");
	fprintf(fp,"  \"block_bytes\": 144,\n");
	fprintf(fp,"  \"notes\": {\n");
	fprintf(fp,"    \"block_rng\": \"xorshift32 bytes\",\n");
	fprintf(fp,"    \"generator\": \"C tool linked against ggml-base dequantize_row_q4_K\",\n");
	fprintf(fp,"    \"x_rng\": \"xorshift32; map (u&0x00FFFFFF)/2^24 * 6 - 3\"\n");
	fprintf(fp,"  },\n");
	fprintf(fp,"  \"qk\": 256,\n");
	fprintf(fp,"  \"schema\": 1,\n");
	fprintf(fp,"  \"upstream\": {\n");
	fprintf(fp,"    \"commit\": \"%s\",\n",cfg->up_commit);
	fprintf(fp,"    \"ref\": \"%s\",\n",cfg->up_ref);
	fprintf(fp,"    \"repo\": \"%s\"\n",cfg->up_repo);
	fprintf(fp,"  },\n");
	fprintf(fp,"  \"vectors\": [\n");
	for (i=0; i<cfg->vectors; i++)
	{
		uint32_t seed_block = cfg->seed_block0 + (uint32_t)(i * 0x9e3779b9u);
		uint32_t seed_x = cfg->seed_x0 + (uint32_t)(i * 0x7f4a7c15u);
		uint8_t block_bytes[144];
		float x[256],w[256];
		double dot = 0.0;
		rng_bytes(seed_block,block_bytes,144);
		gen_x_vec(seed_x,x,256);
		dequantize_row_q4_K((const block_q4_K *)block_bytes,w,256);
		for (j=0; j<256; j++)
			dot += (double)w[j] * (double)x[j];
		char hex[(144*2)+1];
		if (hex_encode(block_bytes,144,hex,(int32_t)sizeof(hex)) != 0)
			return(-1);
		fprintf(fp,"    {\n");
		fprintf(fp,"      \"block_hex\": \"%s\",\n",hex);
		fprintf(fp,"      \"dot\": %.17g,\n",dot);
		fprintf(fp,"      \"seed_block\": %" PRIu32 ",\n",seed_block);
		fprintf(fp,"      \"seed_x\": %" PRIu32 "\n",seed_x);
		fprintf(fp,"    }%s\n",(i == (cfg->vectors-1)) ? "" : ",");
	}
	fprintf(fp,"  ]\n");
	fprintf(fp,"}\n");
	return(0);
}

int main(int argc,char **argv)
{
	fixture_cfg_t cfg;
	memset(&cfg,0,sizeof(cfg));
	cfg.up_repo = "ggml-org/llama.cpp";
	cfg.up_ref = "refs/tags/b9110";
	cfg.up_commit = "unknown";
	cfg.vectors = 16;
	cfg.seed_block0 = 2654435778u;
	cfg.seed_x0 = 467453664u;
	if (parse_args(argc,argv,&cfg) < 0)
		return(2);
	if (cfg.out_path == 0)
	{
		fprintf(stderr,"missing --out\n");
		return(2);
	}
	FILE *fp = fopen(cfg.out_path,"wb");
	if (fp == 0)
	{
		fprintf(stderr,"fopen(%s) failed\n",cfg.out_path);
		return(3);
	}
	if (write_fixture(fp,&cfg) < 0)
	{
		fclose(fp);
		fprintf(stderr,"write_fixture failed\n");
		return(4);
	}
	fclose(fp);
	return(0);
}
