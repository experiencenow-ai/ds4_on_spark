#include <stdint.h>

#if defined(__CUDA_ARCH__)
#if (__CUDA_ARCH__ != 1210)
#error "sm_121 cxx20 flags compile probe: expected __CUDA_ARCH__=1210 (sm_121)"
#endif
#if !defined(__CUDACC_EXTENDED_LAMBDA__)
#error "sm_121 cxx20 flags compile probe: expected __CUDACC_EXTENDED_LAMBDA__ defined"
#endif
#if !defined(__CUDACC_RELAXED_CONSTEXPR__)
#error "sm_121 cxx20 flags compile probe: expected __CUDACC_RELAXED_CONSTEXPR__ defined"
#endif
#endif

template <typename T>
__host__ __device__ constexpr T add_constexpr(T a,T b)
{
	return((T)(a + b));
}

__global__ void sm121_cxx20_flags_compile_probe(uint32_t *out)
{
#if defined(__CUDA_ARCH__)
	auto lam = [] __host__ __device__ (uint32_t v) { return((uint32_t)(v + 1U)); };
	constexpr uint32_t k = add_constexpr<uint32_t>(7U,9U);
	if ( out != 0 )
		out[0] = (uint32_t)(lam((uint32_t)__CUDA_ARCH__) + k);
#else
	(void)out;
#endif
}

