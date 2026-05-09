#include <stdint.h>
#include <stdio.h>

#include <cuda_runtime.h>

#include "cuda_probe_util.h"

__global__ void graph_smoke_write_u32(uint32_t *out,uint32_t v)
{
	if ( blockIdx.x != 0 )
		return;
	if ( ((int32_t)threadIdx.x) == 0 )
		out[0] = v;
}

int main(int argc,char **argv)
{
	uint32_t *d_out = 0,h_out = 0;
	cudaStream_t stream = 0;
	cudaGraph_t graph = 0;
	cudaGraphExec_t graph_exec = 0;
	int32_t rc = 0;
	(void)argc;
	(void)argv;
	cuda_probe_print_versions();
	rc = cuda_probe_check(cudaStreamCreate(&stream),-1,"cudaStreamCreate");
	if ( rc != 0 )
		return(rc);
	rc = cuda_probe_check(cudaMalloc((void **)&d_out,(size_t)sizeof(uint32_t)),-2,"cudaMalloc(d_out)");
	if ( rc != 0 )
	{
		cudaStreamDestroy(stream);
		return(rc);
	}
	rc = cuda_probe_check(cudaMemsetAsync(d_out,0,(size_t)sizeof(uint32_t),stream),-3,"cudaMemsetAsync(d_out)");
	if ( rc != 0 )
	{
		cudaFree(d_out);
		cudaStreamDestroy(stream);
		return(rc);
	}
	rc = cuda_probe_check(cudaStreamBeginCapture(stream,cudaStreamCaptureModeGlobal),-4,"cudaStreamBeginCapture");
	if ( rc != 0 )
	{
		cudaFree(d_out);
		cudaStreamDestroy(stream);
		return(rc);
	}
	graph_smoke_write_u32<<<1,32,0,stream>>>(d_out,0x11111111u);
	rc = cuda_probe_check(cudaGetLastError(),-5,"kernel launch (capture 1)");
	if ( rc != 0 )
	{
		cudaStreamEndCapture(stream,&graph);
		if ( graph != 0 )
			cudaGraphDestroy(graph);
		cudaFree(d_out);
		cudaStreamDestroy(stream);
		return(rc);
	}
	graph_smoke_write_u32<<<1,32,0,stream>>>(d_out,0x22222222u);
	rc = cuda_probe_check(cudaGetLastError(),-6,"kernel launch (capture 2)");
	if ( rc != 0 )
	{
		cudaStreamEndCapture(stream,&graph);
		if ( graph != 0 )
			cudaGraphDestroy(graph);
		cudaFree(d_out);
		cudaStreamDestroy(stream);
		return(rc);
	}
	rc = cuda_probe_check(cudaStreamEndCapture(stream,&graph),-7,"cudaStreamEndCapture");
	if ( rc != 0 || graph == 0 )
	{
		if ( graph != 0 )
			cudaGraphDestroy(graph);
		cudaFree(d_out);
		cudaStreamDestroy(stream);
		if ( rc != 0 )
			return(rc);
		return(-8);
	}
	rc = cuda_probe_check(cudaGraphInstantiateWithFlags(&graph_exec,graph,0ULL),-9,"cudaGraphInstantiateWithFlags");
	if ( rc != 0 )
	{
		cudaGraphDestroy(graph);
		cudaFree(d_out);
		cudaStreamDestroy(stream);
		return(rc);
	}
	cudaGraphDestroy(graph);
	rc = cuda_probe_check(cudaGraphLaunch(graph_exec,stream),-10,"cudaGraphLaunch");
	if ( rc != 0 )
	{
		cudaGraphExecDestroy(graph_exec);
		cudaFree(d_out);
		cudaStreamDestroy(stream);
		return(rc);
	}
	rc = cuda_probe_check(cudaStreamSynchronize(stream),-11,"cudaStreamSynchronize");
	if ( rc != 0 )
	{
		cudaGraphExecDestroy(graph_exec);
		cudaFree(d_out);
		cudaStreamDestroy(stream);
		return(rc);
	}
	rc = cuda_probe_check(cudaMemcpy(&h_out,d_out,(size_t)sizeof(uint32_t),cudaMemcpyDeviceToHost),-12,"cudaMemcpy(D2H)");
	if ( rc != 0 )
	{
		cudaGraphExecDestroy(graph_exec);
		cudaFree(d_out);
		cudaStreamDestroy(stream);
		return(rc);
	}
	cudaGraphExecDestroy(graph_exec);
	cudaFree(d_out);
	cudaStreamDestroy(stream);
	printf("cuda_graph_smoke out=%08x\n",h_out);
	if ( h_out != 0x22222222u )
		return(-13);
	return(0);
}
