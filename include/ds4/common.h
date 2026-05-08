#pragma once

#include <stdint.h>

#define DS4_UNUSED(x) ((void)(x))

typedef struct
{
	uint32_t v0,v1,v2;
} ds4_version_t;

ds4_version_t ds4_version(void);
