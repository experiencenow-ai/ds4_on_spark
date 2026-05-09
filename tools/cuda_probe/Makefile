CUDA_HOME ?= /usr/local/cuda
NVCC ?= $(CUDA_HOME)/bin/nvcc
CXXFLAGS ?= -O2 -std=c++17
CXXFLAGS_CXX20 ?= -O2 -std=c++20
LDFLAGS ?=

BIN_DIR := bin
SRC_DIR := src

DEVICE_PROPS := $(BIN_DIR)/cuda_device_props
DEVICE_PROPS_TINY := $(BIN_DIR)/cuda_device_props_tiny
SM121_PROBE := $(BIN_DIR)/cuda_sm121_probe
SM121_FATBIN_PROBE := $(BIN_DIR)/cuda_sm121_fatbin_probe
SM121_COMPILE_PROBE_OBJ := $(BIN_DIR)/cuda_sm121_compile_probe.o
CUBLASLT_SMOKE := $(BIN_DIR)/cuda_cublaslt_smoke
CUBLASLT_FP8_SMOKE := $(BIN_DIR)/cuda_cublaslt_fp8_smoke
CUBLASLT_FP8_E5M2_SMOKE := $(BIN_DIR)/cuda_cublaslt_fp8_e5m2_smoke
SM121_ARCH_REPORT := $(BIN_DIR)/cuda_sm121_arch_report
SM121_SMEM_OPTIN := $(BIN_DIR)/cuda_sm121_smem_optin
SM121_DEVATTRS := $(BIN_DIR)/cuda_sm121_devattrs
SM121_FP8_CONV := $(BIN_DIR)/cuda_sm121_fp8_conv
SM121_PIPELINE_MEMCPY_ASYNC := $(BIN_DIR)/cuda_sm121_pipeline_memcpy_async
SM120_COMPAT_PROBE := $(BIN_DIR)/cuda_sm120_compat_probe
SM121_BARRIER_MEMCPY_ASYNC := $(BIN_DIR)/cuda_sm121_barrier_memcpy_async
SM121_CP_ASYNC_BULK_TX := $(BIN_DIR)/cuda_sm121_cp_async_bulk_tx
SM121_WMMA_SMOKE := $(BIN_DIR)/cuda_sm121_wmma_smoke
SM121_CLUSTER_LAUNCH := $(BIN_DIR)/cuda_sm121_cluster_launch
SM121_CCCL_ATOMIC_REF := $(BIN_DIR)/cuda_sm121_cccl_atomic_ref
SM121_CUDA_GRAPH_SMOKE := $(BIN_DIR)/cuda_sm121_cuda_graph_smoke
SM121_CXX20_PROBE := $(BIN_DIR)/cuda_sm121_cxx20_probe
SM121_NVRTC_JIT := $(BIN_DIR)/cuda_sm121_nvrtc_jit
SM121_NVCC_FLAGS_PROBE := $(BIN_DIR)/cuda_sm121_nvcc_flags_probe
SM121_NVJITLINK_JIT := $(BIN_DIR)/cuda_sm121_nvjitlink_jit
SM121_RDC_PROBE := $(BIN_DIR)/cuda_sm121_rdc_probe
SM121_RDC_PROBE_OBJ := $(BIN_DIR)/cuda_sm121_rdc_probe.o
SM121_RDC_LIB_OBJ := $(BIN_DIR)/cuda_sm121_rdc_lib.o
SM121_RDC_DLINK_OBJ := $(BIN_DIR)/cuda_sm121_rdc_dlink.o

.PHONY: all clean

all: $(DEVICE_PROPS) $(DEVICE_PROPS_TINY) $(SM121_COMPILE_PROBE_OBJ) $(SM121_PROBE) $(SM121_FATBIN_PROBE) $(CUBLASLT_SMOKE) $(CUBLASLT_FP8_SMOKE) $(CUBLASLT_FP8_E5M2_SMOKE) $(SM121_ARCH_REPORT) $(SM121_SMEM_OPTIN) $(SM121_DEVATTRS) $(SM121_FP8_CONV) $(SM121_PIPELINE_MEMCPY_ASYNC) $(SM120_COMPAT_PROBE) $(SM121_BARRIER_MEMCPY_ASYNC) $(SM121_CP_ASYNC_BULK_TX) $(SM121_WMMA_SMOKE) $(SM121_CLUSTER_LAUNCH) $(SM121_CCCL_ATOMIC_REF) $(SM121_CUDA_GRAPH_SMOKE) $(SM121_CXX20_PROBE) $(SM121_NVRTC_JIT) $(SM121_NVCC_FLAGS_PROBE) $(SM121_NVJITLINK_JIT) $(SM121_RDC_PROBE)

$(BIN_DIR):
	mkdir -p $(BIN_DIR)

$(DEVICE_PROPS): $(BIN_DIR) $(SRC_DIR)/cuda_device_props.cu $(SRC_DIR)/cuda_probe_util.h
	$(NVCC) $(CXXFLAGS) -arch=native -o $@ $(SRC_DIR)/cuda_device_props.cu $(LDFLAGS)

$(DEVICE_PROPS_TINY): $(BIN_DIR) $(SRC_DIR)/cuda_device_props_tiny.cu $(SRC_DIR)/cuda_probe_util.h
	$(NVCC) $(CXXFLAGS) -arch=native -o $@ $(SRC_DIR)/cuda_device_props_tiny.cu $(LDFLAGS)

$(SM121_COMPILE_PROBE_OBJ): $(BIN_DIR) $(SRC_DIR)/cuda_sm121_compile_probe.cu
	$(NVCC) $(CXXFLAGS) -arch=sm_121 -c -o $@ $(SRC_DIR)/cuda_sm121_compile_probe.cu

$(SM121_PROBE): $(BIN_DIR) $(SRC_DIR)/cuda_sm121_probe.cu $(SRC_DIR)/cuda_probe_util.h
	$(NVCC) $(CXXFLAGS) -arch=sm_121 -o $@ $(SRC_DIR)/cuda_sm121_probe.cu $(LDFLAGS)

$(SM121_FATBIN_PROBE): $(BIN_DIR) $(SRC_DIR)/cuda_sm121_fatbin_probe.cu $(SRC_DIR)/cuda_probe_util.h
	$(NVCC) $(CXXFLAGS) -gencode arch=compute_120,code=sm_120 -gencode arch=compute_121,code=sm_121 -gencode arch=compute_121,code=compute_121 -o $@ $(SRC_DIR)/cuda_sm121_fatbin_probe.cu $(LDFLAGS)

$(CUBLASLT_SMOKE): $(BIN_DIR) $(SRC_DIR)/cuda_cublaslt_smoke.cu $(SRC_DIR)/cuda_probe_util.h
	$(NVCC) $(CXXFLAGS) -arch=sm_121 -o $@ $(SRC_DIR)/cuda_cublaslt_smoke.cu -lcublasLt -lcublas $(LDFLAGS)

$(CUBLASLT_FP8_SMOKE): $(BIN_DIR) $(SRC_DIR)/cuda_cublaslt_fp8_smoke.cu $(SRC_DIR)/cuda_probe_util.h
	$(NVCC) $(CXXFLAGS) -arch=sm_121 -o $@ $(SRC_DIR)/cuda_cublaslt_fp8_smoke.cu -lcublasLt -lcublas $(LDFLAGS)

$(CUBLASLT_FP8_E5M2_SMOKE): $(BIN_DIR) $(SRC_DIR)/cuda_cublaslt_fp8_e5m2_smoke.cu $(SRC_DIR)/cuda_probe_util.h
	$(NVCC) $(CXXFLAGS) -arch=sm_121 -o $@ $(SRC_DIR)/cuda_cublaslt_fp8_e5m2_smoke.cu -lcublasLt -lcublas $(LDFLAGS)

$(SM121_ARCH_REPORT): $(BIN_DIR) $(SRC_DIR)/cuda_sm121_arch_report.cu $(SRC_DIR)/cuda_probe_util.h
	$(NVCC) $(CXXFLAGS) -arch=sm_121 -o $@ $(SRC_DIR)/cuda_sm121_arch_report.cu $(LDFLAGS)

$(SM121_SMEM_OPTIN): $(BIN_DIR) $(SRC_DIR)/cuda_sm121_smem_optin.cu $(SRC_DIR)/cuda_probe_util.h
	$(NVCC) $(CXXFLAGS) -arch=sm_121 -o $@ $(SRC_DIR)/cuda_sm121_smem_optin.cu $(LDFLAGS)

$(SM121_DEVATTRS): $(BIN_DIR) $(SRC_DIR)/cuda_sm121_devattrs.cu $(SRC_DIR)/cuda_probe_util.h
	$(NVCC) $(CXXFLAGS) -arch=sm_121 -o $@ $(SRC_DIR)/cuda_sm121_devattrs.cu $(LDFLAGS)

$(SM121_FP8_CONV): $(BIN_DIR) $(SRC_DIR)/cuda_sm121_fp8_conv.cu $(SRC_DIR)/cuda_probe_util.h
	$(NVCC) $(CXXFLAGS) -arch=sm_121 -o $@ $(SRC_DIR)/cuda_sm121_fp8_conv.cu $(LDFLAGS)

$(SM121_PIPELINE_MEMCPY_ASYNC): $(BIN_DIR) $(SRC_DIR)/cuda_sm121_pipeline_memcpy_async.cu $(SRC_DIR)/cuda_probe_util.h
	$(NVCC) $(CXXFLAGS) -arch=sm_121 -o $@ $(SRC_DIR)/cuda_sm121_pipeline_memcpy_async.cu $(LDFLAGS)

$(SM121_BARRIER_MEMCPY_ASYNC): $(BIN_DIR) $(SRC_DIR)/cuda_sm121_barrier_memcpy_async.cu $(SRC_DIR)/cuda_probe_util.h
	$(NVCC) $(CXXFLAGS) -arch=sm_121 -o $@ $(SRC_DIR)/cuda_sm121_barrier_memcpy_async.cu $(LDFLAGS)

$(SM121_CP_ASYNC_BULK_TX): $(BIN_DIR) $(SRC_DIR)/cuda_sm121_cp_async_bulk_tx.cu $(SRC_DIR)/cuda_probe_util.h
	$(NVCC) $(CXXFLAGS) -arch=sm_121 -o $@ $(SRC_DIR)/cuda_sm121_cp_async_bulk_tx.cu $(LDFLAGS)

$(SM120_COMPAT_PROBE): $(BIN_DIR) $(SRC_DIR)/cuda_sm120_compat_probe.cu $(SRC_DIR)/cuda_probe_util.h
	$(NVCC) $(CXXFLAGS) -arch=sm_120 -o $@ $(SRC_DIR)/cuda_sm120_compat_probe.cu $(LDFLAGS)

$(SM121_WMMA_SMOKE): $(BIN_DIR) $(SRC_DIR)/cuda_sm121_wmma_smoke.cu $(SRC_DIR)/cuda_probe_util.h
	$(NVCC) $(CXXFLAGS) -arch=sm_121 -o $@ $(SRC_DIR)/cuda_sm121_wmma_smoke.cu $(LDFLAGS)

$(SM121_CLUSTER_LAUNCH): $(BIN_DIR) $(SRC_DIR)/cuda_sm121_cluster_launch.cu $(SRC_DIR)/cuda_probe_util.h
	$(NVCC) $(CXXFLAGS) -arch=sm_121 -o $@ $(SRC_DIR)/cuda_sm121_cluster_launch.cu $(LDFLAGS)

$(SM121_CCCL_ATOMIC_REF): $(BIN_DIR) $(SRC_DIR)/cuda_sm121_cccl_atomic_ref.cu $(SRC_DIR)/cuda_probe_util.h
	$(NVCC) $(CXXFLAGS) -arch=sm_121 -o $@ $(SRC_DIR)/cuda_sm121_cccl_atomic_ref.cu $(LDFLAGS)

$(SM121_CUDA_GRAPH_SMOKE): $(BIN_DIR) $(SRC_DIR)/cuda_sm121_cuda_graph_smoke.cu $(SRC_DIR)/cuda_probe_util.h
	$(NVCC) $(CXXFLAGS) -arch=sm_121 -o $@ $(SRC_DIR)/cuda_sm121_cuda_graph_smoke.cu $(LDFLAGS)

$(SM121_CXX20_PROBE): $(BIN_DIR) $(SRC_DIR)/cuda_sm121_cxx20_probe.cu $(SRC_DIR)/cuda_probe_util.h
	$(NVCC) $(CXXFLAGS_CXX20) -arch=sm_121 -o $@ $(SRC_DIR)/cuda_sm121_cxx20_probe.cu $(LDFLAGS)

$(SM121_NVRTC_JIT): $(BIN_DIR) $(SRC_DIR)/cuda_sm121_nvrtc_jit.cu $(SRC_DIR)/cuda_probe_util.h
	$(NVCC) $(CXXFLAGS) -arch=sm_121 -o $@ $(SRC_DIR)/cuda_sm121_nvrtc_jit.cu -lnvrtc -lcuda $(LDFLAGS)

$(SM121_NVCC_FLAGS_PROBE): $(BIN_DIR) $(SRC_DIR)/cuda_sm121_nvcc_flags_probe.cu $(SRC_DIR)/cuda_probe_util.h
	$(NVCC) $(CXXFLAGS_CXX20) --extended-lambda --expt-relaxed-constexpr -arch=sm_121 -o $@ $(SRC_DIR)/cuda_sm121_nvcc_flags_probe.cu $(LDFLAGS)

$(SM121_NVJITLINK_JIT): $(BIN_DIR) $(SRC_DIR)/cuda_sm121_nvjitlink_jit.cu $(SRC_DIR)/cuda_probe_util.h
	$(NVCC) $(CXXFLAGS) -arch=sm_121 -o $@ $(SRC_DIR)/cuda_sm121_nvjitlink_jit.cu -lnvJitLink -lnvrtc -lcuda $(LDFLAGS)

$(SM121_RDC_PROBE_OBJ): $(BIN_DIR) $(SRC_DIR)/cuda_sm121_rdc_probe.cu $(SRC_DIR)/cuda_probe_util.h
	$(NVCC) $(CXXFLAGS) -arch=sm_121 -dc -o $@ $(SRC_DIR)/cuda_sm121_rdc_probe.cu

$(SM121_RDC_LIB_OBJ): $(BIN_DIR) $(SRC_DIR)/cuda_sm121_rdc_lib.cu
	$(NVCC) $(CXXFLAGS) -arch=sm_121 -dc -o $@ $(SRC_DIR)/cuda_sm121_rdc_lib.cu

$(SM121_RDC_DLINK_OBJ): $(BIN_DIR) $(SM121_RDC_PROBE_OBJ) $(SM121_RDC_LIB_OBJ)
	$(NVCC) -arch=sm_121 -dlink -o $@ $(SM121_RDC_PROBE_OBJ) $(SM121_RDC_LIB_OBJ)

$(SM121_RDC_PROBE): $(BIN_DIR) $(SM121_RDC_PROBE_OBJ) $(SM121_RDC_LIB_OBJ) $(SM121_RDC_DLINK_OBJ)
	$(NVCC) $(CXXFLAGS) -arch=sm_121 -o $@ $(SM121_RDC_PROBE_OBJ) $(SM121_RDC_LIB_OBJ) $(SM121_RDC_DLINK_OBJ) $(LDFLAGS)

clean:
	rm -rf $(BIN_DIR)
