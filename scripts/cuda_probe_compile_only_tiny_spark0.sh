#!/usr/bin/env sh
set -eu

target="${1:-spark0@aitopatom-9ab9.local}"
SSH_OPTS="${SSH_OPTS:-"-o BatchMode=yes -o ConnectTimeout=10 -o StrictHostKeyChecking=accept-new -o UserKnownHostsFile=/private/tmp/ds4_spark_known_hosts"}"
REMOTE_DIR="${REMOTE_DIR:-/tmp/ds4_cuda_probe_compile_only_tiny}"

repo_root="$(cd "$(dirname "$0")/.." && pwd)"
probe_dir="$repo_root/tools/cuda_probe"
tar_no_mac_metadata=""
if tar --version 2>/dev/null | grep -qi "bsdtar"; then
	tar_no_mac_metadata="--no-mac-metadata"
fi

if [ ! -d "$probe_dir" ]; then
	echo "missing $probe_dir" >&2
	exit 2
fi

ssh $SSH_OPTS "$target" "set -eu
rm -rf \"$REMOTE_DIR\"
mkdir -p \"$REMOTE_DIR\"
"

LC_ALL=C env COPYFILE_DISABLE=1 tar --no-xattrs $tar_no_mac_metadata -C "$probe_dir" -cf - . | ssh $SSH_OPTS "$target" "set -eu
LC_ALL=C LANG=C tar -C \"$REMOTE_DIR\" -xf -
"

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
echo \"== nvcc: --list-gpu-arch (if supported) ==\"
list_gpu_arch=\$(\$NVCC --list-gpu-arch 2>/dev/null || true)
if [ \"\${list_gpu_arch}\" = \"\" ]; then
	echo \"(nvcc --list-gpu-arch not supported)\"
else
	printf \"%s\n\" \"\${list_gpu_arch}\"
	if echo \"\${list_gpu_arch}\" | grep -q \"compute_121\"; then
		:
	else
		echo \"(nvcc --list-gpu-arch missing compute_121)\" >&2
		exit 4
	fi
fi
echo
echo \"== nvcc: --list-gpu-code (if supported) ==\"
list_gpu_code=\$(\$NVCC --list-gpu-code 2>/dev/null || true)
if [ \"\${list_gpu_code}\" = \"\" ]; then
	echo \"(nvcc --list-gpu-code not supported)\"
	else
		printf \"%s\n\" \"\${list_gpu_code}\"
		if echo \"\${list_gpu_code}\" | grep -q \"sm_121\"; then
			:
		else
			echo \"(nvcc --list-gpu-code missing sm_121)\" >&2
			exit 5
		fi
	fi

	echo
	echo \"== nvcc: sm_121 variant compile (best-effort) ==\"
	cd \"$REMOTE_DIR\"
	mkdir -p bin
	try_variant() {
		arch=\"\$1\"
		advertised=\"unknown\"
		if [ \"\${list_gpu_code}\" != \"\" ]; then
			if echo \"\${list_gpu_code}\" | grep -q \"\${arch}\"; then
				advertised=\"yes\"
			else
				advertised=\"no\"
			fi
		fi
		echo \"-- \${arch} (best-effort; advertised=\${advertised})\"
		set +e
		\$NVCC -O2 -std=c++17 -arch=\${arch} -c -o bin/cuda_\${arch}_compile_probe.o src/cuda_sm121_compile_probe.cu 2>bin/cuda_\${arch}_compile_probe.err
		rc=\$?
		set -e
		if [ \$rc -eq 0 ]; then
			echo \"variant_\${arch}: OK\"
		else
			echo \"variant_\${arch}: FAILED rc=\$rc\"
			head -n 40 bin/cuda_\${arch}_compile_probe.err || true
		fi
	}
	try_variant sm_121a
	try_variant sm_121f

	echo
	echo \"== nvcc: __CUDA_ARCH_LIST__ probe (best-effort) ==\"
	cat > bin/cuda_sm121_arch_list_probe.cu <<'EOF'
#define STR1(x) #x
#define STR(x) STR1(x)

#if defined(__CUDA_ARCH_LIST__)
#pragma message(\"CUDA_ARCH_LIST=\" STR(__CUDA_ARCH_LIST__))
#else
#pragma message(\"CUDA_ARCH_LIST=(missing)\")
#endif

int cuda_arch_list_probe_dummy(void)
{
	return(0);
}
EOF

	try_arch_list() {
		tag=\"\$1\"
		arch=\"\$2\"
		echo \"-- \${tag} (-arch=\${arch})\"
		set +e
		\$NVCC -O2 -std=c++17 -arch=\${arch} -c -o bin/\${tag}.o bin/cuda_sm121_arch_list_probe.cu 2>bin/\${tag}.err
		rc=\$?
		set -e
		if [ \$rc -eq 0 ]; then
			arch_list=\$(grep -E \"CUDA_ARCH_LIST=\" bin/\${tag}.err | head -n 1 | sed -E 's/^.*CUDA_ARCH_LIST=//' | tr -cd '0-9,')
			if [ \"\${arch_list}\" = \"\" ]; then
				arch_list=\"(missing)\"
			fi
			echo \"\${tag}: OK __CUDA_ARCH_LIST__=\${arch_list}\"
		else
			echo \"\${tag}: FAILED rc=\$rc\"
			head -n 40 bin/\${tag}.err || true
		fi
	}

	try_arch_list arch_list_sm_121 sm_121
	try_arch_list arch_list_sm_121a sm_121a
	try_arch_list arch_list_sm_121f sm_121f

	echo
	echo \"== nvcc: feature-set macro compile (best-effort) ==\"
	cat > bin/cuda_sm121_featureset_macros_compile_probe.cu <<'EOF'
#include <stdint.h>

	#if defined(__CUDA_ARCH__)
	#if (__CUDA_ARCH__ != 1210)
	#error featureset_macros_expected___CUDA_ARCH___1210
		#endif

		#if defined(EXPECT_SPECIFIC)
	#if !defined(__CUDA_ARCH_SPECIFIC__)
	#error featureset_macros_expected___CUDA_ARCH_SPECIFIC___defined
	#endif
	#if (__CUDA_ARCH_SPECIFIC__ != 1210)
	#error featureset_macros_expected___CUDA_ARCH_SPECIFIC___1210
	#endif
	#else
	#if defined(__CUDA_ARCH_SPECIFIC__)
	#error featureset_macros_unexpected___CUDA_ARCH_SPECIFIC___defined
	#endif
		#endif

		#if defined(EXPECT_FAMILY)
	#if !defined(__CUDA_ARCH_FAMILY_SPECIFIC__)
	#error featureset_macros_expected___CUDA_ARCH_FAMILY_SPECIFIC___defined
	#endif
	#if (__CUDA_ARCH_FAMILY_SPECIFIC__ != 1210)
	#error featureset_macros_expected___CUDA_ARCH_FAMILY_SPECIFIC___1210
	#endif
	#else
	#if defined(__CUDA_ARCH_FAMILY_SPECIFIC__)
	#error featureset_macros_unexpected___CUDA_ARCH_FAMILY_SPECIFIC___defined
	#endif
	#endif
	#endif

__global__ void featureset_macros_compile_probe(uint32_t *out)
{
	(void)out;
}
EOF

	try_featureset_macros() {
		tag=\"\$1\"
		arch=\"\$2\"
		defs=\"\$3\"
		echo \"-- \${tag} (-arch=\${arch})\"
		set +e
		\$NVCC -O2 -std=c++17 \${defs} -arch=\${arch} -c -o bin/\${tag}.o bin/cuda_sm121_featureset_macros_compile_probe.cu 2>bin/\${tag}.err
		rc=\$?
		set -e
		if [ \$rc -eq 0 ]; then
			echo \"\${tag}: OK\"
		else
			echo \"\${tag}: FAILED rc=\$rc\"
			head -n 40 bin/\${tag}.err || true
		fi
	}

	try_featureset_macros featureset_compute_121a compute_121a \"-DEXPECT_SPECIFIC=1 -DEXPECT_FAMILY=1\"
	try_featureset_macros featureset_compute_121f compute_121f \"-DEXPECT_FAMILY=1\"

	echo
	echo \"== nvcc: compute_121 compile (best-effort) ==\"
	if [ \"\${list_gpu_arch}\" = \"\" ]; then
		echo \"(nvcc --list-gpu-arch not supported; skipping compute_121)\"
else
	if echo \"\${list_gpu_arch}\" | grep -q \"compute_121\"; then
		echo \"-- compute_121\"
		set +e
		\$NVCC -O2 -std=c++17 -arch=compute_121 -c -o bin/cuda_compute_121_compile_probe.o src/cuda_sm121_compile_probe.cu 2>bin/cuda_compute_121_compile_probe.err
		rc=\$?
		set -e
		if [ \$rc -eq 0 ]; then
			echo \"arch_compute_121: OK\"
		else
			echo \"arch_compute_121: FAILED rc=\$rc\"
			head -n 40 bin/cuda_compute_121_compile_probe.err || true
		fi
	else
		echo \"(nvcc --list-gpu-arch missing compute_121; skipping)\"
	fi
fi

echo
echo \"== nvcc: gencode compile (best-effort) ==\"
if [ \"\${list_gpu_arch}\" = \"\" ]; then
	echo \"(nvcc --list-gpu-arch not supported; skipping gencode)\"
else
	if echo \"\${list_gpu_arch}\" | grep -q \"compute_121\"; then
		set +e
		\$NVCC -O2 -std=c++17 -gencode \"arch=compute_121,code=sm_121\" -c -o bin/cuda_gencode_sm_121_compile_probe.o src/cuda_sm121_compile_probe.cu 2>bin/cuda_gencode_sm_121_compile_probe.err
		rc=\$?
		set -e
		if [ \$rc -eq 0 ]; then
			echo \"gencode_sm_121: OK\"
		else
			echo \"gencode_sm_121: FAILED rc=\$rc\"
			head -n 40 bin/cuda_gencode_sm_121_compile_probe.err || true
		fi

		set +e
		\$NVCC -O2 -std=c++17 -gencode \"arch=compute_121,code=compute_121\" -c -o bin/cuda_gencode_compute_121_compile_probe.o src/cuda_sm121_compile_probe.cu 2>bin/cuda_gencode_compute_121_compile_probe.err
		rc=\$?
		set -e
		if [ \$rc -eq 0 ]; then
			echo \"gencode_compute_121: OK\"
		else
			echo \"gencode_compute_121: FAILED rc=\$rc\"
			head -n 40 bin/cuda_gencode_compute_121_compile_probe.err || true
		fi

		set +e
		\$NVCC -O2 -std=c++17 -gencode \"arch=compute_121,code=[sm_121,compute_121]\" -c -o bin/cuda_gencode_sm_121_plus_compute_121_compile_probe.o src/cuda_sm121_compile_probe.cu 2>bin/cuda_gencode_sm_121_plus_compute_121_compile_probe.err
		rc=\$?
		set -e
		if [ \$rc -eq 0 ]; then
			echo \"gencode_sm_121_plus_compute_121: OK\"
		else
			echo \"gencode_sm_121_plus_compute_121: FAILED rc=\$rc\"
			head -n 40 bin/cuda_gencode_sm_121_plus_compute_121_compile_probe.err || true
		fi
	else
		echo \"(nvcc --list-gpu-arch missing compute_121; skipping gencode)\"
	fi
fi

echo
echo \"== nvcc: cluster_dims attribute compile (best-effort) ==\"
set +e
\$NVCC -O2 -std=c++17 -arch=sm_121 -c -o bin/cuda_sm121_cluster_dims_attr_compile.o src/cuda_sm121_cluster_dims_attr_compile.cu 2>bin/cuda_sm121_cluster_dims_attr_compile.err
rc=\$?
set -e
if [ \$rc -eq 0 ]; then
	echo \"cluster_dims_attr_compile: OK\"
else
	echo \"cluster_dims_attr_compile: FAILED rc=\$rc\"
	head -n 40 bin/cuda_sm121_cluster_dims_attr_compile.err || true
fi

echo
echo \"== compile-only (tiny) ==\"
make clean
make bin/cuda_sm121_compile_probe.o bin/cuda_sm121_gpuarch_compile_probe.o bin/cuda_sm121_cxx20_flags_compile_probe.o bin/cuda_sm121_cxx20_flags_gpuarch_compile_probe.o

	echo
	echo \"== nvcc: -arch=sm_121 emits embedded PTX (best-effort) ==\"
	CUOBJDUMP=\"\"
	if [ -x /usr/local/cuda/bin/cuobjdump ]; then
		CUOBJDUMP=\"/usr/local/cuda/bin/cuobjdump\"
elif command -v cuobjdump >/dev/null 2>&1; then
	CUOBJDUMP=\"cuobjdump\"
fi
	if [ \"\${CUOBJDUMP}\" = \"\" ]; then
		echo \"(cuobjdump not found; skipping)\"
	else
		set +e
		\$NVCC -O2 -std=c++17 -arch=sm_121 -fatbin -o bin/cuda_sm121_arch_shorthand.fatbin src/cuda_sm121_probe.cu 2>bin/cuda_sm121_arch_shorthand.err
	rc=\$?
	set -e
	if [ \$rc -ne 0 ]; then
		echo \"(nvcc -fatbin -arch=sm_121 failed rc=\$rc)\" >&2
		head -n 40 bin/cuda_sm121_arch_shorthand.err || true
		else
			ptx_target_line=\$(\$CUOBJDUMP --dump-ptx bin/cuda_sm121_arch_shorthand.fatbin 2>/dev/null | grep \"^\\\\.target\" | head -n 1 || true)
			if [ \"\${ptx_target_line}\" != \"\" ]; then
				echo \"ptx_embed: OK\"
				echo \"ptx_target_sm_121: \${ptx_target_line}\"
			else
				echo \"ptx_embed: MISSING\" >&2
				\$CUOBJDUMP --dump-ptx bin/cuda_sm121_arch_shorthand.fatbin 2>/dev/null | head -n 40 || true
			fi
		fi
	fi

	echo
	echo \"== nvcc: -gencode PTX embed behavior (best-effort) ==\"
	if [ \"\${CUOBJDUMP}\" = \"\" ]; then
		echo \"(cuobjdump not found; skipping)\"
	elif [ \"\${list_gpu_arch}\" = \"\" ]; then
		echo \"(nvcc --list-gpu-arch not supported; skipping)\"
	elif echo \"\${list_gpu_arch}\" | grep -q \"compute_121\"; then
		set +e
		\$NVCC -O2 -std=c++17 -gencode \"arch=compute_121,code=sm_121\" -fatbin -o bin/cuda_gencode_sm_121_only.fatbin src/cuda_sm121_probe.cu 2>bin/cuda_gencode_sm_121_only.err
		rc=\$?
		set -e
		if [ \$rc -ne 0 ]; then
			echo \"(nvcc -fatbin -gencode code=sm_121 failed rc=\$rc)\" >&2
			head -n 40 bin/cuda_gencode_sm_121_only.err || true
		else
			ptx_target_line=\$(\$CUOBJDUMP --dump-ptx bin/cuda_gencode_sm_121_only.fatbin 2>/dev/null | grep \"^\\\\.target\" | head -n 1 || true)
			if [ \"\${ptx_target_line}\" != \"\" ]; then
				echo \"ptx_embed_gencode_sm_only: PRESENT (unexpected)\"
				echo \"ptx_target_gencode_sm_only: \${ptx_target_line}\"
			else
				echo \"ptx_embed_gencode_sm_only: MISSING (expected)\"
			fi
		fi

		set +e
		\$NVCC -O2 -std=c++17 -gencode \"arch=compute_121,code=compute_121\" -fatbin -o bin/cuda_gencode_compute_121_only.fatbin src/cuda_sm121_probe.cu 2>bin/cuda_gencode_compute_121_only.err
		rc=\$?
		set -e
		if [ \$rc -ne 0 ]; then
			echo \"(nvcc -fatbin -gencode code=compute_121 failed rc=\$rc)\" >&2
			head -n 40 bin/cuda_gencode_compute_121_only.err || true
		else
			ptx_target_line=\$(\$CUOBJDUMP --dump-ptx bin/cuda_gencode_compute_121_only.fatbin 2>/dev/null | grep \"^\\\\.target\" | head -n 1 || true)
			if [ \"\${ptx_target_line}\" != \"\" ]; then
				echo \"ptx_embed_gencode_ptx_only: PRESENT (expected)\"
				echo \"ptx_target_gencode_ptx_only: \${ptx_target_line}\"
			else
				echo \"ptx_embed_gencode_ptx_only: MISSING\" >&2
			fi
		fi

		set +e
		\$NVCC -O2 -std=c++17 -gencode \"arch=compute_121,code=[sm_121,compute_121]\" -fatbin -o bin/cuda_gencode_sm_plus_ptx_list.fatbin src/cuda_sm121_probe.cu 2>bin/cuda_gencode_sm_plus_ptx_list.err
		rc=\$?
		set -e
		if [ \$rc -ne 0 ]; then
			echo \"(nvcc -fatbin -gencode code=[sm_121,compute_121] failed rc=\$rc)\" >&2
			head -n 40 bin/cuda_gencode_sm_plus_ptx_list.err || true
		else
			ptx_target_line=\$(\$CUOBJDUMP --dump-ptx bin/cuda_gencode_sm_plus_ptx_list.fatbin 2>/dev/null | grep \"^\\\\.target\" | head -n 1 || true)
			if [ \"\${ptx_target_line}\" != \"\" ]; then
				echo \"ptx_embed_gencode_sm_plus_ptx_list: PRESENT (expected)\"
				echo \"ptx_target_gencode_sm_plus_ptx_list: \${ptx_target_line}\"
			else
				echo \"ptx_embed_gencode_sm_plus_ptx_list: MISSING\" >&2
			fi
		fi

		set +e
		\$NVCC -O2 -std=c++17 -gencode \"arch=compute_121,code=sm_121\" -gencode \"arch=compute_121,code=compute_121\" -fatbin -o bin/cuda_gencode_sm_plus_ptx.fatbin src/cuda_sm121_probe.cu 2>bin/cuda_gencode_sm_plus_ptx.err
		rc=\$?
		set -e
		if [ \$rc -ne 0 ]; then
			echo \"(nvcc -fatbin -gencode sm_121+compute_121 failed rc=\$rc)\" >&2
			head -n 40 bin/cuda_gencode_sm_plus_ptx.err || true
		else
			ptx_target_line=\$(\$CUOBJDUMP --dump-ptx bin/cuda_gencode_sm_plus_ptx.fatbin 2>/dev/null | grep \"^\\\\.target\" | head -n 1 || true)
			if [ \"\${ptx_target_line}\" != \"\" ]; then
				echo \"ptx_embed_gencode_sm_plus_ptx: PRESENT (expected)\"
				echo \"ptx_target_gencode_sm_plus_ptx: \${ptx_target_line}\"
			else
				echo \"ptx_embed_gencode_sm_plus_ptx: MISSING\" >&2
			fi
		fi
	else
		echo \"(nvcc --list-gpu-arch missing compute_121; skipping)\"
	fi

	echo
	echo \"== nvcc: -arch=native emits embedded PTX (best-effort; expected missing) ==\"
	if [ \"\${CUOBJDUMP}\" = \"\" ]; then
		echo \"(cuobjdump not found; skipping)\"
else
	set +e
	\$NVCC -O2 -std=c++17 -arch=native -fatbin -o bin/cuda_native_arch_shorthand.fatbin src/cuda_sm121_probe.cu 2>bin/cuda_native_arch_shorthand.err
	rc=\$?
	set -e
	if [ \$rc -ne 0 ]; then
		echo \"(nvcc -fatbin -arch=native failed rc=\$rc)\" >&2
		head -n 40 bin/cuda_native_arch_shorthand.err || true
	else
		if \$CUOBJDUMP --dump-ptx bin/cuda_native_arch_shorthand.fatbin 2>/dev/null | grep -q \"^\\\\.target\"; then
			echo \"ptx_embed_native: PRESENT\"
			ptx_target_line=\$(\$CUOBJDUMP --dump-ptx bin/cuda_native_arch_shorthand.fatbin 2>/dev/null | grep \"^\\\\.target\" | head -n 1 || true)
			if [ \"\${ptx_target_line}\" != \"\" ]; then
				echo \"ptx_target_native: \${ptx_target_line}\"
			fi
		else
			echo \"ptx_embed_native: MISSING (expected)\"
		fi
	fi
fi
"
