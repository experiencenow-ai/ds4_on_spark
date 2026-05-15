#include "ds4/pipeline.h"

int32_t ds4_header_smoke_pipeline(void);

int32_t ds4_header_smoke_pipeline(void)
{
	return((int)sizeof(ds4_pipeline_stage_config_t));
}
