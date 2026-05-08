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

.PHONY: all clean

all: $(DEVICE_PROPS) $(SM121_PROBE) $(CUBLASLT_SMOKE) $(SM121_ARCH_REPORT)

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

clean:
	rm -rf $(BIN_DIR)
