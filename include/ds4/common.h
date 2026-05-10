#pragma once

#include <stdint.h>

#ifdef __cplusplus
#define DS4_EXTERN_C_BEGIN extern "C" {
#define DS4_EXTERN_C_END }
#else
#define DS4_EXTERN_C_BEGIN
#define DS4_EXTERN_C_END
#endif

#define DS4_UNUSED(x) ((void)(x))

#ifndef DS4_VERSION_V0
#define DS4_VERSION_V0 0
#endif

#ifndef DS4_VERSION_V1
#define DS4_VERSION_V1 0
#endif

#ifndef DS4_VERSION_V2
#define DS4_VERSION_V2 0
#endif

typedef struct
{
	uint32_t v0,v1,v2;
} ds4_version_t;

DS4_EXTERN_C_BEGIN
ds4_version_t ds4_version(void);
DS4_EXTERN_C_END
