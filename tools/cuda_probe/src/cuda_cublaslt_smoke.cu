#include <stdint.h>
#include <stdio.h>

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

static int32_t cublaslt_probe_check(cublasStatus_t s,int32_t code,const char *callsite)
{
	if ( s == CUBLAS_STATUS_SUCCESS )
		return(0);
	fprintf(stderr,"cuBLASLt error %s: %s\n",callsite,cublaslt_status_str(s));
	return(code);
}

static int32_t fill_identity_f32(float *a,int32_t m,int32_t n)
{
	int32_t i,j;
	if ( a == 0 )
		return(-1001);
	for (j=0; j<n; j++)
	{
		for (i=0; i<m; i++)
			a[i + (j * m)] = (i == j) ? 1.0f : 0.0f;
	}
	return(0);
}

static int32_t fill_seq_f32(float *a,int32_t m,int32_t n)
{
	int32_t i,j;
	float v = 0.0f;
	if ( a == 0 )
		return(-1002);
	for (j=0; j<n; j++)
	{
		for (i=0; i<m; i++)
		{
			a[i + (j * m)] = v;
			v += 1.0f;
		}
	}
	return(0);
}

static int32_t max_abs_err_f32(float *a,float *b,int32_t m,int32_t n,float *out)
{
	int32_t i,j;
	float e = 0.0f;
	if ( a == 0 || b == 0 || out == 0 )
		return(-1003);
	for (j=0; j<n; j++)
	{
		for (i=0; i<m; i++)
		{
			float d = a[i + (j * m)] - b[i + (j * m)];
			if ( d < 0.0f )
				d = -d;
			if ( d > e )
				e = d;
		}
	}
	*out = e;
	return(0);
}

static int32_t run_cublaslt_sgemm_smoke(float *d_a,float *d_b,float *d_c,void *d_ws,size_t ws_bytes,int32_t m,int32_t n,int32_t k)
{
	const float alpha = 1.0f,beta = 0.0f;
	cublasLtHandle_t lt = 0;
	cublasLtMatmulDesc_t op = 0;
	cublasLtMatrixLayout_t a_desc = 0,b_desc = 0,c_desc = 0;
	cublasLtMatmulPreference_t pref = 0;
	cublasLtMatmulHeuristicResult_t heur;
	int32_t got = 0,rc = 0;
	cublasOperation_t trans = CUBLAS_OP_N;
	cublasStatus_t st;
	if ( d_a == 0 || d_b == 0 || d_c == 0 || d_ws == 0 )
		return(-2001);
	do
	{
		st = cublasLtCreate(&lt);
		rc = cublaslt_probe_check(st,-20,"cublasLtCreate");
		if ( rc != 0 )
			break;
		st = cublasLtMatmulDescCreate(&op,CUBLAS_COMPUTE_32F,CUDA_R_32F);
		rc = cublaslt_probe_check(st,-21,"cublasLtMatmulDescCreate");
		if ( rc != 0 )
			break;
		st = cublasLtMatmulDescSetAttribute(op,CUBLASLT_MATMUL_DESC_TRANSA,&trans,(size_t)sizeof(trans));
		rc = cublaslt_probe_check(st,-22,"cublasLtMatmulDescSetAttribute(TRANSA)");
		if ( rc != 0 )
			break;
		st = cublasLtMatmulDescSetAttribute(op,CUBLASLT_MATMUL_DESC_TRANSB,&trans,(size_t)sizeof(trans));
		rc = cublaslt_probe_check(st,-23,"cublasLtMatmulDescSetAttribute(TRANSB)");
		if ( rc != 0 )
			break;
		st = cublasLtMatrixLayoutCreate(&a_desc,CUDA_R_32F,m,k,m);
		rc = cublaslt_probe_check(st,-24,"cublasLtMatrixLayoutCreate(A)");
		if ( rc != 0 )
			break;
		st = cublasLtMatrixLayoutCreate(&b_desc,CUDA_R_32F,k,n,k);
		rc = cublaslt_probe_check(st,-25,"cublasLtMatrixLayoutCreate(B)");
		if ( rc != 0 )
			break;
		st = cublasLtMatrixLayoutCreate(&c_desc,CUDA_R_32F,m,n,m);
		rc = cublaslt_probe_check(st,-26,"cublasLtMatrixLayoutCreate(C)");
		if ( rc != 0 )
			break;
		st = cublasLtMatmulPreferenceCreate(&pref);
		rc = cublaslt_probe_check(st,-27,"cublasLtMatmulPreferenceCreate");
		if ( rc != 0 )
			break;
		st = cublasLtMatmulPreferenceSetAttribute(pref,CUBLASLT_MATMUL_PREF_MAX_WORKSPACE_BYTES,&ws_bytes,(size_t)sizeof(ws_bytes));
		rc = cublaslt_probe_check(st,-28,"cublasLtMatmulPreferenceSetAttribute(MAX_WORKSPACE_BYTES)");
		if ( rc != 0 )
			break;
		st = cublasLtMatmulAlgoGetHeuristic(lt,op,a_desc,b_desc,c_desc,c_desc,pref,1,&heur,&got);
		rc = cublaslt_probe_check(st,-29,"cublasLtMatmulAlgoGetHeuristic");
		if ( rc != 0 )
			break;
		if ( got <= 0 )
		{
			rc = -30;
			break;
		}
		st = cublasLtMatmul(lt,op,&alpha,d_a,a_desc,d_b,b_desc,&beta,d_c,c_desc,d_c,c_desc,&heur.algo,d_ws,ws_bytes,0);
		rc = cublaslt_probe_check(st,-31,"cublasLtMatmul");
		if ( rc != 0 )
			break;
	} while (0);
	if ( pref != 0 )
		cublasLtMatmulPreferenceDestroy(pref);
	if ( c_desc != 0 )
		cublasLtMatrixLayoutDestroy(c_desc);
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
	static const int32_t m = 16,n = 16,k = 16;
	float h_a[m * k],h_b[k * n],h_c[m * n];
	float *d_a = 0,*d_b = 0,*d_c = 0;
	void *d_ws = 0;
	size_t ws_bytes = (size_t)(1u<<20);
	float max_err = 0.0f;
	int32_t rc = 0;
	(void)argc;
	(void)argv;
	cuda_probe_print_versions();
	printf("cublasLtGetVersion=%zu cublasLtGetCudartVersion=%zu\n",cublasLtGetVersion(),cublasLtGetCudartVersion());
	do
	{
		rc = fill_identity_f32(h_a,m,k);
		if ( rc != 0 )
			break;
		rc = fill_seq_f32(h_b,k,n);
		if ( rc != 0 )
			break;
		rc = cuda_probe_check(cudaMalloc((void **)&d_a,(size_t)m * (size_t)k * (size_t)sizeof(float)),-2,"cudaMalloc(A)");
		if ( rc != 0 )
			break;
		rc = cuda_probe_check(cudaMalloc((void **)&d_b,(size_t)k * (size_t)n * (size_t)sizeof(float)),-3,"cudaMalloc(B)");
		if ( rc != 0 )
			break;
		rc = cuda_probe_check(cudaMalloc((void **)&d_c,(size_t)m * (size_t)n * (size_t)sizeof(float)),-4,"cudaMalloc(C)");
		if ( rc != 0 )
			break;
		rc = cuda_probe_check(cudaMalloc(&d_ws,ws_bytes),-5,"cudaMalloc(workspace)");
		if ( rc != 0 )
			break;
		rc = cuda_probe_check(cudaMemcpy(d_a,h_a,(size_t)m * (size_t)k * (size_t)sizeof(float),cudaMemcpyHostToDevice),-6,"cudaMemcpy(H2D A)");
		if ( rc != 0 )
			break;
		rc = cuda_probe_check(cudaMemcpy(d_b,h_b,(size_t)k * (size_t)n * (size_t)sizeof(float),cudaMemcpyHostToDevice),-7,"cudaMemcpy(H2D B)");
		if ( rc != 0 )
			break;
		rc = cuda_probe_check(cudaMemset(d_c,0,(size_t)m * (size_t)n * (size_t)sizeof(float)),-8,"cudaMemset(C)");
		if ( rc != 0 )
			break;
		rc = run_cublaslt_sgemm_smoke(d_a,d_b,d_c,d_ws,ws_bytes,m,n,k);
		if ( rc != 0 )
			break;
		rc = cuda_probe_check(cudaDeviceSynchronize(),-32,"cudaDeviceSynchronize");
		if ( rc != 0 )
			break;
		rc = cuda_probe_check(cudaMemcpy(h_c,d_c,(size_t)m * (size_t)n * (size_t)sizeof(float),cudaMemcpyDeviceToHost),-33,"cudaMemcpy(D2H C)");
		if ( rc != 0 )
			break;
		rc = max_abs_err_f32(h_c,h_b,m,n,&max_err);
		if ( rc != 0 )
			break;
	} while (0);
	if ( d_ws != 0 )
		cudaFree(d_ws);
	if ( d_c != 0 )
		cudaFree(d_c);
	if ( d_b != 0 )
		cudaFree(d_b);
	if ( d_a != 0 )
		cudaFree(d_a);
	if ( rc != 0 )
		return(rc);
	printf("cuBLASLt sgemm smoke max_abs_err=%g\n",max_err);
	if ( max_err > 1.0e-4f )
		return(-40);
	return(0);
}
