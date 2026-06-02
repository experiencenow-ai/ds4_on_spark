#define _POSIX_C_SOURCE 200809L
#include <errno.h>
#include <fcntl.h>
#include <inttypes.h>
#include <pthread.h>
#include <stdint.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <unistd.h>

#define DS4_MAX_SHARDS 6
#define DS4_ALIGN 4096
#define DS4_LINE_MAX 1024
#define XXH_PRIME64_1 11400714785074694791ULL
#define XXH_PRIME64_2 14029467366897019727ULL
#define XXH_PRIME64_3 1609587929392839161ULL
#define XXH_PRIME64_4 9650029242287828579ULL
#define XXH_PRIME64_5 2870177450012600261ULL

typedef struct
{
	int32_t fd;
	int32_t rc;
	uint8_t *buf;
	uint64_t len,offset,hash;
}
io_job_t;

typedef struct
{
	uint64_t extent,object_extent,offset,shard_len,logical_len,hash[DS4_MAX_SHARDS];
	int32_t parity_slot;
}
extent_plan_t;

static uint64_t rotl64(uint64_t x,int32_t r)
{
	return((x << r) | (x >> (64 - r)));
}

static uint64_t read64(uint8_t *p)
{
	uint64_t v;
	memcpy(&v,p,sizeof(v));
	return(v);
}

static uint32_t read32(uint8_t *p)
{
	uint32_t v;
	memcpy(&v,p,sizeof(v));
	return(v);
}

static uint64_t xxh_round(uint64_t acc,uint64_t input)
{
	acc += (input * XXH_PRIME64_2);
	acc = rotl64(acc,31);
	acc *= XXH_PRIME64_1;
	return(acc);
}

static uint64_t xxh_merge(uint64_t acc,uint64_t val)
{
	val = xxh_round(0,val);
	acc ^= val;
	acc = ((acc * XXH_PRIME64_1) + XXH_PRIME64_4);
	return(acc);
}

static uint64_t hash64_bytes(uint8_t *data,uint64_t len)
{
	uint8_t *p = data,*end = data + len,*limit;
	uint64_t h,v1,v2,v3,v4;
	if ( len >= 32 )
	{
		limit = end - 32;
		v1 = XXH_PRIME64_1 + XXH_PRIME64_2;
		v2 = XXH_PRIME64_2;
		v3 = 0;
		v4 = 0 - XXH_PRIME64_1;
		do
		{
			v1 = xxh_round(v1,read64(p)); p += 8;
			v2 = xxh_round(v2,read64(p)); p += 8;
			v3 = xxh_round(v3,read64(p)); p += 8;
			v4 = xxh_round(v4,read64(p)); p += 8;
		}
		while ( p <= limit );
		h = rotl64(v1,1) + rotl64(v2,7) + rotl64(v3,12) + rotl64(v4,18);
		h = xxh_merge(h,v1);
		h = xxh_merge(h,v2);
		h = xxh_merge(h,v3);
		h = xxh_merge(h,v4);
	}
	else
		h = XXH_PRIME64_5;
	h += len;
	while ( (p + 8) <= end )
	{
		h ^= xxh_round(0,read64(p));
		h = ((rotl64(h,27) * XXH_PRIME64_1) + XXH_PRIME64_4);
		p += 8;
	}
	if ( (p + 4) <= end )
	{
		h ^= ((uint64_t)read32(p) * XXH_PRIME64_1);
		h = ((rotl64(h,23) * XXH_PRIME64_2) + XXH_PRIME64_3);
		p += 4;
	}
	while ( p < end )
	{
		h ^= ((uint64_t)(*p) * XXH_PRIME64_5);
		h = (rotl64(h,11) * XXH_PRIME64_1);
		p++;
	}
	h ^= (h >> 33);
	h *= XXH_PRIME64_2;
	h ^= (h >> 29);
	h *= XXH_PRIME64_3;
	h ^= (h >> 32);
	return(h);
}

static int32_t valid_shard_count(int32_t n)
{
	return(n == 4 || n == 6);
}

static int32_t parse_u64(char *arg,uint64_t *out)
{
	char *end = 0;
	errno = 0;
	*out = strtoull(arg,&end,10);
	if ( errno != 0 || end == arg || *end != 0 )
		return(-1);
	return(0);
}

static int32_t parse_hex64(char *arg,uint64_t *out)
{
	char *end = 0;
	errno = 0;
	*out = strtoull(arg,&end,16);
	if ( errno != 0 || end == arg || *end != 0 )
		return(-1);
	return(0);
}

static int32_t open_path(char *path,int32_t rw)
{
	int32_t fd;
	fd = rw != 0 ? open(path,O_CREAT|O_RDWR,0666) : open(path,O_RDONLY);
	if ( fd < 0 )
		fprintf(stderr,"open failed %s: %s\n",path,strerror(errno));
	return(fd);
}

static int32_t open_files(char **paths,int32_t fds[DS4_MAX_SHARDS],int32_t shard_count,int32_t rw)
{
	int32_t i;
	for (i=0; i<DS4_MAX_SHARDS; i++)
		fds[i] = -1;
	for (i=0; i<shard_count; i++)
	{
		fds[i] = open_path(paths[i],rw);
		if ( fds[i] < 0 )
			return(-1);
	}
	return(0);
}

static void close_files(int32_t fds[DS4_MAX_SHARDS],int32_t shard_count)
{
	int32_t i;
	for (i=0; i<shard_count; i++)
		if ( fds[i] >= 0 )
			close(fds[i]);
}

static int32_t alloc_aligned(uint8_t **ptr,uint64_t len)
{
	if ( posix_memalign((void **)ptr,DS4_ALIGN,(size_t)len) != 0 )
		return(-1);
	return(0);
}

static int32_t write_full(int32_t fd,uint8_t *buf,uint64_t len)
{
	uint64_t done = 0;
	ssize_t n;
	while ( done < len )
	{
		n = write(fd,buf + done,(size_t)(len - done));
		if ( n < 0 && errno == EINTR )
			continue;
		if ( n <= 0 )
			return(-1);
		done += (uint64_t)n;
	}
	return(0);
}

static int32_t write_full_at(int32_t fd,uint8_t *buf,uint64_t len,uint64_t offset)
{
	uint64_t done = 0;
	ssize_t n;
	while ( done < len )
	{
		n = pwrite(fd,buf + done,(size_t)(len - done),(off_t)(offset + done));
		if ( n < 0 && errno == EINTR )
			continue;
		if ( n <= 0 )
			return(-1);
		done += (uint64_t)n;
	}
	return(0);
}

static int32_t read_full_at(int32_t fd,uint8_t *buf,uint64_t len,uint64_t offset)
{
	uint64_t done = 0;
	ssize_t n;
	while ( done < len )
	{
		n = pread(fd,buf + done,(size_t)(len - done),(off_t)(offset + done));
		if ( n < 0 && errno == EINTR )
			continue;
		if ( n <= 0 )
			return(-1);
		done += (uint64_t)n;
	}
	return(0);
}

static int32_t read_extent(int32_t fd,uint8_t *buf,uint64_t cap,uint64_t *out)
{
	uint64_t done = 0;
	ssize_t n;
	while ( done < cap )
	{
		n = read(fd,buf + done,(size_t)(cap - done));
		if ( n < 0 && errno == EINTR )
			continue;
		if ( n < 0 )
			return(-1);
		if ( n == 0 )
			break;
		done += (uint64_t)n;
	}
	*out = done;
	return(0);
}

static void xor_data(uint8_t *out,uint8_t *shards[DS4_MAX_SHARDS],int32_t data_shards,uint64_t len)
{
	uint64_t i;
	int32_t di;
	memcpy(out,shards[0],(size_t)len);
	for (di=1; di<data_shards; di++)
		for (i=0; i<len; i++)
			out[i] = (uint8_t)(out[i] ^ shards[di][i]);
}

static void xor_other(uint8_t *out,uint8_t *bufs[DS4_MAX_SHARDS],int32_t shard_count,int32_t skip,uint64_t len)
{
	uint64_t i;
	int32_t slot;
	memset(out,0,(size_t)len);
	for (slot=0; slot<shard_count; slot++)
	{
		if ( slot == skip )
			continue;
		for (i=0; i<len; i++)
			out[i] = (uint8_t)(out[i] ^ bufs[slot][i]);
	}
}

static int32_t data_slot(int32_t shard_count,int32_t parity_slot,int32_t data_index)
{
	int32_t slot,count = 0;
	for (slot=0; slot<shard_count; slot++)
	{
		if ( slot == parity_slot )
			continue;
		if ( count == data_index )
			return(slot);
		count++;
	}
	return(-1);
}

static int32_t data_index_for_slot(int32_t shard_count,int32_t parity_slot,int32_t target_slot)
{
	int32_t slot,count = 0;
	for (slot=0; slot<shard_count; slot++)
	{
		if ( slot == parity_slot )
			continue;
		if ( slot == target_slot )
			return(count);
		count++;
	}
	return(-1);
}

static void *write_job_main(void *arg)
{
	io_job_t *job = (io_job_t *)arg;
	job->hash = hash64_bytes(job->buf,job->len);
	job->rc = write_full_at(job->fd,job->buf,job->len,job->offset);
	return(0);
}

static void *read_job_main(void *arg)
{
	io_job_t *job = (io_job_t *)arg;
	job->rc = read_full_at(job->fd,job->buf,job->len,job->offset);
	if ( job->rc == 0 )
		job->hash = hash64_bytes(job->buf,job->len);
	return(0);
}

static int32_t run_jobs(io_job_t jobs[DS4_MAX_SHARDS],void *(*mainfn)(void *),int32_t use[DS4_MAX_SHARDS],int32_t shard_count)
{
	pthread_t tids[DS4_MAX_SHARDS];
	int32_t slot,created[DS4_MAX_SHARDS] = {0},rc = 0;
	for (slot=0; slot<shard_count; slot++)
	{
		if ( use[slot] == 0 )
			continue;
		if ( pthread_create(&tids[slot],0,mainfn,&jobs[slot]) != 0 )
			jobs[slot].rc = -1;
		else
			created[slot] = 1;
	}
	for (slot=0; slot<shard_count; slot++)
	{
		if ( created[slot] != 0 )
			pthread_join(tids[slot],0);
		if ( use[slot] != 0 && jobs[slot].rc != 0 )
			rc = -1;
	}
	return(rc);
}

static int32_t write_shards(int32_t fds[DS4_MAX_SHARDS],uint8_t *payloads[DS4_MAX_SHARDS],int32_t shard_count,uint64_t len,uint64_t offset,uint64_t hash[DS4_MAX_SHARDS])
{
	io_job_t jobs[DS4_MAX_SHARDS];
	int32_t slot,use[DS4_MAX_SHARDS] = {0},rc;
	for (slot=0; slot<shard_count; slot++)
	{
		jobs[slot].fd = fds[slot];
		jobs[slot].buf = payloads[slot];
		jobs[slot].len = len;
		jobs[slot].offset = offset;
		jobs[slot].hash = 0;
		jobs[slot].rc = -1;
		use[slot] = 1;
	}
	rc = run_jobs(jobs,write_job_main,use,shard_count);
	for (slot=0; slot<shard_count; slot++)
		hash[slot] = jobs[slot].hash;
	return(rc);
}

static int32_t read_shards(int32_t fds[DS4_MAX_SHARDS],uint8_t *bufs[DS4_MAX_SHARDS],int32_t shard_count,uint64_t len,uint64_t offset,uint64_t hash[DS4_MAX_SHARDS],int32_t use[DS4_MAX_SHARDS],int32_t ok[DS4_MAX_SHARDS])
{
	io_job_t jobs[DS4_MAX_SHARDS];
	int32_t slot,rc;
	for (slot=0; slot<shard_count; slot++)
	{
		jobs[slot].fd = fds[slot];
		jobs[slot].buf = bufs[slot];
		jobs[slot].len = len;
		jobs[slot].offset = offset;
		jobs[slot].hash = 0;
		jobs[slot].rc = -1;
		ok[slot] = 0;
	}
	rc = run_jobs(jobs,read_job_main,use,shard_count);
	for (slot=0; slot<shard_count; slot++)
		if ( use[slot] != 0 && jobs[slot].rc == 0 && jobs[slot].hash == hash[slot] )
			ok[slot] = 1;
	return(rc);
}

static int32_t parse_plan_header(FILE *fp,int32_t *shard_count,int32_t *data_shards)
{
	char line[DS4_LINE_MAX];
	if ( fgets(line,sizeof(line),fp) == 0 )
		return(-1);
	if ( sscanf(line,"ds4-xor-plan-v2\t%d\t%d",shard_count,data_shards) == 2 )
		return(valid_shard_count(*shard_count) != 0 && *data_shards == (*shard_count - 1) ? 0 : -1);
	if ( strcmp(line,"ds4-xor-plan-v1\n") == 0 || strcmp(line,"ds4-xor-plan-v1") == 0 )
	{
		*shard_count = 6;
		*data_shards = 5;
		return(0);
	}
	return(-1);
}

static int32_t parse_extent_line(char *line,extent_plan_t *plan,int32_t shard_count)
{
	char *save = 0,*tok;
	int32_t i;
	tok = strtok_r(line,"\t\n",&save);
	if ( tok == 0 || strcmp(tok,"E") != 0 )
		return(-1);
	if ( (tok = strtok_r(0,"\t\n",&save)) == 0 || parse_u64(tok,&plan->extent) < 0 )
		return(-2);
	if ( (tok = strtok_r(0,"\t\n",&save)) == 0 || parse_u64(tok,&plan->object_extent) < 0 )
		return(-3);
	if ( (tok = strtok_r(0,"\t\n",&save)) == 0 || parse_u64(tok,&plan->offset) < 0 )
		return(-4);
	if ( (tok = strtok_r(0,"\t\n",&save)) == 0 || parse_u64(tok,&plan->shard_len) < 0 )
		return(-5);
	if ( (tok = strtok_r(0,"\t\n",&save)) == 0 || parse_u64(tok,&plan->logical_len) < 0 )
		return(-6);
	if ( (tok = strtok_r(0,"\t\n",&save)) == 0 )
		return(-7);
	plan->parity_slot = atoi(tok);
	if ( plan->parity_slot < 0 || plan->parity_slot >= shard_count )
		return(-8);
	for (i=0; i<shard_count; i++)
	{
		if ( (tok = strtok_r(0,"\t\n",&save)) == 0 || parse_hex64(tok,&plan->hash[i]) < 0 )
			return(-9);
	}
	return(strtok_r(0,"\t\n",&save) == 0 ? 0 : -10);
}

static uint64_t plan_max_shard_len(char *plan_path,int32_t *shard_count,int32_t *data_shards)
{
	FILE *fp;
	char line[DS4_LINE_MAX];
	extent_plan_t plan;
	uint64_t max_len = 0;
	fp = fopen(plan_path,"r");
	if ( fp == 0 )
		return(0);
	if ( parse_plan_header(fp,shard_count,data_shards) < 0 )
	{
		fclose(fp);
		return(0);
	}
	while ( fgets(line,sizeof(line),fp) != 0 )
		if ( line[0] == 'E' && parse_extent_line(line,&plan,*shard_count) == 0 && plan.shard_len > max_len )
			max_len = plan.shard_len;
	fclose(fp);
	return(max_len);
}

static int32_t emit_extent(FILE *plan,extent_plan_t *extent,int32_t shard_count)
{
	int32_t slot;
	if ( fprintf(plan,"E\t%" PRIu64 "\t%" PRIu64 "\t%" PRIu64 "\t%" PRIu64 "\t%" PRIu64 "\t%d",extent->extent,extent->object_extent,extent->offset,extent->shard_len,extent->logical_len,extent->parity_slot) < 0 )
		return(-1);
	for (slot=0; slot<shard_count; slot++)
		if ( fprintf(plan,"\t%016" PRIx64,extent->hash[slot]) < 0 )
			return(-2);
	return(fprintf(plan,"\n") < 0 ? -3 : 0);
}

static int32_t cmd_put(int32_t argc,char **argv)
{
	FILE *planfp;
	extent_plan_t extent;
	uint8_t *buf = 0,*parity = 0,*shard[DS4_MAX_SHARDS],*payloads[DS4_MAX_SHARDS];
	uint64_t start_offset,start_extent,extent_payload,offset,read_len,object_extent = 0,logical_total = 0,object_hash = 0;
	int32_t in,slot,di,shard_count,data_shards,fds[DS4_MAX_SHARDS],rc = -1;
	shard_count = (argc - 7);
	data_shards = (shard_count - 1);
	if ( argc < 11 || parse_u64(argv[4],&start_offset) < 0 || parse_u64(argv[5],&start_extent) < 0 || parse_u64(argv[6],&extent_payload) < 0 || extent_payload == 0 || valid_shard_count(shard_count) == 0 )
		return(-1);
	in = open_path(argv[2],0);
	planfp = fopen(argv[3],"w");
	if ( in < 0 || planfp == 0 || open_files(&argv[7],fds,shard_count,1) < 0 )
		return(-2);
	if ( alloc_aligned(&buf,extent_payload + (uint64_t)data_shards) < 0 || alloc_aligned(&parity,(extent_payload + (uint64_t)data_shards) / (uint64_t)data_shards) < 0 )
		return(-3);
	fprintf(planfp,"ds4-xor-plan-v2\t%d\t%d\n",shard_count,data_shards);
	offset = start_offset;
	while ( read_extent(in,buf,extent_payload,&read_len) == 0 && read_len > 0 )
	{
		memset(&extent,0,sizeof(extent));
		extent.shard_len = ((read_len + (uint64_t)data_shards - 1) / (uint64_t)data_shards);
		memset(buf + read_len,0,(size_t)((extent.shard_len * (uint64_t)data_shards) - read_len));
		for (di=0; di<data_shards; di++)
			shard[di] = buf + (extent.shard_len * (uint64_t)di);
		xor_data(parity,shard,data_shards,extent.shard_len);
		extent.parity_slot = (int32_t)((start_extent + object_extent) % (uint64_t)shard_count);
		for (slot=0; slot<shard_count; slot++)
			payloads[slot] = (slot == extent.parity_slot) ? parity : shard[data_index_for_slot(shard_count,extent.parity_slot,slot)];
		if ( write_shards(fds,payloads,shard_count,extent.shard_len,offset,extent.hash) < 0 )
			goto cleanup;
		extent.extent = (start_extent + object_extent);
		extent.object_extent = object_extent;
		extent.offset = offset;
		extent.logical_len = read_len;
		if ( emit_extent(planfp,&extent,shard_count) < 0 )
			goto cleanup;
		offset += extent.shard_len;
		logical_total += read_len;
		object_extent++;
	}
	fprintf(planfp,"O\t%" PRIu64 "\t%016" PRIx64 "\n",logical_total,object_hash);
	rc = 0;
cleanup:
	free(buf);
	free(parity);
	if ( in >= 0 )
		close(in);
	if ( planfp != 0 )
		fclose(planfp);
	close_files(fds,shard_count);
	fprintf(stderr,"logical_bytes=%" PRIu64 " extents=%" PRIu64 " shards=%d data_shards=%d\n",logical_total,object_extent,shard_count,data_shards);
	return(rc);
}

static int32_t read_all_for_extent(int32_t fds[DS4_MAX_SHARDS],uint8_t *bufs[DS4_MAX_SHARDS],int32_t shard_count,uint64_t shard_len,uint64_t offset,uint64_t hash[DS4_MAX_SHARDS],int32_t ok[DS4_MAX_SHARDS])
{
	int32_t slot,use[DS4_MAX_SHARDS] = {0};
	for (slot=0; slot<shard_count; slot++)
		use[slot] = 1;
	read_shards(fds,bufs,shard_count,shard_len,offset,hash,use,ok);
	return(0);
}

static int32_t write_logical_extent(int32_t out,uint8_t *bufs[DS4_MAX_SHARDS],int32_t shard_count,int32_t data_shards,uint64_t shard_len,uint64_t logical_len,int32_t parity_slot)
{
	uint64_t remaining = logical_len,take;
	int32_t di,slot;
	for (di=0; di<data_shards && remaining > 0; di++)
	{
		slot = data_slot(shard_count,parity_slot,di);
		take = remaining < shard_len ? remaining : shard_len;
		if ( write_full(out,bufs[slot],take) < 0 )
			return(-1);
		remaining -= take;
	}
	return(0);
}

static int32_t get_extent(int32_t out,int32_t fds[DS4_MAX_SHARDS],uint8_t *bufs[DS4_MAX_SHARDS],int32_t shard_count,int32_t data_shards,extent_plan_t *extent)
{
	int32_t slot,di,use[DS4_MAX_SHARDS] = {0},ok[DS4_MAX_SHARDS] = {0},bad_count = 0,bad_slot = -1;
	for (di=0; di<data_shards; di++)
		use[data_slot(shard_count,extent->parity_slot,di)] = 1;
	read_shards(fds,bufs,shard_count,extent->shard_len,extent->offset,extent->hash,use,ok);
	for (di=0; di<data_shards; di++)
		if ( ok[data_slot(shard_count,extent->parity_slot,di)] == 0 )
			bad_count++;
	if ( bad_count == 0 )
		return(write_logical_extent(out,bufs,shard_count,data_shards,extent->shard_len,extent->logical_len,extent->parity_slot));
	read_all_for_extent(fds,bufs,shard_count,extent->shard_len,extent->offset,extent->hash,ok);
	bad_count = 0;
	for (slot=0; slot<shard_count; slot++)
		if ( ok[slot] == 0 )
		{
			bad_count++;
			bad_slot = slot;
		}
	if ( bad_count > 1 )
		return(-1);
	xor_other(bufs[bad_slot],bufs,shard_count,bad_slot,extent->shard_len);
	return(write_logical_extent(out,bufs,shard_count,data_shards,extent->shard_len,extent->logical_len,extent->parity_slot));
}

static int32_t cmd_get(int32_t argc,char **argv)
{
	FILE *planfp;
	char line[DS4_LINE_MAX];
	extent_plan_t extent;
	uint8_t *storage = 0,*bufs[DS4_MAX_SHARDS];
	uint64_t max_len;
	int32_t out,slot,shard_count,path_count,data_shards,fds[DS4_MAX_SHARDS],rc = -1;
	path_count = (argc - 4);
	if ( argc < 8 || valid_shard_count(path_count) == 0 )
		return(-1);
	max_len = plan_max_shard_len(argv[3],&shard_count,&data_shards);
	if ( max_len == 0 || shard_count != path_count || alloc_aligned(&storage,max_len * (uint64_t)shard_count) < 0 )
		return(-2);
	for (slot=0; slot<shard_count; slot++)
		bufs[slot] = storage + (max_len * (uint64_t)slot);
	out = open(argv[2],O_CREAT|O_TRUNC|O_WRONLY,0666);
	planfp = fopen(argv[3],"r");
	if ( out < 0 || planfp == 0 || parse_plan_header(planfp,&shard_count,&data_shards) < 0 || open_files(&argv[4],fds,shard_count,0) < 0 )
		goto cleanup;
	while ( fgets(line,sizeof(line),planfp) != 0 )
		if ( line[0] == 'E' && parse_extent_line(line,&extent,shard_count) == 0 && get_extent(out,fds,bufs,shard_count,data_shards,&extent) < 0 )
			goto cleanup;
	rc = 0;
cleanup:
	free(storage);
	if ( out >= 0 )
		close(out);
	if ( planfp != 0 )
		fclose(planfp);
	close_files(fds,shard_count);
	return(rc);
}

static int32_t verify_or_repair_extent(int32_t fds[DS4_MAX_SHARDS],uint8_t *bufs[DS4_MAX_SHARDS],int32_t shard_count,extent_plan_t *extent,int32_t repair)
{
	int32_t slot,ok[DS4_MAX_SHARDS] = {0},bad_count = 0,bad_slot = -1;
	read_all_for_extent(fds,bufs,shard_count,extent->shard_len,extent->offset,extent->hash,ok);
	for (slot=0; slot<shard_count; slot++)
		if ( ok[slot] == 0 )
		{
			bad_count++;
			bad_slot = slot;
		}
	if ( bad_count == 1 && repair != 0 )
	{
		xor_other(bufs[bad_slot],bufs,shard_count,bad_slot,extent->shard_len);
		if ( write_full_at(fds[bad_slot],bufs[bad_slot],extent->shard_len,extent->offset) < 0 )
			return(-2);
		return(1);
	}
	return(bad_count);
}

static int32_t cmd_verify_or_repair(int32_t argc,char **argv,int32_t repair)
{
	FILE *planfp;
	char line[DS4_LINE_MAX];
	extent_plan_t extent;
	uint8_t *storage = 0,*bufs[DS4_MAX_SHARDS];
	uint64_t max_len,bad_extents = 0,repaired = 0;
	int32_t slot,shard_count,path_count,data_shards,bad,fds[DS4_MAX_SHARDS],rc = -1;
	path_count = (argc - 3);
	if ( argc < 7 || valid_shard_count(path_count) == 0 )
		return(-1);
	max_len = plan_max_shard_len(argv[2],&shard_count,&data_shards);
	if ( max_len == 0 || shard_count != path_count || alloc_aligned(&storage,max_len * (uint64_t)shard_count) < 0 )
		return(-2);
	for (slot=0; slot<shard_count; slot++)
		bufs[slot] = storage + (max_len * (uint64_t)slot);
	planfp = fopen(argv[2],"r");
	if ( planfp == 0 || parse_plan_header(planfp,&shard_count,&data_shards) < 0 || open_files(&argv[3],fds,shard_count,repair) < 0 )
		goto cleanup;
	while ( fgets(line,sizeof(line),planfp) != 0 )
	{
		if ( line[0] != 'E' || parse_extent_line(line,&extent,shard_count) < 0 )
			continue;
		bad = verify_or_repair_extent(fds,bufs,shard_count,&extent,repair);
		if ( bad < 0 || bad > 1 )
			goto cleanup;
		if ( bad > 0 )
			bad_extents++;
		if ( bad == 1 && repair != 0 )
			repaired++;
	}
	fprintf(stdout,"{\"bad_extents\":%" PRIu64 ",\"repaired_extents\":%" PRIu64 "}\n",bad_extents,repaired);
	rc = bad_extents == 0 || repair != 0 ? 0 : 1;
cleanup:
	free(storage);
	if ( planfp != 0 )
		fclose(planfp);
	close_files(fds,shard_count);
	return(rc);
}

int main(int argc,char **argv)
{
	if ( argc > 1 && strcmp(argv[1],"put") == 0 )
		return(cmd_put(argc,argv) == 0 ? 0 : 1);
	if ( argc > 1 && strcmp(argv[1],"get") == 0 )
		return(cmd_get(argc,argv) == 0 ? 0 : 1);
	if ( argc > 1 && strcmp(argv[1],"verify") == 0 )
		return(cmd_verify_or_repair(argc,argv,0));
	if ( argc > 1 && strcmp(argv[1],"repair") == 0 )
		return(cmd_verify_or_repair(argc,argv,1) == 0 ? 0 : 1);
	fprintf(stderr,"usage:\n");
	fprintf(stderr,"  %s put input plan start_offset start_extent extent_payload shard0 shard1 shard2 shard3 [shard4 shard5]\n",argv[0]);
	fprintf(stderr,"  %s get output plan shard0 shard1 shard2 shard3 [shard4 shard5]\n",argv[0]);
	fprintf(stderr,"  %s verify plan shard0 shard1 shard2 shard3 [shard4 shard5]\n",argv[0]);
	fprintf(stderr,"  %s repair plan shard0 shard1 shard2 shard3 [shard4 shard5]\n",argv[0]);
	return(2);
}
