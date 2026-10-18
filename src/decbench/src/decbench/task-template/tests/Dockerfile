FROM rust:1.91.1-bookworm@sha256:c1e5f19e773b7878c3f7a805dd00a495e747acbdc76fb2337a4ebf0418896b33 AS parser
RUN git init /parser && cd /parser \
    && git remote add origin https://github.com/Noelo-Lab/rust-joern.git \
    && git fetch --depth 1 origin 9f8cad170d6b6883fe08627fa524ecb28128380d \
    && git checkout --detach FETCH_HEAD && cargo build --release --locked

FROM python:3.12.13-bookworm@sha256:3cd9086bdb30f7c9bc08a3fa621d9842e0d3f6f9291aeb4677e0547817c10b12
RUN apt-get update && apt-get install -y --no-install-recommends \
    gcc-multilib binutils gcc-arm-none-eabi gcc-mingw-w64-x86-64 git \
    && rm -rf /var/lib/apt/lists/*
COPY --from=parser /parser /opt/rust-joern
RUN pip install --no-cache-dir /opt/rust-joern
RUN git init /opt/decbench && cd /opt/decbench \
    && git remote add origin https://github.com/Noelo-Lab/decbench.git \
    && git fetch --depth 1 origin ae070b885b4e005ed37510a2c3445af6284dc2b9 \
    && git checkout --detach FETCH_HEAD
COPY requirements.txt /tmp/requirements.txt
RUN pip install --no-cache-dir -r /tmp/requirements.txt \
    && pip install --no-deps /opt/decbench
ENV DECBENCH_NO_CACHE=1
ENV RUST_JOERN_LIBRARY=/opt/rust-joern/target/release/librust_joern.so
WORKDIR /workspace
COPY . /tests/
