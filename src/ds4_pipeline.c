#include "ds4/pipeline.h"

#include <arpa/inet.h>
#include <stdint.h>
#include <string.h>
#include <sys/socket.h>
#include <time.h>
#include <unistd.h>

static uint64_t ds4_pipeline_hton64(uint64_t x)
{
	uint32_t hi,lo;
	hi = htonl((uint32_t)(x >> 32));
	lo = htonl((uint32_t)(x & 0xffffffffU));
	return(((uint64_t)lo << 32) | hi);
}

static uint64_t ds4_pipeline_ntoh64(uint64_t x)
{
	uint32_t hi,lo;
	hi = ntohl((uint32_t)(x >> 32));
	lo = ntohl((uint32_t)(x & 0xffffffffU));
	return(((uint64_t)lo << 32) | hi);
}

static int64_t ds4_pipeline_now_us(void)
{
	struct timespec ts;
	if ( clock_gettime(CLOCK_MONOTONIC,&ts) != 0 )
		return(0);
	return(((int64_t)ts.tv_sec * (int64_t)1000000) + ((int64_t)ts.tv_nsec / (int64_t)1000));
}

static int32_t ds4_pipeline_sleep_us(int32_t us)
{
	struct timespec ts;
	if ( us <= 0 )
		return(0);
	ts.tv_sec = (time_t)(us / 1000000);
	ts.tv_nsec = (long)((us % 1000000) * 1000);
	if ( nanosleep(&ts,0) != 0 )
		return(-1);
	return(0);
}

static int32_t ds4_pipeline_set_buffers(int32_t fd,int32_t bytes)
{
	if ( bytes <= 0 )
		return(0);
	if ( setsockopt(fd,SOL_SOCKET,SO_SNDBUF,&bytes,(socklen_t)sizeof(bytes)) != 0 )
		return(-1);
	if ( setsockopt(fd,SOL_SOCKET,SO_RCVBUF,&bytes,(socklen_t)sizeof(bytes)) != 0 )
		return(-2);
	return(0);
}

static int32_t ds4_pipeline_send_all(int32_t fd,const uint8_t *buf,uint64_t len)
{
	ssize_t n;
	size_t chunk;
	if ( fd < 0 )
		return(-1);
	if ( buf == 0 && len != 0 )
		return(-2);
	while ( len > 0 )
	{
		chunk = (len > (uint64_t)0x400000) ? (size_t)0x400000 : (size_t)len;
		n = send(fd,buf,chunk,0);
		if ( n <= 0 )
			return(-3);
		buf += n;
		len -= (uint64_t)n;
	}
	return(0);
}

static int32_t ds4_pipeline_recv_all(int32_t fd,uint8_t *buf,uint64_t len)
{
	ssize_t n;
	size_t chunk;
	if ( fd < 0 )
		return(-1);
	if ( buf == 0 && len != 0 )
		return(-2);
	while ( len > 0 )
	{
		chunk = (len > (uint64_t)0x400000) ? (size_t)0x400000 : (size_t)len;
		n = recv(fd,buf,chunk,0);
		if ( n <= 0 )
			return(-3);
		buf += n;
		len -= (uint64_t)n;
	}
	return(0);
}

static int32_t ds4_pipeline_send_header(int32_t fd,uint64_t seq,uint64_t len)
{
	uint64_t hdr[2];
	hdr[0] = ds4_pipeline_hton64(seq);
	hdr[1] = ds4_pipeline_hton64(len);
	return(ds4_pipeline_send_all(fd,(const uint8_t *)hdr,(uint64_t)sizeof(hdr)));
}

static int32_t ds4_pipeline_recv_header(int32_t fd,uint64_t *seq,uint64_t *len)
{
	uint64_t hdr[2];
	if ( seq == 0 )
		return(-1);
	if ( len == 0 )
		return(-2);
	if ( ds4_pipeline_recv_all(fd,(uint8_t *)hdr,(uint64_t)sizeof(hdr)) < 0 )
		return(-3);
	*seq = ds4_pipeline_ntoh64(hdr[0]);
	*len = ds4_pipeline_ntoh64(hdr[1]);
	return(0);
}

static int32_t ds4_pipeline_bind_addr(struct sockaddr_in *addr,const char *bind_ip,int32_t port)
{
	if ( addr == 0 )
		return(-1);
	if ( bind_ip == 0 )
		return(-2);
	if ( port <= 0 || port > 65535 )
		return(-3);
	memset(addr,0,sizeof(*addr));
	addr->sin_family = AF_INET;
	addr->sin_port = htons((uint16_t)port);
	if ( inet_pton(AF_INET,bind_ip,&addr->sin_addr) != 1 )
		return(-4);
	return(0);
}

static int32_t ds4_pipeline_accept_prev(const ds4_pipeline_stage_config_t *cfg)
{
	struct sockaddr_in addr;
	int32_t server,fd,one;
	server = socket(AF_INET,SOCK_STREAM,0);
	if ( server < 0 )
		return(-1);
	one = 1;
	setsockopt(server,SOL_SOCKET,SO_REUSEADDR,&one,(socklen_t)sizeof(one));
	if ( ds4_pipeline_bind_addr(&addr,cfg->listen_bind,cfg->listen_port) < 0 )
		return(-2);
	if ( ds4_pipeline_set_buffers(server,cfg->socket_buffer_bytes) < 0 )
		return(-3);
	if ( bind(server,(struct sockaddr *)&addr,(socklen_t)sizeof(addr)) != 0 )
		return(-4);
	if ( listen(server,1) != 0 )
		return(-5);
	fd = accept(server,0,0);
	close(server);
	if ( fd < 0 )
		return(-6);
	ds4_pipeline_set_buffers(fd,cfg->socket_buffer_bytes);
	return(fd);
}

static int32_t ds4_pipeline_connect_next(const ds4_pipeline_stage_config_t *cfg)
{
	struct sockaddr_in addr,local;
	int64_t deadline;
	int32_t fd,err;
	fd = socket(AF_INET,SOCK_STREAM,0);
	if ( fd < 0 )
		return(-1);
	ds4_pipeline_set_buffers(fd,cfg->socket_buffer_bytes);
	if ( cfg->next_bind != 0 && cfg->next_bind[0] != 0 )
	{
		err = ds4_pipeline_bind_addr(&local,cfg->next_bind,1);
		if ( err < 0 )
			return(-2);
		local.sin_port = 0;
		if ( bind(fd,(struct sockaddr *)&local,(socklen_t)sizeof(local)) != 0 )
			return(-3);
	}
	if ( ds4_pipeline_bind_addr(&addr,cfg->next_host,cfg->next_port) < 0 )
		return(-4);
	deadline = (ds4_pipeline_now_us() + (int64_t)30000000);
	while ( connect(fd,(struct sockaddr *)&addr,(socklen_t)sizeof(addr)) != 0 )
	{
		if ( ds4_pipeline_now_us() > deadline )
			return(-5);
		ds4_pipeline_sleep_us(100000);
	}
	return(fd);
}

static int32_t ds4_pipeline_process_one(const ds4_pipeline_stage_config_t *cfg,uint64_t seq,uint8_t *payload,uint64_t len)
{
	if ( cfg->process != 0 )
	{
		if ( cfg->process(cfg->process_ctx,seq,payload,len) < 0 )
			return(-1);
	}
	if ( ds4_pipeline_sleep_us(cfg->stage_us) < 0 )
		return(-2);
	return(0);
}

static int32_t ds4_pipeline_result_set(ds4_pipeline_stage_result_t *out,const ds4_pipeline_stage_config_t *cfg,int32_t items,uint64_t total_bytes,int64_t elapsed_us,int64_t active_us)
{
	double active_s;
	if ( out == 0 )
		return(-1);
	memset(out,0,sizeof(*out));
	if ( active_us <= 0 )
		active_us = elapsed_us;
	active_s = ((double)active_us / 1000000.0);
	out->rank = cfg->rank;
	out->world_size = cfg->world_size;
	out->items = items;
	out->payload_bytes = cfg->payload_bytes;
	out->total_payload_bytes = total_bytes;
	out->elapsed_us = elapsed_us;
	out->active_us = active_us;
	if ( active_s > 0.0 )
	{
		out->items_per_s = ((double)items / active_s);
		out->payload_GBps = ((double)total_bytes / active_s / 1000000000.0);
	}
	return(0);
}

static int32_t ds4_pipeline_run_source(const ds4_pipeline_stage_config_t *cfg,int32_t next_fd,ds4_pipeline_stage_result_t *out)
{
	int64_t start,first,end;
	int32_t i;
	start = ds4_pipeline_now_us();
	first = 0;
	for (i=0; i<cfg->items; i++)
	{
		if ( i == 0 )
			first = ds4_pipeline_now_us();
		if ( ds4_pipeline_process_one(cfg,(uint64_t)i,cfg->payload,cfg->payload_bytes) < 0 )
			return(-1);
		if ( ds4_pipeline_send_header(next_fd,(uint64_t)i,cfg->payload_bytes) < 0 )
			return(-2);
		if ( ds4_pipeline_send_all(next_fd,cfg->payload,cfg->payload_bytes) < 0 )
			return(-3);
	}
	ds4_pipeline_send_header(next_fd,(uint64_t)cfg->items,0);
	end = ds4_pipeline_now_us();
	return(ds4_pipeline_result_set(out,cfg,cfg->items,(cfg->payload_bytes * (uint64_t)cfg->items),(end - start),(end - first)));
}

static int32_t ds4_pipeline_forward_done(int32_t next_fd,uint64_t seq)
{
	if ( next_fd < 0 )
		return(0);
	if ( ds4_pipeline_send_header(next_fd,seq,0) < 0 )
		return(-1);
	return(0);
}

static int32_t ds4_pipeline_forward_payload(int32_t next_fd,uint64_t seq,uint8_t *payload,uint64_t len)
{
	if ( next_fd < 0 )
		return(0);
	if ( ds4_pipeline_send_header(next_fd,seq,len) < 0 )
		return(-1);
	if ( ds4_pipeline_send_all(next_fd,payload,len) < 0 )
		return(-2);
	return(0);
}

static int32_t ds4_pipeline_run_receiver(const ds4_pipeline_stage_config_t *cfg,int32_t prev_fd,int32_t next_fd,ds4_pipeline_stage_result_t *out)
{
	int64_t start,first,end;
	uint64_t seq,len,total;
	int32_t items;
	start = ds4_pipeline_now_us();
	first = 0;
	total = 0;
	items = 0;
	while ( ds4_pipeline_recv_header(prev_fd,&seq,&len) == 0 )
	{
		if ( len == 0 )
		{
			if ( ds4_pipeline_forward_done(next_fd,seq) < 0 )
				return(-1);
			break;
		}
		if ( len > cfg->payload_bytes )
			return(-2);
		if ( items == 0 )
			first = ds4_pipeline_now_us();
		if ( ds4_pipeline_recv_all(prev_fd,cfg->payload,len) < 0 )
			return(-3);
		if ( ds4_pipeline_process_one(cfg,seq,cfg->payload,len) < 0 )
			return(-4);
		if ( ds4_pipeline_forward_payload(next_fd,seq,cfg->payload,len) < 0 )
			return(-5);
		total += len;
		items += 1;
	}
	end = ds4_pipeline_now_us();
	return(ds4_pipeline_result_set(out,cfg,items,total,(end - start),(end - first)));
}

int32_t ds4_pipeline_stage_config_defaults(ds4_pipeline_stage_config_t *cfg)
{
	if ( cfg == 0 )
		return(-1);
	memset(cfg,0,sizeof(*cfg));
	cfg->rank = 0;
	cfg->world_size = 1;
	cfg->items = 1;
	cfg->payload_bytes = 1;
	cfg->socket_buffer_bytes = (64 * 1024 * 1024);
	return(0);
}

int32_t ds4_pipeline_stage_validate(const ds4_pipeline_stage_config_t *cfg)
{
	if ( cfg == 0 )
		return(-1);
	if ( cfg->world_size <= 0 )
		return(-2);
	if ( cfg->rank < 0 || cfg->rank >= cfg->world_size )
		return(-3);
	if ( cfg->items < 0 )
		return(-4);
	if ( cfg->payload_bytes == 0 )
		return(-5);
	if ( cfg->payload == 0 )
		return(-6);
	if ( cfg->stage_us < 0 )
		return(-7);
	if ( cfg->socket_buffer_bytes < 0 )
		return(-8);
	if ( cfg->rank > 0 && (cfg->listen_bind == 0 || cfg->listen_bind[0] == 0 || cfg->listen_port <= 0) )
		return(-9);
	if ( cfg->rank < (cfg->world_size - 1) && (cfg->next_host == 0 || cfg->next_host[0] == 0 || cfg->next_port <= 0) )
		return(-10);
	return(0);
}

int32_t ds4_pipeline_stage_run(const ds4_pipeline_stage_config_t *cfg,ds4_pipeline_stage_result_t *out)
{
	int32_t prev_fd,next_fd,err;
	if ( out == 0 )
		return(-1);
	if ( ds4_pipeline_stage_validate(cfg) < 0 )
		return(-2);
	prev_fd = -1;
	next_fd = -1;
	if ( cfg->rank > 0 )
		prev_fd = ds4_pipeline_accept_prev(cfg);
	if ( cfg->rank > 0 && prev_fd < 0 )
		return(-3);
	if ( cfg->rank < (cfg->world_size - 1) )
		next_fd = ds4_pipeline_connect_next(cfg);
	if ( cfg->rank < (cfg->world_size - 1) && next_fd < 0 )
		return(-4);
	if ( cfg->rank == 0 )
		err = ds4_pipeline_run_source(cfg,next_fd,out);
	else
		err = ds4_pipeline_run_receiver(cfg,prev_fd,next_fd,out);
	if ( prev_fd >= 0 )
		close(prev_fd);
	if ( next_fd >= 0 )
		close(next_fd);
	if ( err < 0 )
		return(-5);
	return(0);
}

int32_t ds4_pipeline_sequential_run(const ds4_pipeline_stage_config_t *cfg,ds4_pipeline_stage_result_t *out)
{
	int64_t start,end;
	int32_t i,j;
	if ( out == 0 )
		return(-1);
	if ( ds4_pipeline_stage_validate(cfg) < 0 && cfg != 0 )
	{
		if ( cfg->payload == 0 || cfg->payload_bytes == 0 || cfg->world_size <= 0 || cfg->items < 0 || cfg->stage_us < 0 )
			return(-2);
	}
	if ( cfg == 0 )
		return(-3);
	start = ds4_pipeline_now_us();
	for (i=0; i<cfg->items; i++)
		for (j=0; j<cfg->world_size; j++)
			if ( ds4_pipeline_process_one(cfg,(uint64_t)i,cfg->payload,cfg->payload_bytes) < 0 )
				return(-4);
	end = ds4_pipeline_now_us();
	return(ds4_pipeline_result_set(out,cfg,cfg->items,(cfg->payload_bytes * (uint64_t)cfg->items),(end - start),(end - start)));
}
