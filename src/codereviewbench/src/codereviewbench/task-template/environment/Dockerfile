FROM python:3.12.13-slim-bookworm@sha256:4766d8b510c428e595d74b9cc5bbb2fae8e26316fffb4adc89908d79aacd58a2 AS source
RUN apt-get update && apt-get install -y --no-install-recommends git ca-certificates \
    && rm -rf /var/lib/apt/lists/*
WORKDIR /checkout
RUN git init . && git remote add origin https://github.com/{repo}.git \
    && git fetch --depth 1 origin {head} {base} \
    && mkdir -p /snapshot/repo \
    && git --work-tree=/snapshot/repo checkout {head} -- .
RUN git diff --no-ext-diff {base} {head} > /snapshot/change.diff \
    && test -z "$(find /snapshot -name .git -print -quit)"

# Copy only the current tracked tree and review diff. No Git objects, refs,
# reflogs, remotes, previous checkouts, or source-stage layers reach this image.
FROM python:3.12.13-slim-bookworm@sha256:4766d8b510c428e595d74b9cc5bbb2fae8e26316fffb4adc89908d79aacd58a2
RUN apt-get update && apt-get install -y --no-install-recommends tmux asciinema \
    && rm -rf /var/lib/apt/lists/* \
    && useradd --create-home --uid 1000 reviewer \
    && mkdir -p /workspace && chown reviewer:reviewer /workspace
COPY --from=source /snapshot/ /workspace/
RUN chown reviewer:reviewer /workspace
USER reviewer
WORKDIR /workspace/repo
