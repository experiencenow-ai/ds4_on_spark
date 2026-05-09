CUDA_HOME ?= /usr/local/cuda
NVCC ?= $(CUDA_HOME)/bin/nvcc
CXXFLAGS ?= -O2 -std=c++17
LDFLAGS ?=

BIN_DIR := bin
SRC_DIR := src

DEVICE_PROPS := $(BIN_DIR)/cuda_device_props
SM121_PROBE := $(BIN_DIR)/cuda_sm121_probe
CUBLASLT_SMOKE := $(BIN_DIR)/cuda_cublaslt_smoke
SM121_ARCH_REPORT := $(BIN_DIR)/cuda_sm121_arch_report
SM121_SMEM_OPTIN := $(BIN_DIR)/cuda_sm121_smem_optin
SM121_DEVATTRS := $(BIN_DIR)/cuda_sm121_devattrs
SM121_FP8_CONV := $(BIN_DIR)/cuda_sm121_fp8_conv
SM121_PIPELINE_MEMCPY_ASYNC := $(BIN_DIR)/cuda_sm121_pipeline_memcpy_async
SM121_BARRIER_MEMCPY_ASYNC := $(BIN_DIR)/cuda_sm121_barrier_memcpy_async

.PHONY: all clean

all: $(DEVICE_PROPS) $(SM121_PROBE) $(CUBLASLT_SMOKE) $(SM121_ARCH_REPORT) $(SM121_SMEM_OPTIN) $(SM121_DEVATTRS) $(SM121_FP8_CONV) $(SM121_PIPELINE_MEMCPY_ASYNC) $(SM121_BARRIER_MEMCPY_ASYNC)

$(BIN_DIR):
	mkdir -p $(BIN_DIR)

$(DEVICE_PROPS): $(BIN_DIR) $(SRC_DIR)/cuda_device_props.cu $(SRC_DIR)/cuda_probe_util.h
	$(NVCC) $(CXXFLAGS) -arch=native -o $@ $(SRC_DIR)/cuda_device_props.cu $(LDFLAGS)

$(SM121_PROBE): $(BIN_DIR) $(SRC_DIR)/cuda_sm121_probe.cu $(SRC_DIR)/cuda_probe_util.h
	$(NVCC) $(CXXFLAGS) -arch=sm_121 -o $@ $(SRC_DIR)/cuda_sm121_probe.cu $(LDFLAGS)

$(CUBLASLT_SMOKE): $(BIN_DIR) $(SRC_DIR)/cuda_cublaslt_smoke.cu $(SRC_DIR)/cuda_probe_util.h
	$(NVCC) $(CXXFLAGS) -arch=sm_121 -o $@ $(SRC_DIR)/cuda_cublaslt_smoke.cu -lcublasLt -lcublas $(LDFLAGS)

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

clean:
	rm -rf $(BIN_DIR)
