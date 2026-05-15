#include "ds4/pipeline.h"

#include <stdint.h>

#include "test_suite.h"

static int32_t test_pipeline_process(void *ctx,uint64_t seq,uint8_t *payload,uint64_t payload_bytes)
{
	int32_t *count;
	if ( ctx == 0 )
		return(-1);
	if ( payload == 0 )
		return(-2);
	if ( payload_bytes == 0 )
		return(-3);
	count = (int32_t *)ctx;
	*count += 1;
	payload[0] = (uint8_t)(seq & 0xff);
	return(0);
}

int32_t test_pipeline(void)
{
	ds4_pipeline_stage_config_t cfg;
	ds4_pipeline_stage_result_t out;
	uint8_t payload[8];
	int32_t count;
	if ( ds4_pipeline_stage_config_defaults(&cfg) < 0 )
		return(-1);
	if ( cfg.world_size != 1 )
		return(-2);
	if ( cfg.payload_bytes != 1 )
		return(-3);
	if ( ds4_pipeline_stage_validate(&cfg) == 0 )
		return(-4);
	cfg.payload = payload;
	cfg.payload_bytes = (uint64_t)sizeof(payload);
	cfg.items = 4;
	cfg.world_size = 3;
	cfg.rank = 0;
	if ( ds4_pipeline_stage_validate(&cfg) == 0 )
		return(-5);
	cfg.next_host = "127.0.0.1";
	cfg.next_port = 1;
	if ( ds4_pipeline_stage_validate(&cfg) < 0 )
		return(-6);
	cfg.rank = 2;
	cfg.next_host = 0;
	cfg.next_port = 0;
	if ( ds4_pipeline_stage_validate(&cfg) == 0 )
		return(-7);
	cfg.listen_bind = "127.0.0.1";
	cfg.listen_port = 1;
	if ( ds4_pipeline_stage_validate(&cfg) < 0 )
		return(-8);
	count = 0;
	cfg.process = test_pipeline_process;
	cfg.process_ctx = &count;
	if ( ds4_pipeline_sequential_run(&cfg,&out) < 0 )
		return(-9);
	if ( out.items != 4 )
		return(-10);
	if ( out.world_size != 3 )
		return(-11);
	if ( count != 12 )
		return(-12);
	if ( out.items_per_s <= 0.0 )
		return(-13);
	return(0);
}
