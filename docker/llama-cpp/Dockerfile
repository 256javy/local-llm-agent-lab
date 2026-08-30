FROM nvidia/cuda:12.8.1-devel-ubuntu24.04 AS builder

ARG LLAMA_CPP_REPOSITORY=https://github.com/ggml-org/llama.cpp.git
ARG LLAMA_CPP_REVISION=master
ARG LLAMA_CPP_CMAKE_ARGS="-DGGML_CUDA=ON -DGGML_NATIVE=OFF -DBUILD_SHARED_LIBS=OFF"

RUN apt-get update \
    && apt-get install -y --no-install-recommends build-essential ca-certificates cmake curl git ninja-build \
    && git init /src/llama.cpp \
    && git -C /src/llama.cpp remote add origin "${LLAMA_CPP_REPOSITORY}" \
    && git -C /src/llama.cpp fetch --depth 1 origin "${LLAMA_CPP_REVISION}" \
    && git -C /src/llama.cpp checkout --detach FETCH_HEAD \
    && cmake -S /src/llama.cpp -B /src/llama.cpp/build -G Ninja \
       -DCMAKE_BUILD_TYPE=Release ${LLAMA_CPP_CMAKE_ARGS} \
       -DLLAMA_BUILD_WEBUI=OFF -DLLAMA_BUILD_UI=OFF \
    && cmake --build /src/llama.cpp/build --target llama-server -j "$(nproc)"

FROM nvidia/cuda:12.8.1-runtime-ubuntu24.04

RUN apt-get update \
    && apt-get install -y --no-install-recommends ca-certificates curl jq libgomp1 \
    && apt-get clean \
    && rm -rf /var/lib/apt/lists/*

COPY --from=builder /src/llama.cpp/build/bin/llama-server /usr/local/bin/llama-server
COPY docker/llama-cpp/entrypoint.sh /usr/local/bin/llm-lab-entrypoint
RUN chmod +x /usr/local/bin/llm-lab-entrypoint

EXPOSE 8080
ENTRYPOINT ["/usr/local/bin/llm-lab-entrypoint"]
