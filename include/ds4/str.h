#pragma once

#include <stdint.h>

static inline int32_t ds4_cstr_len_i32(const char *s)
{
	int32_t n;
	if ( s == 0 )
		return(0);
	for (n=0; s[n]!=0; n++)
		;
	return(n);
}

static inline uint8_t ds4_ascii_lower(uint8_t c)
{
	if ( c >= 'A' && c <= 'Z' )
		return((uint8_t)(c + ('a' - 'A')));
	return(c);
}

static inline int32_t ds4_span_eq(const char *a,int32_t alen,const char *b)
{
	int32_t i;
	if ( a == 0 )
		return(0);
	if ( b == 0 )
		return(0);
	if ( alen <= 0 )
		return(0);
	for (i=0; b[i]!=0; i++)
	{
		if ( i >= alen )
			return(0);
		if ( a[i] != b[i] )
			return(0);
	}
	if ( i != alen )
		return(0);
	return(1);
}

static inline int32_t ds4_span_eq_ci(const char *a,int32_t alen,const char *b)
{
	int32_t i;
	uint8_t ca,cb;
	if ( a == 0 )
		return(0);
	if ( b == 0 )
		return(0);
	if ( alen <= 0 )
		return(0);
	for (i=0; b[i]!=0; i++)
	{
		if ( i >= alen )
			return(0);
		ca = ds4_ascii_lower((uint8_t)a[i]);
		cb = ds4_ascii_lower((uint8_t)b[i]);
		if ( ca != cb )
			return(0);
	}
	if ( i != alen )
		return(0);
	return(1);
}
