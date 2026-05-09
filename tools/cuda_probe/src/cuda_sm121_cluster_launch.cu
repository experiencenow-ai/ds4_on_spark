#include <stdint.h>
#include <stdio.h>

#include <cooperative_groups.h>
#include <cuda_runtime.h>

#include "cuda_probe_util.h"

__global__ void cluster_block_rank_u32(uint32_t *out)
{
	cooperative_groups::cluster_group cluster = cooperative_groups::this_cluster();
	uint32_t brank = (uint32_t)cluster.block_rank();
	if ( ((int32_t)threadIdx.x) == 0 )
		out[(int32_t)blockIdx.x] = brank;
}

int main(int argc,char **argv)
{
	uint32_t *d_out = 0,h_out[2] = {0,0};
	int32_t cluster_supported = 0,max_cluster_size = 0,max_active_clusters = 0;
	int32_t rc = 0;
	cudaLaunchAttribute attr = {};
	cudaLaunchConfig_t config = {};
	void *args[1];
	(void)argc;
	(void)argv;
	cuda_probe_print_versions();
	rc = cuda_probe_check(cudaDeviceGetAttribute(&cluster_supported,cudaDevAttrClusterLaunch,0),-1,"cudaDeviceGetAttribute(cudaDevAttrClusterLaunch)");
	if ( rc != 0 )
		return(rc);
	printf("cluster_launch_supported=%d\n",cluster_supported);
	if ( cluster_supported == 0 )
		return(0);
	rc = cuda_probe_check(cudaMalloc((void **)&d_out,(size_t)(2 * (int32_t)sizeof(uint32_t))),-2,"cudaMalloc(d_out)");
	if ( rc != 0 )
		return(rc);
	rc = cuda_probe_check(cudaMemset(d_out,0,(size_t)(2 * (int32_t)sizeof(uint32_t))),-3,"cudaMemset(d_out)");
	if ( rc != 0 )
	{
		cudaFree(d_out);
		return(rc);
	}
	config.gridDim = dim3(2,1,1);
	config.blockDim = dim3(32,1,1);
	config.dynamicSmemBytes = 0;
	config.stream = 0;
	attr.id = cudaLaunchAttributeClusterDimension;
	attr.val.clusterDim.x = 2;
	attr.val.clusterDim.y = 1;
	attr.val.clusterDim.z = 1;
	config.attrs = &attr;
	config.numAttrs = 1;
	rc = cuda_probe_check(cudaOccupancyMaxPotentialClusterSize(&max_cluster_size,(const void *)cluster_block_rank_u32,&config),-4,"cudaOccupancyMaxPotentialClusterSize");
	if ( rc != 0 )
	{
		cudaFree(d_out);
		return(rc);
	}
	printf("max_cluster_size_portable=%d\n",max_cluster_size);
	rc = cuda_probe_check(cudaOccupancyMaxActiveClusters(&max_active_clusters,(const void *)cluster_block_rank_u32,&config),-5,"cudaOccupancyMaxActiveClusters");
	if ( rc != 0 )
	{
		cudaFree(d_out);
		return(rc);
	}
	printf("max_active_clusters_for_2x1x1=%d\n",max_active_clusters);
	args[0] = &d_out;
	rc = cuda_probe_check(cudaLaunchKernelExC(&config,(const void *)cluster_block_rank_u32,args),-6,"cudaLaunchKernelExC(clusterDim=2x1x1)");
	if ( rc != 0 )
	{
		cudaFree(d_out);
		return(rc);
	}
	rc = cuda_probe_check(cudaDeviceSynchronize(),-7,"cudaDeviceSynchronize");
	if ( rc != 0 )
	{
		cudaFree(d_out);
		return(rc);
	}
	rc = cuda_probe_check(cudaMemcpy(h_out,d_out,(size_t)(2 * (int32_t)sizeof(uint32_t)),cudaMemcpyDeviceToHost),-8,"cudaMemcpy(D2H)");
	if ( rc != 0 )
	{
		cudaFree(d_out);
		return(rc);
	}
	cudaFree(d_out);
	printf("cluster_block_rank out[0]=%u out[1]=%u\n",h_out[0],h_out[1]);
	if ( h_out[0] != 0 || h_out[1] != 1 )
		return(-9);
	return(0);
}

