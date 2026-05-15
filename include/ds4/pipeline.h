#pragma once

#include "ds4/common.h"

typedef int32_t (*ds4_pipeline_process_f)(void *ctx,uint64_t seq,uint8_t *payload,uint64_t payload_bytes);

typedef struct
{
	int32_t rank;
	int32_t world_size;
	int32_t items;
	int32_t listen_port;
	int32_t next_port;
	int32_t socket_buffer_bytes;
	int32_t stage_us;
	const char *listen_bind;
	const char *next_bind;
	const char *next_host;
	uint8_t *payload;
	uint64_t payload_bytes;
	ds4_pipeline_process_f process;
	void *process_ctx;
} ds4_pipeline_stage_config_t;

typedef struct
{
	int32_t rank;
	int32_t world_size;
	int32_t items;
	uint64_t payload_bytes;
	uint64_t total_payload_bytes;
	int64_t elapsed_us;
	int64_t active_us;
	double items_per_s;
	double payload_GBps;
} ds4_pipeline_stage_result_t;

DS4_EXTERN_C_BEGIN
int32_t ds4_pipeline_stage_config_defaults(ds4_pipeline_stage_config_t *cfg);
int32_t ds4_pipeline_stage_validate(const ds4_pipeline_stage_config_t *cfg);
int32_t ds4_pipeline_stage_run(const ds4_pipeline_stage_config_t *cfg,ds4_pipeline_stage_result_t *out);
int32_t ds4_pipeline_sequential_run(const ds4_pipeline_stage_config_t *cfg,ds4_pipeline_stage_result_t *out);
DS4_EXTERN_C_END
