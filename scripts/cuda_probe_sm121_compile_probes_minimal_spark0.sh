#!/usr/bin/env sh
set -eu

target="${1:-spark0@aitopatom-9ab9.local}"
SSH_OPTS="${SSH_OPTS:-"-o BatchMode=yes -o ConnectTimeout=10 -o ServerAliveInterval=0 -o StrictHostKeyChecking=accept-new -o UserKnownHostsFile=/private/tmp/ds4_spark_known_hosts"}"
remote_tag="${REMOTE_TAG:-"$(date -u +%Y%m%d-%H%M%S)-$$"}"
default_remote_dir="/tmp/ds4_cuda_probe_sm121_compile_probes_minimal_${remote_tag}"
REMOTE_DIR="${REMOTE_DIR:-${default_remote_dir}}"
log_path="${LOG_PATH:-}"

main() {
ssh $SSH_OPTS "$target" "set -eu
NVCC=\"\"
echo \"== nvcc ==\"
if [ -x /usr/local/cuda/bin/nvcc ]; then
	NVCC=\"/usr/local/cuda/bin/nvcc\"
elif command -v nvcc >/dev/null 2>&1; then
	NVCC=\"nvcc\"
else
	echo \"nvcc not found\" >&2
	exit 3
fi
\$NVCC --version

echo
echo \"== nvcc: --list-gpu-arch / --list-gpu-code (best-effort) ==\"
list_gpu_arch=\$(\$NVCC --list-gpu-arch 2>/dev/null || true)
if [ \"\${list_gpu_arch}\" = \"\" ]; then
	echo \"(nvcc --list-gpu-arch not supported)\"
else
	printf \"%s\n\" \"\${list_gpu_arch}\"
fi
list_gpu_code=\$(\$NVCC --list-gpu-code 2>/dev/null || true)
if [ \"\${list_gpu_code}\" = \"\" ]; then
	echo \"(nvcc --list-gpu-code not supported)\"
else
	printf \"%s\n\" \"\${list_gpu_code}\"
fi

echo
echo \"== build: sm_121 compile probes (compile-only; no link/run) ==\"
rm -rf \"$REMOTE_DIR\"
mkdir -p \"$REMOTE_DIR\"/bin

cat > \"$REMOTE_DIR\"/cuda_sm121_compile_probe_minimal.cu <<'EOF'
#include <stdint.h>

#if defined(__CUDA_ARCH__)
#if (__CUDA_ARCH__ != 1210)
#error \"sm_121 compile probe: expected __CUDA_ARCH__=1210 (sm_121)\"
#endif
#endif

__global__ void sm121_compile_probe(uint32_t *out)
{
	if ( ((int32_t)threadIdx.x) == 0 )
	{
#if defined(__CUDA_ARCH__)
		out[0] = (uint32_t)__CUDA_ARCH__;
#else
		out[0] = 0;
#endif
	}
}
EOF

cat > \"$REMOTE_DIR\"/cuda_compute121_compile_probe_minimal.cu <<'EOF'
#include <stdint.h>

#if defined(__CUDA_ARCH__)
#if (__CUDA_ARCH__ != 1210)
#error \"compute_121 compile probe: expected __CUDA_ARCH__=1210 (compute_121)\"
#endif
#endif

__global__ void compute121_compile_probe(uint32_t *out)
{
	if ( ((int32_t)threadIdx.x) == 0 )
	{
#if defined(__CUDA_ARCH__)
		out[0] = (uint32_t)__CUDA_ARCH__;
#else
		out[0] = 0;
#endif
	}
}
EOF

cat > \"$REMOTE_DIR\"/cuda_sm121_cxx20_flags_compile_probe_minimal.cu <<'EOF'
#include <stdint.h>

#if defined(__CUDA_ARCH__)
#if (__CUDA_ARCH__ != 1210)
#error \"sm_121 cxx20 flags compile probe: expected __CUDA_ARCH__=1210 (sm_121)\"
#endif
#if !defined(__CUDACC_EXTENDED_LAMBDA__)
#error \"sm_121 cxx20 flags compile probe: expected __CUDACC_EXTENDED_LAMBDA__ defined\"
#endif
#if !defined(__CUDACC_RELAXED_CONSTEXPR__)
#error \"sm_121 cxx20 flags compile probe: expected __CUDACC_RELAXED_CONSTEXPR__ defined\"
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
EOF

cat > \"$REMOTE_DIR\"/cuda_sm121_cluster_dims_attr_compile_probe_minimal.cu <<'EOF'
#include <stdint.h>

#include <cuda_runtime.h>

__global__ void __cluster_dims__(2,1,1) cluster_dims_attr_probe(uint32_t *out)
{
	if ( ((int32_t)threadIdx.x) == 0 )
		out[(int32_t)blockIdx.x] = 0;
}
EOF

cat > \"$REMOTE_DIR\"/cuda_sm121_arch_list_compile_probe_minimal.cu <<'EOF'
#define STR2(x) #x
#define STR(x) STR2(x)

#if defined(__CUDA_ARCH_LIST__)
#pragma message(\"DS4_CUDA_ARCH_LIST=\" STR(__CUDA_ARCH_LIST__))
#endif

#if defined(__CUDA_ARCH_SPECIFIC__)
#pragma message(\"DS4_CUDA_ARCH_SPECIFIC=\" STR(__CUDA_ARCH_SPECIFIC__))
#endif

#if defined(__CUDA_ARCH_FAMILY_SPECIFIC__)
#pragma message(\"DS4_CUDA_ARCH_FAMILY_SPECIFIC=\" STR(__CUDA_ARCH_FAMILY_SPECIFIC__))
#endif

__global__ void arch_list_compile_probe(void)
{
}
EOF

compile_probe() {
	tag=\"\$1\"
	src=\"\$2\"
	shift 2
	set +e
	\$NVCC -O2 -std=c++17 \"\$@\" -c -o \"$REMOTE_DIR\"/bin/\"\${tag}\".o \"$REMOTE_DIR\"/\"\${src}\" 2>\"$REMOTE_DIR\"/bin/\"\${tag}\".err
	rc=\$?
	set -e
	if [ \$rc -eq 0 ]; then
		echo \"\${tag}: OK\"
		return 0
	fi
	echo \"\${tag}: FAILED rc=\$rc\" >&2
	head -n 60 \"$REMOTE_DIR\"/bin/\"\${tag}\".err || true
	return 1
}

ptx_target_probe() {
	tag=\"\$1\"
	arch=\"\$2\"
	set +e
	\$NVCC -O2 -std=c++17 -arch=\"\${arch}\" -ptx -o \"$REMOTE_DIR\"/bin/\"\${tag}\".ptx \"$REMOTE_DIR\"/cuda_sm121_compile_probe_minimal.cu 2>\"$REMOTE_DIR\"/bin/\"\${tag}\".err
	rc=\$?
	set -e
	if [ \$rc -eq 0 ]; then
		target_line=\$(grep \"^\\\\.target\" \"$REMOTE_DIR\"/bin/\"\${tag}\".ptx | head -n 1 || true)
		if [ \"\${target_line}\" = \"\" ]; then
			target_line=\"(missing)\"
		fi
		echo \"\${tag}: OK ptx_target=\${target_line}\"
		return 0
	fi
	echo \"\${tag}: FAILED rc=\$rc\" >&2
	head -n 60 \"$REMOTE_DIR\"/bin/\"\${tag}\".err || true
	return 1
}

featureset_macros_probe() {
	tag=\"\$1\"
	arch=\"\$2\"
	set +e
	\$NVCC -O2 -std=c++17 -arch=\"\${arch}\" -c -o \"$REMOTE_DIR\"/bin/\"\${tag}\".o \"$REMOTE_DIR\"/cuda_sm121_arch_list_compile_probe_minimal.cu 2>\"$REMOTE_DIR\"/bin/\"\${tag}\".err
	rc=\$?
	set -e
	if [ \$rc -eq 0 ]; then
		spec=\$(grep -E \"DS4_CUDA_ARCH_SPECIFIC=\" \"$REMOTE_DIR\"/bin/\"\${tag}\".err | head -n 1 | sed -E 's/^.*DS4_CUDA_ARCH_SPECIFIC=//' | tr -cd '0-9')
		fam=\$(grep -E \"DS4_CUDA_ARCH_FAMILY_SPECIFIC=\" \"$REMOTE_DIR\"/bin/\"\${tag}\".err | head -n 1 | sed -E 's/^.*DS4_CUDA_ARCH_FAMILY_SPECIFIC=//' | tr -cd '0-9')
		if [ \"\${spec}\" = \"\" ]; then
			spec=\"(missing)\"
		fi
		if [ \"\${fam}\" = \"\" ]; then
			fam=\"(missing)\"
		fi
		echo \"\${tag}: OK __CUDA_ARCH_SPECIFIC__=\${spec} __CUDA_ARCH_FAMILY_SPECIFIC__=\${fam}\"
		return 0
	fi
	echo \"\${tag}: FAILED rc=\$rc\" >&2
	head -n 60 \"$REMOTE_DIR\"/bin/\"\${tag}\".err || true
	return 1
}

compile_probe sm121_arch_sm_121 cuda_sm121_compile_probe_minimal.cu -arch=sm_121
compile_probe sm121_gpuarch_sm_121 cuda_sm121_compile_probe_minimal.cu --gpu-architecture=sm_121
compile_probe sm121_gpuarchcode_sm_121 cuda_sm121_compile_probe_minimal.cu --gpu-architecture=compute_121 --gpu-code=sm_121

echo
echo \"== build: sm_121 variant alias compile probes (best-effort) ==\"
compile_probe sm121_arch_sm_121a cuda_sm121_compile_probe_minimal.cu -arch=sm_121a || true
compile_probe sm121_arch_sm_121f cuda_sm121_compile_probe_minimal.cu -arch=sm_121f || true
compile_probe sm121_gpuarch_sm_121a cuda_sm121_compile_probe_minimal.cu --gpu-architecture=sm_121a || true
compile_probe sm121_gpuarch_sm_121f cuda_sm121_compile_probe_minimal.cu --gpu-architecture=sm_121f || true

echo
echo \"== nvcc: PTX .target probe (best-effort) ==\"
ptx_target_probe ptx_target_sm_121 sm_121
ptx_target_probe ptx_target_sm_121a sm_121a || true
ptx_target_probe ptx_target_sm_121f sm_121f || true

echo
echo \"== build: sm_121 c++20 flags compile probes (compile-only; no link/run) ==\"
compile_probe sm121_cxx20_flags_arch_sm_121 cuda_sm121_cxx20_flags_compile_probe_minimal.cu -arch=sm_121 -std=c++20 --extended-lambda --expt-relaxed-constexpr
compile_probe sm121_cxx20_flags_gpuarch_sm_121 cuda_sm121_cxx20_flags_compile_probe_minimal.cu --gpu-architecture=sm_121 -std=c++20 --extended-lambda --expt-relaxed-constexpr
compile_probe sm121_cxx20_flags_gpuarchcode_sm_121 cuda_sm121_cxx20_flags_compile_probe_minimal.cu --gpu-architecture=compute_121 --gpu-code=sm_121 -std=c++20 --extended-lambda --expt-relaxed-constexpr

echo
echo \"== build: sm_121 cluster dims attr compile probes (compile-only; no link/run) ==\"
compile_probe sm121_cluster_dims_attr_arch_sm_121 cuda_sm121_cluster_dims_attr_compile_probe_minimal.cu -arch=sm_121
compile_probe sm121_cluster_dims_attr_gpuarch_sm_121 cuda_sm121_cluster_dims_attr_compile_probe_minimal.cu --gpu-architecture=sm_121
compile_probe sm121_cluster_dims_attr_gpuarchcode_sm_121 cuda_sm121_cluster_dims_attr_compile_probe_minimal.cu --gpu-architecture=compute_121 --gpu-code=sm_121

echo
echo \"== build: compute_121 compile probe (best-effort) ==\"
do_build_compute121=1
if [ \"\${list_gpu_arch}\" != \"\" ]; then
	if echo \"\${list_gpu_arch}\" | grep -q \"compute_121\"; then
		:
	else
		echo \"(nvcc --list-gpu-arch missing compute_121; skipping)\" >&2
		do_build_compute121=0
	fi
fi
if [ \"\${do_build_compute121}\" = \"1\" ]; then
	compile_probe compute121_arch_compute_121 cuda_compute121_compile_probe_minimal.cu -arch=compute_121 || true
	compile_probe compute121_gpuarch_compute_121 cuda_compute121_compile_probe_minimal.cu --gpu-architecture=compute_121 || true
	compile_probe compute121_gpuarchcode_sm_121 cuda_compute121_compile_probe_minimal.cu --gpu-architecture=compute_121 --gpu-code=sm_121 || true

	echo
	echo \"== nvcc: PTX .target probe for compute_121 (best-effort) ==\"
	ptx_target_probe ptx_target_compute_121 compute_121 || true
	ptx_target_probe ptx_target_compute_121a compute_121a || true
	ptx_target_probe ptx_target_compute_121f compute_121f || true

	echo
	echo \"== nvcc: feature-set macro compile probe (best-effort) ==\"
	featureset_macros_probe featureset_compute_121a compute_121a || true
	featureset_macros_probe featureset_compute_121f compute_121f || true

	echo
	echo \"== nvcc: gencode compile (best-effort) ==\"
	set +e
	\$NVCC -O2 -std=c++17 -gencode \"arch=compute_121,code=[sm_121,compute_121]\" -c -o \"$REMOTE_DIR\"/bin/gencode_sm121_plus_ptx.o \"$REMOTE_DIR\"/cuda_sm121_compile_probe_minimal.cu 2>\"$REMOTE_DIR\"/bin/gencode_sm121_plus_ptx.err
	rc=\$?
	set -e
	if [ \$rc -eq 0 ]; then
		echo \"gencode_sm121_plus_ptx: OK\"
	else
		echo \"gencode_sm121_plus_ptx: FAILED rc=\$rc\" >&2
		head -n 60 \"$REMOTE_DIR\"/bin/gencode_sm121_plus_ptx.err || true
		exit \"\${rc}\"
	fi
fi
"
}

if [ "$log_path" = "" ]; then
	main
	exit 0
fi

mkdir -p "$(dirname "$log_path")"
printf "== cuda_probe_sm121_compile_probes_minimal_spark0 log: %s ==\n" "$(date -u +%Y-%m-%dT%H:%M:%SZ)" >> "$log_path"
tmp_out="$(mktemp "/private/tmp/ds4_cuda_probe_sm121_compile_probes_minimal_out.XXXXXX")"
set +e
main >"$tmp_out" 2>&1
rc=$?
set -e
cat "$tmp_out"
cat "$tmp_out" >> "$log_path"
rm -f "$tmp_out"
exit $rc
