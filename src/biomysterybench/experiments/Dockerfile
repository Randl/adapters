# Reconstructed from the author tool inventory. Build/solve not yet executed.
# Freeze the resolved image digest and package list before collecting scores.
FROM mambaorg/micromamba:2.9.0
USER root
RUN apt-get update && apt-get install -y --no-install-recommends \
    bash curl git wget vim build-essential libcairo2-dev libgl1 \
    && rm -rf /var/lib/apt/lists/*
COPY environment.yaml /tmp/environment.yaml
RUN micromamba install --yes --name base --file /tmp/environment.yaml \
    && micromamba clean --all --yes
ENV PATH="/opt/conda/bin:${PATH}"
WORKDIR /workspace
COPY data/ /workspace/data/
