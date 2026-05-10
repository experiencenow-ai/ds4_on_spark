#include <stdint.h>
#include <stdio.h>

#include <cuda_fp4.h>
#include <cuda_fp8.h>
#include <cuda_runtime.h>
#include <cublasLt.h>

#include "cuda_probe_util.h"

static const char *cublaslt_status_str(cublasStatus_t s)
{
	switch (s)
	{
		case CUBLAS_STATUS_SUCCESS: return("CUBLAS_STATUS_SUCCESS");
		case CUBLAS_STATUS_NOT_INITIALIZED: return("CUBLAS_STATUS_NOT_INITIALIZED");
		case CUBLAS_STATUS_ALLOC_FAILED: return("CUBLAS_STATUS_ALLOC_FAILED");
		case CUBLAS_STATUS_INVALID_VALUE: return("CUBLAS_STATUS_INVALID_VALUE");
		case CUBLAS_STATUS_ARCH_MISMATCH: return("CUBLAS_STATUS_ARCH_MISMATCH");
		case CUBLAS_STATUS_MAPPING_ERROR: return("CUBLAS_STATUS_MAPPING_ERROR");
		case CUBLAS_STATUS_EXECUTION_FAILED: return("CUBLAS_STATUS_EXECUTION_FAILED");
		case CUBLAS_STATUS_INTERNAL_ERROR: return("CUBLAS_STATUS_INTERNAL_ERROR");
		case CUBLAS_STATUS_NOT_SUPPORTED: return("CUBLAS_STATUS_NOT_SUPPORTED");
		default: return("CUBLAS_STATUS_UNKNOWN");
	}
}

static const char *dtype_str(cudaDataType t)
{
	switch (t)
	{
		case CUDA_R_16F: return("CUDA_R_16F");
		case CUDA_R_16BF: return("CUDA_R_16BF");
		case CUDA_R_32F: return("CUDA_R_32F");
		case CUDA_R_4F_E2M1: return("CUDA_R_4F_E2M1");
		default: return("CUDA_R_<unknown>");
	}
}

static const char *compute_str(cublasComputeType_t t)
{
	switch (t)
	{
		case CUBLAS_COMPUTE_32F: return("CUBLAS_COMPUTE_32F");
		case CUBLAS_COMPUTE_32F_FAST_TF32: return("CUBLAS_COMPUTE_32F_FAST_TF32");
		default: return("CUBLAS_COMPUTE_<unknown>");
	}
}

static __global__ void fp4_fill_identity_ones_e2m1(uint8_t *a,uint8_t *b,int32_t m,int32_t n,int32_t k)
{
	int32_t idx = (int32_t)((int32_t)blockIdx.x * (int32_t)blockDim.x + (int32_t)threadIdx.x);
	int32_t a_elems = (k * m),b_elems = (k * n),max_elems = (a_elems > b_elems) ? a_elems : b_elems;
	if ( a == 0 || b == 0 )
		return;
	if ( idx >= max_elems )
		return;
	if ( idx < a_elems )
	{
		int32_t row = (idx % k),col = (idx / k);
		float v = (row == col) ? 1.0f : 0.0f;
		a[idx] = (uint8_t)__nv_cvt_float_to_fp4(v,__NV_E2M1,cudaRoundNearest);
	}
	if ( idx < b_elems )
		b[idx] = (uint8_t)__nv_cvt_float_to_fp4(1.0f,__NV_E2M1,cudaRoundNearest);
}

static int32_t run_cublaslt_fp4_e2m1_try(uint8_t *d_a,uint8_t *d_b,void *d_d,void *d_ws,size_t ws_bytes,uint8_t *d_a_scale,uint8_t *d_b_scale,int32_t m,int32_t n,int32_t k,cudaDataType d_type,cublasComputeType_t compute_type,int32_t *out_got,cublasStatus_t *out_status)
{
	const float alpha = 1.0f,beta = 0.0f;
	cublasLtHandle_t lt = 0;
	cublasLtMatmulDesc_t op = 0;
	cublasLtMatrixLayout_t a_desc = 0,b_desc = 0,d_desc = 0;
	cublasLtMatmulPreference_t pref = 0;
	cublasLtMatmulHeuristicResult_t heur[8];
	int32_t got = 0,rc = 0,i = 0;
	cublasOperation_t trans_a = CUBLAS_OP_T,trans_b = CUBLAS_OP_N;
	int32_t a_scale_mode = (int32_t)CUBLASLT_MATMUL_MATRIX_SCALE_VEC16_UE4M3;
	int32_t b_scale_mode = (int32_t)CUBLASLT_MATMUL_MATRIX_SCALE_VEC16_UE4M3;
	void *a_scale_ptr = 0,*b_scale_ptr = 0;
	cublasStatus_t st = CUBLAS_STATUS_SUCCESS;
	if ( out_got != 0 )
		*out_got = 0;
	if ( out_status != 0 )
		*out_status = CUBLAS_STATUS_SUCCESS;
	if ( d_a == 0 || d_b == 0 || d_d == 0 || d_ws == 0 || d_a_scale == 0 || d_b_scale == 0 )
		return(-2001);
	a_scale_ptr = d_a_scale;
	b_scale_ptr = d_b_scale;
	do
	{
		st = cublasLtCreate(&lt);
		if ( st != CUBLAS_STATUS_SUCCESS ) { rc = -20; break; }
		st = cublasLtMatmulDescCreate(&op,compute_type,CUDA_R_32F);
		if ( st != CUBLAS_STATUS_SUCCESS ) { rc = -21; break; }
		st = cublasLtMatmulDescSetAttribute(op,CUBLASLT_MATMUL_DESC_TRANSA,&trans_a,(size_t)sizeof(trans_a));
		if ( st != CUBLAS_STATUS_SUCCESS ) { rc = -22; break; }
		st = cublasLtMatmulDescSetAttribute(op,CUBLASLT_MATMUL_DESC_TRANSB,&trans_b,(size_t)sizeof(trans_b));
		if ( st != CUBLAS_STATUS_SUCCESS ) { rc = -23; break; }
		st = cublasLtMatmulDescSetAttribute(op,CUBLASLT_MATMUL_DESC_A_SCALE_MODE,&a_scale_mode,(size_t)sizeof(a_scale_mode));
		if ( st != CUBLAS_STATUS_SUCCESS ) { rc = -24; break; }
		st = cublasLtMatmulDescSetAttribute(op,CUBLASLT_MATMUL_DESC_B_SCALE_MODE,&b_scale_mode,(size_t)sizeof(b_scale_mode));
		if ( st != CUBLAS_STATUS_SUCCESS ) { rc = -25; break; }
		st = cublasLtMatmulDescSetAttribute(op,CUBLASLT_MATMUL_DESC_A_SCALE_POINTER,&a_scale_ptr,(size_t)sizeof(a_scale_ptr));
		if ( st != CUBLAS_STATUS_SUCCESS ) { rc = -26; break; }
		st = cublasLtMatmulDescSetAttribute(op,CUBLASLT_MATMUL_DESC_B_SCALE_POINTER,&b_scale_ptr,(size_t)sizeof(b_scale_ptr));
		if ( st != CUBLAS_STATUS_SUCCESS ) { rc = -27; break; }
		st = cublasLtMatrixLayoutCreate(&a_desc,CUDA_R_4F_E2M1,k,m,k);
		if ( st != CUBLAS_STATUS_SUCCESS ) { rc = -28; break; }
		st = cublasLtMatrixLayoutCreate(&b_desc,CUDA_R_4F_E2M1,k,n,k);
		if ( st != CUBLAS_STATUS_SUCCESS ) { rc = -29; break; }
		st = cublasLtMatrixLayoutCreate(&d_desc,d_type,m,n,m);
		if ( st != CUBLAS_STATUS_SUCCESS ) { rc = -30; break; }
		st = cublasLtMatmulPreferenceCreate(&pref);
		if ( st != CUBLAS_STATUS_SUCCESS ) { rc = -31; break; }
		st = cublasLtMatmulPreferenceSetAttribute(pref,CUBLASLT_MATMUL_PREF_MAX_WORKSPACE_BYTES,&ws_bytes,(size_t)sizeof(ws_bytes));
		if ( st != CUBLAS_STATUS_SUCCESS ) { rc = -32; break; }
		st = cublasLtMatmulAlgoGetHeuristic(lt,op,a_desc,b_desc,d_desc,d_desc,pref,(int32_t)(sizeof(heur) / sizeof(heur[0])),heur,&got);
		if ( out_got != 0 )
			*out_got = got;
		if ( out_status != 0 )
			*out_status = st;
		if ( st != CUBLAS_STATUS_SUCCESS )
		{
			rc = -33;
			break;
		}
		if ( got <= 0 )
		{
			rc = -34;
			break;
		}
		rc = -35;
		for (i=0; i<got; i++)
		{
			st = cublasLtMatmul(lt,op,&alpha,d_a,a_desc,d_b,b_desc,&beta,d_d,d_desc,d_d,d_desc,&heur[i].algo,d_ws,ws_bytes,0);
			if ( st == CUBLAS_STATUS_SUCCESS )
			{
				rc = 0;
				break;
			}
		}
		if ( rc != 0 && out_status != 0 )
			*out_status = st;
	} while (0);
	if ( pref != 0 )
		cublasLtMatmulPreferenceDestroy(pref);
	if ( d_desc != 0 )
		cublasLtMatrixLayoutDestroy(d_desc);
	if ( b_desc != 0 )
		cublasLtMatrixLayoutDestroy(b_desc);
	if ( a_desc != 0 )
		cublasLtMatrixLayoutDestroy(a_desc);
	if ( op != 0 )
		cublasLtMatmulDescDestroy(op);
	if ( lt != 0 )
		cublasLtDestroy(lt);
	return(rc);
}

int main(int argc,char **argv)
{
	static const int32_t max_dim = 64;
	static const int32_t a_scale_elems = 512,b_scale_elems = 512;
	uint8_t *d_a = 0,*d_b = 0,*d_a_scale = 0,*d_b_scale = 0;
	uint8_t h_a_scale[a_scale_elems],h_b_scale[b_scale_elems];
	uint8_t scale_one = 0;
	void *d_d = 0;
	void *d_ws = 0;
	size_t ws_bytes_list[] =
	{
		(size_t)(1u<<20),
		(size_t)(16u<<20),
	};
	cudaDataType d_types[] = { CUDA_R_16BF,CUDA_R_16F,CUDA_R_32F };
	cublasComputeType_t compute_types[] = { CUBLAS_COMPUTE_32F,CUBLAS_COMPUTE_32F_FAST_TF32 };
	int32_t rc = 0,threads = 256,blocks = 1,elems = 0,w = 0,dt = 0,ct = 0,got = 0;
	int32_t rc_case = 0;
	int32_t i = 0,outer = 0,inner = 0,inner_dim = ((max_dim + 15) / 16),off = 0;
	size_t ws_bytes = 0,d_bytes = 0;
	cublasStatus_t st = CUBLAS_STATUS_SUCCESS;
	(void)argc;
	(void)argv;
	cuda_probe_print_versions();
	printf("cublasLtGetVersion=%zu cublasLtGetCudartVersion=%zu\n",cublasLtGetVersion(),cublasLtGetCudartVersion());
	do
	{
		rc = cuda_probe_check(cudaMalloc((void **)&d_a,(size_t)max_dim * (size_t)max_dim),-1,"cudaMalloc(A fp4)");
		if ( rc != 0 )
			break;
		rc = cuda_probe_check(cudaMalloc((void **)&d_b,(size_t)max_dim * (size_t)max_dim),-2,"cudaMalloc(B fp4)");
		if ( rc != 0 )
			break;
		rc = cuda_probe_check(cudaMalloc((void **)&d_a_scale,(size_t)a_scale_elems),-3,"cudaMalloc(A scale)");
		if ( rc != 0 )
			break;
		rc = cuda_probe_check(cudaMalloc((void **)&d_b_scale,(size_t)b_scale_elems),-4,"cudaMalloc(B scale)");
		if ( rc != 0 )
			break;
		elems = (max_dim * max_dim);
		blocks = ((elems + threads - 1) / threads);
		scale_one = (uint8_t)__nv_cvt_float_to_fp8(1.0f,__NV_SATFINITE,__NV_E4M3);
		for (i=0; i<a_scale_elems; i++)
		{
			h_a_scale[i] = 0;
			h_b_scale[i] = 0;
		}
		for (outer=0; outer<max_dim; outer++)
		{
			for (inner=0; inner<inner_dim; inner++)
			{
				off = ((outer % 32) * 16) + ((outer / 32) * 4) + inner;
				h_a_scale[off] = scale_one;
				h_b_scale[off] = scale_one;
			}
		}
		rc = cuda_probe_check(cudaMemcpy(d_a_scale,h_a_scale,(size_t)a_scale_elems,cudaMemcpyHostToDevice),-50,"cudaMemcpy(H2D A scale)");
		if ( rc != 0 )
			break;
		rc = cuda_probe_check(cudaMemcpy(d_b_scale,h_b_scale,(size_t)b_scale_elems,cudaMemcpyHostToDevice),-51,"cudaMemcpy(H2D B scale)");
		if ( rc != 0 )
			break;
		fp4_fill_identity_ones_e2m1<<<blocks,threads>>>(d_a,d_b,max_dim,max_dim,max_dim);
		rc = cuda_probe_check(cudaGetLastError(),-5,"fp4_fill_identity_ones_e2m1 launch");
		if ( rc != 0 )
			break;
		for (w=0; w<(int32_t)(sizeof(ws_bytes_list) / sizeof(ws_bytes_list[0])); w++)
		{
			ws_bytes = ws_bytes_list[w];
			if ( d_ws != 0 )
				cudaFree(d_ws);
			d_ws = 0;
			rc = cuda_probe_check(cudaMalloc(&d_ws,ws_bytes),-6,"cudaMalloc(workspace)");
			if ( rc != 0 )
				break;
			for (dt=0; dt<(int32_t)(sizeof(d_types) / sizeof(d_types[0])); dt++)
			{
				for (ct=0; ct<(int32_t)(sizeof(compute_types) / sizeof(compute_types[0])); ct++)
				{
					cudaDataType d_type = d_types[dt];
					cublasComputeType_t compute_type = compute_types[ct];
					if ( d_d != 0 )
						cudaFree(d_d);
					d_d = 0;
					d_bytes = (size_t)max_dim * (size_t)max_dim;
					if ( d_type == CUDA_R_16BF || d_type == CUDA_R_16F )
						d_bytes *= (size_t)sizeof(uint16_t);
					else if ( d_type == CUDA_R_32F )
						d_bytes *= (size_t)sizeof(float);
					else
						d_bytes = 0;
					rc = cuda_probe_check(cudaMalloc(&d_d,d_bytes),-7,"cudaMalloc(D)");
					if ( rc != 0 )
						break;
					rc = cuda_probe_check(cudaMemset(d_d,0,d_bytes),-8,"cudaMemset(D)");
					if ( rc != 0 )
						break;
					got = 0;
					st = CUBLAS_STATUS_SUCCESS;
					rc_case = run_cublaslt_fp4_e2m1_try(d_a,d_b,d_d,d_ws,ws_bytes,d_a_scale,d_b_scale,max_dim,max_dim,max_dim,d_type,compute_type,&got,&st);
					printf("fp4_e2m1 sweep ws_bytes=%zu D=%s compute=%s heuristic=%s got=%d rc=%d\n",ws_bytes,dtype_str(d_type),compute_str(compute_type),cublaslt_status_str(st),got,rc_case);
					if ( rc_case == 0 )
					{
						rc = cuda_probe_check(cudaDeviceSynchronize(),-9,"cudaDeviceSynchronize");
						if ( rc != 0 )
							break;
						printf("fp4_e2m1 sweep: SUCCESS\n");
						return(0);
					}
				}
			}
			if ( rc != 0 )
				break;
		}
	} while (0);
	if ( d_ws != 0 )
		cudaFree(d_ws);
	if ( d_d != 0 )
		cudaFree(d_d);
	if ( d_b_scale != 0 )
		cudaFree(d_b_scale);
	if ( d_a_scale != 0 )
		cudaFree(d_a_scale);
	if ( d_b != 0 )
		cudaFree(d_b);
	if ( d_a != 0 )
		cudaFree(d_a);
	if ( rc != 0 )
		return(rc);
	printf("fp4_e2m1 sweep: no supported configuration found\n");
	return(-41);
}
