# Build (GGUF metadata-only)

The build skeleton includes a minimal GGUF v3 header/metadata parser (`include/ds4/gguf.h`) intended for future loader work.

Notes:

- No allocations: parsing is zero-copy over a caller-provided buffer.
- Metadata-only: this does not load tensor data.
- Prefix-only usage: for large GGUFs, read a prefix (header + metadata + tensor table) into memory before calling `ds4_gguf_parse_mem`.

Example:

```c
ds4_gguf_view_t g;
ds4_gguf_kv_view_t kv;
ds4_gguf_str_t arch;
int32_t rc;

rc = ds4_gguf_parse_mem(&g,buf,len);
if ( rc < 0 )
	return(rc);
if ( ds4_gguf_find_kv(&g,"general.architecture",&kv) == 0 )
{
	if ( ds4_gguf_kv_as_string(&kv,&arch) == 0 )
		DS4_LOGI("GGUF arch: %.*s",(int)arch.len,arch.ptr);
}
```
