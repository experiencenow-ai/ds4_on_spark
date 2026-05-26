FROM vllm-node-dsv4:latest

ENV CUDA_HOME=/usr/local/cuda
ENV TORCH_CUDA_ARCH_LIST=12.1a

RUN uv pip install --system --no-deps \
    sortedcontainers \
    aiofile \
    caio \
    aiofiles \
    blake3 \
    awscrt \
    cufile-python \
    msgspec \
    nvtx \
    redis \
    httptools

RUN git clone --depth 1 --branch v0.4.5 https://github.com/LMCache/LMCache.git /tmp/LMCache \
    && cd /tmp/LMCache \
    && uv pip install --system -r requirements/build.txt \
    && CUDA_HOME=/usr/local/cuda TORCH_CUDA_ARCH_LIST=12.1a uv build --wheel --no-build-isolation --out-dir /tmp/lmcache-wheel \
    && uv pip install --system --no-deps --force-reinstall /tmp/lmcache-wheel/lmcache-*.whl \
    && python3 -c "import lmcache.integration.vllm.lmcache_connector_v1 as c; print(c.LMCacheConnectorV1Dynamic)" \
    && rm -rf /tmp/LMCache /tmp/lmcache-wheel /root/.cache/uv/builds-v0
