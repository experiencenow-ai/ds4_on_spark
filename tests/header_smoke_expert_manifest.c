#include "ds4/expert_manifest.h"

int32_t ds4_header_smoke_expert_manifest(void);

int32_t ds4_header_smoke_expert_manifest(void)
{
	ds4_expert_manifest_view_t m;
	m.rank = 0;
	return(m.rank);
}
