#include <stdint.h>
#include <stdio.h>

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

static int32_t cublaslt_probe_check(cublasStatus_t s,int32_t code,const char *callsite)
{
	if ( s == CUBLAS_STATUS_SUCCESS )
		return(0);
	fprintf(stderr,"cuBLASLt error %s: %s\n",callsite,cublaslt_status_str(s));
	return(code);
}

static __global__ void fp8_fill_identity_ones_e4m3(uint8_t *a,uint8_t *b,int32_t m,int32_t n,int32_t k)
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
		a[idx] = (uint8_t)__nv_cvt_float_to_fp8(v,__NV_SATFINITE,__NV_E4M3);
	}
	if ( idx < b_elems )
		b[idx] = (uint8_t)__nv_cvt_float_to_fp8(1.0f,__NV_SATFINITE,__NV_E4M3);
}

static float bf16_to_float(uint16_t x)
{
	union { uint32_t u; float f; } v;
	v.u = ((uint32_t)x) << 16;
	return(v.f);
}

static int32_t max_abs_err_vs_one_bf16(uint16_t *a,int32_t len,float *out)
{
	int32_t i;
	float e = 0.0f;
	if ( a == 0 || out == 0 )
		return(-1001);
	for (i=0; i<len; i++)
	{
		float d = bf16_to_float(a[i]) - 1.0f;
		if ( d < 0.0f )
			d = -d;
		if ( d > e )
			e = d;
	}
	*out = e;
	return(0);
}

static int32_t run_cublaslt_fp8_e4m3_gemm(uint8_t *d_a,uint8_t *d_b,uint16_t *d_d,void *d_ws,size_t ws_bytes,float *d_scale_a,float *d_scale_b,int32_t m,int32_t n,int32_t k)
{
	const float alpha = 1.0f,beta = 0.0f;
	cublasLtHandle_t lt = 0;
	cublasLtMatmulDesc_t op = 0;
	cublasLtMatrixLayout_t a_desc = 0,b_desc = 0,d_desc = 0;
	cublasLtMatmulPreference_t pref = 0;
	cublasLtMatmulHeuristicResult_t heur;
	int32_t got = 0,rc = 0;
	cublasOperation_t trans_a = CUBLAS_OP_T,trans_b = CUBLAS_OP_N;
	int32_t scale_mode_a = (int32_t)CUBLASLT_MATMUL_MATRIX_SCALE_SCALAR_32F;
	int32_t scale_mode_b = (int32_t)CUBLASLT_MATMUL_MATRIX_SCALE_SCALAR_32F;
	int32_t scale_mode_d = (int32_t)CUBLASLT_MATMUL_MATRIX_SCALE_SCALAR_32F;
	void *scale_a_ptr = 0,*scale_b_ptr = 0;
	cublasStatus_t st;
	if ( d_a == 0 || d_b == 0 || d_d == 0 || d_ws == 0 || d_scale_a == 0 || d_scale_b == 0 )
		return(-2001);
	scale_a_ptr = d_scale_a;
	scale_b_ptr = d_scale_b;
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
		st = cublasLtMatmulDescSetAttribute(op,CUBLASLT_MATMUL_DESC_TRANSA,&trans_a,(size_t)sizeof(trans_a));
		rc = cublaslt_probe_check(st,-22,"cublasLtMatmulDescSetAttribute(TRANSA)");
		if ( rc != 0 )
			break;
		st = cublasLtMatmulDescSetAttribute(op,CUBLASLT_MATMUL_DESC_TRANSB,&trans_b,(size_t)sizeof(trans_b));
		rc = cublaslt_probe_check(st,-23,"cublasLtMatmulDescSetAttribute(TRANSB)");
		if ( rc != 0 )
			break;
		st = cublasLtMatmulDescSetAttribute(op,CUBLASLT_MATMUL_DESC_A_SCALE_MODE,&scale_mode_a,(size_t)sizeof(scale_mode_a));
		rc = cublaslt_probe_check(st,-24,"cublasLtMatmulDescSetAttribute(A_SCALE_MODE)");
		if ( rc != 0 )
			break;
		st = cublasLtMatmulDescSetAttribute(op,CUBLASLT_MATMUL_DESC_B_SCALE_MODE,&scale_mode_b,(size_t)sizeof(scale_mode_b));
		rc = cublaslt_probe_check(st,-25,"cublasLtMatmulDescSetAttribute(B_SCALE_MODE)");
		if ( rc != 0 )
			break;
		st = cublasLtMatmulDescSetAttribute(op,CUBLASLT_MATMUL_DESC_D_SCALE_MODE,&scale_mode_d,(size_t)sizeof(scale_mode_d));
		rc = cublaslt_probe_check(st,-26,"cublasLtMatmulDescSetAttribute(D_SCALE_MODE)");
		if ( rc != 0 )
			break;
		st = cublasLtMatmulDescSetAttribute(op,CUBLASLT_MATMUL_DESC_A_SCALE_POINTER,&scale_a_ptr,(size_t)sizeof(scale_a_ptr));
		rc = cublaslt_probe_check(st,-27,"cublasLtMatmulDescSetAttribute(A_SCALE_POINTER)");
		if ( rc != 0 )
			break;
		st = cublasLtMatmulDescSetAttribute(op,CUBLASLT_MATMUL_DESC_B_SCALE_POINTER,&scale_b_ptr,(size_t)sizeof(scale_b_ptr));
		rc = cublaslt_probe_check(st,-28,"cublasLtMatmulDescSetAttribute(B_SCALE_POINTER)");
		if ( rc != 0 )
			break;
		st = cublasLtMatrixLayoutCreate(&a_desc,CUDA_R_8F_E4M3,k,m,k);
		rc = cublaslt_probe_check(st,-29,"cublasLtMatrixLayoutCreate(A)");
		if ( rc != 0 )
			break;
		st = cublasLtMatrixLayoutCreate(&b_desc,CUDA_R_8F_E4M3,k,n,k);
		rc = cublaslt_probe_check(st,-30,"cublasLtMatrixLayoutCreate(B)");
		if ( rc != 0 )
			break;
		st = cublasLtMatrixLayoutCreate(&d_desc,CUDA_R_16BF,m,n,m);
		rc = cublaslt_probe_check(st,-31,"cublasLtMatrixLayoutCreate(D)");
		if ( rc != 0 )
			break;
		st = cublasLtMatmulPreferenceCreate(&pref);
		rc = cublaslt_probe_check(st,-32,"cublasLtMatmulPreferenceCreate");
		if ( rc != 0 )
			break;
		st = cublasLtMatmulPreferenceSetAttribute(pref,CUBLASLT_MATMUL_PREF_MAX_WORKSPACE_BYTES,&ws_bytes,(size_t)sizeof(ws_bytes));
		rc = cublaslt_probe_check(st,-33,"cublasLtMatmulPreferenceSetAttribute(MAX_WORKSPACE_BYTES)");
		if ( rc != 0 )
			break;
		st = cublasLtMatmulAlgoGetHeuristic(lt,op,a_desc,b_desc,d_desc,d_desc,pref,1,&heur,&got);
		rc = cublaslt_probe_check(st,-34,"cublasLtMatmulAlgoGetHeuristic");
		if ( rc != 0 )
			break;
		if ( got <= 0 )
		{
			rc = -35;
			break;
		}
		st = cublasLtMatmul(lt,op,&alpha,d_a,a_desc,d_b,b_desc,&beta,d_d,d_desc,d_d,d_desc,&heur.algo,d_ws,ws_bytes,0);
		rc = cublaslt_probe_check(st,-36,"cublasLtMatmul");
		if ( rc != 0 )
			break;
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
	static const int32_t m = 16,n = 16,k = 16;
	uint8_t *d_a = 0,*d_b = 0;
	uint16_t h_d[m * n];
	uint16_t *d_d = 0;
	float *d_scale_a = 0,*d_scale_b = 0;
	void *d_ws = 0;
	size_t ws_bytes = (size_t)(1u<<20);
	float max_err = 0.0f;
	int32_t rc = 0,threads = 256,blocks = 1,elems = 0;
	float one = 1.0f;
	(void)argc;
	(void)argv;
	cuda_probe_print_versions();
	printf("cublasLtGetVersion=%zu cublasLtGetCudartVersion=%zu\n",cublasLtGetVersion(),cublasLtGetCudartVersion());
	do
	{
		rc = cuda_probe_check(cudaMalloc((void **)&d_a,(size_t)k * (size_t)m),-1,"cudaMalloc(A fp8)");
		if ( rc != 0 )
			break;
		rc = cuda_probe_check(cudaMalloc((void **)&d_b,(size_t)k * (size_t)n),-2,"cudaMalloc(B fp8)");
		if ( rc != 0 )
			break;
		rc = cuda_probe_check(cudaMalloc((void **)&d_d,(size_t)m * (size_t)n * (size_t)sizeof(uint16_t)),-3,"cudaMalloc(D bf16)");
		if ( rc != 0 )
			break;
		rc = cuda_probe_check(cudaMalloc((void **)&d_scale_a,(size_t)sizeof(float)),-9,"cudaMalloc(scale_a)");
		if ( rc != 0 )
			break;
		rc = cuda_probe_check(cudaMalloc((void **)&d_scale_b,(size_t)sizeof(float)),-10,"cudaMalloc(scale_b)");
		if ( rc != 0 )
			break;
		rc = cuda_probe_check(cudaMalloc(&d_ws,ws_bytes),-4,"cudaMalloc(workspace)");
		if ( rc != 0 )
			break;
		rc = cuda_probe_check(cudaMemcpy(d_scale_a,&one,(size_t)sizeof(float),cudaMemcpyHostToDevice),-11,"cudaMemcpy(H2D scale_a)");
		if ( rc != 0 )
			break;
		rc = cuda_probe_check(cudaMemcpy(d_scale_b,&one,(size_t)sizeof(float),cudaMemcpyHostToDevice),-12,"cudaMemcpy(H2D scale_b)");
		if ( rc != 0 )
			break;
		elems = (k * m);
		if ( (k * n) > elems )
			elems = (k * n);
		blocks = ((elems + threads - 1) / threads);
		fp8_fill_identity_ones_e4m3<<<blocks,threads>>>(d_a,d_b,m,n,k);
		rc = cuda_probe_check(cudaGetLastError(),-5,"fp8_fill_identity_ones_e4m3 launch");
		if ( rc != 0 )
			break;
		rc = cuda_probe_check(cudaMemset(d_d,0,(size_t)m * (size_t)n * (size_t)sizeof(uint16_t)),-6,"cudaMemset(D)");
		if ( rc != 0 )
			break;
		rc = run_cublaslt_fp8_e4m3_gemm(d_a,d_b,d_d,d_ws,ws_bytes,d_scale_a,d_scale_b,m,n,k);
		if ( rc != 0 )
			break;
		rc = cuda_probe_check(cudaDeviceSynchronize(),-7,"cudaDeviceSynchronize");
		if ( rc != 0 )
			break;
		rc = cuda_probe_check(cudaMemcpy(h_d,d_d,(size_t)m * (size_t)n * (size_t)sizeof(uint16_t),cudaMemcpyDeviceToHost),-8,"cudaMemcpy(D2H D)");
		if ( rc != 0 )
			break;
		rc = max_abs_err_vs_one_bf16(h_d,(m * n),&max_err);
		if ( rc != 0 )
			break;
	} while (0);
	if ( d_ws != 0 )
		cudaFree(d_ws);
	if ( d_scale_b != 0 )
		cudaFree(d_scale_b);
	if ( d_scale_a != 0 )
		cudaFree(d_scale_a);
	if ( d_d != 0 )
		cudaFree(d_d);
	if ( d_b != 0 )
		cudaFree(d_b);
	if ( d_a != 0 )
		cudaFree(d_a);
	if ( rc != 0 )
		return(rc);
	printf("cuBLASLt fp8 e4m3 smoke max_abs_err_vs_one=%g\n",max_err);
	if ( max_err > 1.0e-2f )
		return(-40);
	return(0);
}
