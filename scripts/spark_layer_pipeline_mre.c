#include <arpa/inet.h>
#include <errno.h>
#include <netinet/in.h>
#include <stdint.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <sys/socket.h>
#include <time.h>
#include <unistd.h>

typedef struct
{
	int32_t role;
	int32_t rank;
	int32_t world_size;
	int32_t items;
	int32_t listen_port;
	int32_t next_port;
	int32_t socket_buffer_mib;
	uint64_t payload_bytes;
	double stage_ms;
	const char *listen_bind;
	const char *next_bind;
	const char *next_host;
} config_t;

static uint64_t hton64(uint64_t x)
{
	uint32_t hi,lo;
	hi = htonl((uint32_t)(x >> 32));
	lo = htonl((uint32_t)(x & 0xffffffffU));
	return(((uint64_t)lo << 32) | hi);
}

static uint64_t ntoh64(uint64_t x)
{
	uint32_t hi,lo;
	hi = ntohl((uint32_t)(x >> 32));
	lo = ntohl((uint32_t)(x & 0xffffffffU));
	return(((uint64_t)lo << 32) | hi);
}

static double now_sec(void)
{
	struct timespec ts;
	clock_gettime(CLOCK_MONOTONIC,&ts);
	return((double)ts.tv_sec + ((double)ts.tv_nsec / 1000000000.0));
}

static void sleep_stage(double stage_ms)
{
	struct timespec ts;
	if ( stage_ms <= 0.0 )
		return;
	ts.tv_sec = (time_t)(stage_ms / 1000.0);
	ts.tv_nsec = (long)(((stage_ms / 1000.0) - (double)ts.tv_sec) * 1000000000.0);
	nanosleep(&ts,0);
}

static int32_t set_buffers(int32_t fd,int32_t mib)
{
	int32_t value;
	if ( mib <= 0 )
		return(0);
	value = (mib * 1024 * 1024);
	if ( setsockopt(fd,SOL_SOCKET,SO_SNDBUF,&value,sizeof(value)) != 0 )
		return(-1);
	if ( setsockopt(fd,SOL_SOCKET,SO_RCVBUF,&value,sizeof(value)) != 0 )
		return(-2);
	return(0);
}

static int32_t send_all(int32_t fd,const uint8_t *buf,uint64_t len)
{
	int64_t n;
	while ( len > 0 )
	{
		n = send(fd,buf,(len > 0x400000) ? 0x400000 : (size_t)len,0);
		if ( n <= 0 )
			return(-1);
		buf += n;
		len -= (uint64_t)n;
	}
	return(0);
}

static int32_t recv_all(int32_t fd,uint8_t *buf,uint64_t len)
{
	int64_t n;
	while ( len > 0 )
	{
		n = recv(fd,buf,(len > 0x400000) ? 0x400000 : (size_t)len,0);
		if ( n <= 0 )
			return(-1);
		buf += n;
		len -= (uint64_t)n;
	}
	return(0);
}

static int32_t send_header(int32_t fd,uint64_t seq,uint64_t len)
{
	uint64_t hdr[2];
	hdr[0] = hton64(seq);
	hdr[1] = hton64(len);
	return(send_all(fd,(uint8_t *)hdr,sizeof(hdr)));
}

static int32_t recv_header(int32_t fd,uint64_t *seq,uint64_t *len)
{
	uint64_t hdr[2];
	if ( recv_all(fd,(uint8_t *)hdr,sizeof(hdr)) < 0 )
		return(-1);
	*seq = ntoh64(hdr[0]);
	*len = ntoh64(hdr[1]);
	return(0);
}

static int32_t accept_prev(const char *bind_ip,int32_t port,int32_t buffer_mib)
{
	struct sockaddr_in addr;
	int32_t server,fd,one;
	server = socket(AF_INET,SOCK_STREAM,0);
	if ( server < 0 )
		return(-1);
	one = 1;
	setsockopt(server,SOL_SOCKET,SO_REUSEADDR,&one,sizeof(one));
	memset(&addr,0,sizeof(addr));
	addr.sin_family = AF_INET;
	addr.sin_port = htons((uint16_t)port);
	if ( inet_pton(AF_INET,bind_ip,&addr.sin_addr) != 1 )
		return(-2);
	if ( set_buffers(server,buffer_mib) < 0 )
		return(-3);
	if ( bind(server,(struct sockaddr *)&addr,sizeof(addr)) != 0 )
		return(-4);
	if ( listen(server,1) != 0 )
		return(-5);
	fd = accept(server,0,0);
	close(server);
	if ( fd < 0 )
		return(-6);
	set_buffers(fd,buffer_mib);
	return(fd);
}

static int32_t connect_next(const char *host,int32_t port,const char *bind_ip,int32_t buffer_mib)
{
	struct sockaddr_in addr,local;
	double deadline;
	int32_t fd;
	fd = socket(AF_INET,SOCK_STREAM,0);
	if ( fd < 0 )
		return(-1);
	set_buffers(fd,buffer_mib);
	if ( bind_ip != 0 && bind_ip[0] != 0 )
	{
		memset(&local,0,sizeof(local));
		local.sin_family = AF_INET;
		local.sin_port = 0;
		if ( inet_pton(AF_INET,bind_ip,&local.sin_addr) != 1 )
			return(-2);
		if ( bind(fd,(struct sockaddr *)&local,sizeof(local)) != 0 )
			return(-3);
	}
	memset(&addr,0,sizeof(addr));
	addr.sin_family = AF_INET;
	addr.sin_port = htons((uint16_t)port);
	if ( inet_pton(AF_INET,host,&addr.sin_addr) != 1 )
		return(-4);
	deadline = (now_sec() + 30.0);
	while ( connect(fd,(struct sockaddr *)&addr,sizeof(addr)) != 0 )
	{
		if ( now_sec() > deadline )
			return(-5);
		usleep(100000);
	}
	return(fd);
}

static int32_t parse_args(config_t *cfg,int32_t argc,char **argv)
{
	int32_t i;
	memset(cfg,0,sizeof(*cfg));
	cfg->role = 0;
	cfg->world_size = 1;
	cfg->items = 120;
	cfg->payload_bytes = (16ULL * 1024ULL * 1024ULL);
	cfg->stage_ms = 22.2;
	cfg->socket_buffer_mib = 64;
	for (i=1; i<argc; i++)
	{
		if ( strcmp(argv[i],"--role") == 0 && i+1 < argc )
			cfg->role = (strcmp(argv[++i],"sequential") == 0) ? 1 : 0;
		else if ( strcmp(argv[i],"--rank") == 0 && i+1 < argc )
			cfg->rank = atoi(argv[++i]);
		else if ( strcmp(argv[i],"--world-size") == 0 && i+1 < argc )
			cfg->world_size = atoi(argv[++i]);
		else if ( strcmp(argv[i],"--items") == 0 && i+1 < argc )
			cfg->items = atoi(argv[++i]);
		else if ( strcmp(argv[i],"--payload-bytes") == 0 && i+1 < argc )
			cfg->payload_bytes = strtoull(argv[++i],0,10);
		else if ( strcmp(argv[i],"--stage-ms") == 0 && i+1 < argc )
			cfg->stage_ms = atof(argv[++i]);
		else if ( strcmp(argv[i],"--listen-bind") == 0 && i+1 < argc )
			cfg->listen_bind = argv[++i];
		else if ( strcmp(argv[i],"--listen-port") == 0 && i+1 < argc )
			cfg->listen_port = atoi(argv[++i]);
		else if ( strcmp(argv[i],"--next-bind") == 0 && i+1 < argc )
			cfg->next_bind = argv[++i];
		else if ( strcmp(argv[i],"--next-host") == 0 && i+1 < argc )
			cfg->next_host = argv[++i];
		else if ( strcmp(argv[i],"--next-port") == 0 && i+1 < argc )
			cfg->next_port = atoi(argv[++i]);
		else if ( strcmp(argv[i],"--socket-buffer-mib") == 0 && i+1 < argc )
			cfg->socket_buffer_mib = atoi(argv[++i]);
	}
	return(0);
}

static void print_result(config_t *cfg,const char *role,int32_t items,uint64_t bytes,double elapsed,double active)
{
	double items_per_s,payload_GBps;
	if ( active <= 0.0 )
		active = elapsed;
	items_per_s = (active > 0.0) ? ((double)items / active) : 0.0;
	payload_GBps = (active > 0.0) ? ((double)bytes / active / 1000000000.0) : 0.0;
	printf("PIPELINE_RESULT {\"active_s\":%.9f,\"elapsed_s\":%.9f,\"items\":%d,\"items_per_s\":%.9f,\"payload_GBps\":%.9f,\"payload_bytes\":%llu,\"rank\":%d,\"role\":\"%s\",\"stage_ms\":%.6f,\"total_payload_bytes\":%llu,\"world_size\":%d}\n",active,elapsed,items,items_per_s,payload_GBps,(unsigned long long)cfg->payload_bytes,cfg->rank,role,cfg->stage_ms,(unsigned long long)bytes,cfg->world_size);
	fflush(stdout);
}

static int32_t run_sequential(config_t *cfg)
{
	double start,elapsed;
	int32_t i,j;
	start = now_sec();
	for (i=0; i<cfg->items; i++)
		for (j=0; j<cfg->world_size; j++)
			sleep_stage(cfg->stage_ms);
	elapsed = (now_sec() - start);
	print_result(cfg,"sequential",cfg->items,0,elapsed,elapsed);
	return(0);
}

static int32_t run_rank0(config_t *cfg,uint8_t *payload,int32_t next_fd)
{
	double start,first,end;
	int32_t i;
	start = now_sec();
	first = 0.0;
	for (i=0; i<cfg->items; i++)
	{
		if ( i == 0 )
			first = now_sec();
		sleep_stage(cfg->stage_ms);
		if ( send_header(next_fd,(uint64_t)i,cfg->payload_bytes) < 0 )
			return(-1);
		if ( send_all(next_fd,payload,cfg->payload_bytes) < 0 )
			return(-2);
	}
	send_header(next_fd,(uint64_t)cfg->items,0);
	end = now_sec();
	print_result(cfg,"rank",cfg->items,(cfg->payload_bytes * (uint64_t)cfg->items),(end - start),(end - first));
	return(0);
}

static int32_t run_rank_mid(config_t *cfg,uint8_t *payload,int32_t prev_fd,int32_t next_fd)
{
	double start,first,end;
	uint64_t seq,len;
	int32_t items;
	start = now_sec();
	first = 0.0;
	items = 0;
	while ( recv_header(prev_fd,&seq,&len) == 0 )
	{
		if ( len == 0 )
		{
			if ( next_fd >= 0 )
				send_header(next_fd,seq,0);
			break;
		}
		if ( items == 0 )
			first = now_sec();
		if ( recv_all(prev_fd,payload,len) < 0 )
			return(-1);
		sleep_stage(cfg->stage_ms);
		if ( next_fd >= 0 )
		{
			if ( send_header(next_fd,seq,cfg->payload_bytes) < 0 )
				return(-2);
			if ( send_all(next_fd,payload,cfg->payload_bytes) < 0 )
				return(-3);
		}
		items++;
	}
	end = now_sec();
	print_result(cfg,"rank",items,(cfg->payload_bytes * (uint64_t)items),(end - start),(end - first));
	return(0);
}

static int32_t run_rank(config_t *cfg)
{
	uint8_t *payload;
	int32_t prev_fd,next_fd,err;
	payload = calloc(1,(size_t)cfg->payload_bytes);
	if ( payload == 0 )
		return(-1);
	prev_fd = -1;
	next_fd = -1;
	if ( cfg->rank > 0 )
		prev_fd = accept_prev(cfg->listen_bind,cfg->listen_port,cfg->socket_buffer_mib);
	if ( cfg->rank > 0 && prev_fd < 0 )
		return(-2);
	if ( cfg->rank < (cfg->world_size - 1) )
		next_fd = connect_next(cfg->next_host,cfg->next_port,cfg->next_bind,cfg->socket_buffer_mib);
	if ( cfg->rank < (cfg->world_size - 1) && next_fd < 0 )
		return(-3);
	if ( cfg->rank == 0 )
		err = run_rank0(cfg,payload,next_fd);
	else
		err = run_rank_mid(cfg,payload,prev_fd,next_fd);
	if ( prev_fd >= 0 )
		close(prev_fd);
	if ( next_fd >= 0 )
		close(next_fd);
	free(payload);
	return(err);
}

int main(int argc,char **argv)
{
	config_t cfg;
	parse_args(&cfg,argc,argv);
	if ( cfg.role == 1 )
		return(run_sequential(&cfg));
	return(run_rank(&cfg));
}
