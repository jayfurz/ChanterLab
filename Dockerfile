# syntax=docker/dockerfile:1.7

ARG RUST_VERSION=1.93.0
ARG PYTHON_VERSION=3.13.5
ARG WASM_PACK_VERSION=0.14.0

FROM rust:${RUST_VERSION}-bookworm AS wasm-builder
ARG WASM_PACK_VERSION

RUN rustup target add wasm32-unknown-unknown \
    && cargo install wasm-pack --version "${WASM_PACK_VERSION}" --locked

WORKDIR /build
COPY Cargo.toml Cargo.lock ./
COPY src/ ./src/
COPY web/ ./web/
COPY training-prototype/ ./training-prototype/

# The training app consumes the same worklet-feature build as the legacy app.
# Build it once, then install the two runtime files at both URL locations.
RUN wasm-pack build --release --target web --out-dir web/pkg \
        -- --features main --no-default-features \
    && wasm-pack build --release --target no-modules --out-dir web/pkg-worklet \
        -- --features worklet --no-default-features \
    && mkdir -p training-prototype/pkg-worklet \
    && cp web/pkg-worklet/chanterlab_core.js \
          web/pkg-worklet/chanterlab_core_bg.wasm \
          training-prototype/pkg-worklet/ \
    && find web/pkg web/pkg-worklet training-prototype/pkg-worklet \
          -type f ! -name 'chanterlab_core.js' ! -name 'chanterlab_core_bg.wasm' \
          -delete

FROM python:${PYTHON_VERSION}-slim-bookworm AS runtime

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    WEBROOT=/srv/chanterlab/web

WORKDIR /srv/chanterlab
COPY --from=wasm-builder --chown=65532:65532 /build/web/ ./web/
COPY --from=wasm-builder --chown=65532:65532 /build/training-prototype/ ./training-prototype/
COPY --chown=65532:65532 server/byzorgan-web-server.py /opt/chanterlab-server/byzorgan-web-server.py
RUN python3 -c "import ast; ast.parse(open('/opt/chanterlab-server/byzorgan-web-server.py').read())"

# The catalog PVC mounts at /srv/chanterlab/data (a neutral path, not inside
# training-prototype/) and is populated at deployment time -- no catalog or
# OMR pipeline material is baked into this image.
#
# It carries two things a fresh git checkout cannot: the generated omr/out
# catalog, AND the 4 built-in content/*.musicxml pieces. Those 4 are
# gitignored (see training-prototype/omr/SOURCES.md -- covered by the same
# publication permission as the catalog, but treated identically: never
# committed, never in a CI build context). An earlier version of this
# Dockerfile tried to bake them in via .dockerignore; that only worked on a
# local build where the gitignored files happened to already be on disk --
# GitHub Actions' checkout never has them, since they're not tracked in git.
# Confirmed broken by deploying and testing: manifest.json and the other 4
# built-ins 404'd, only the tracked control_satb.musicxml (a real COPY, not
# a symlink) served. Symlinks here point INTO the single PVC mount instead.
RUN mkdir -p /srv/chanterlab/data/out /srv/chanterlab/data/content \
    && mkdir -p /srv/chanterlab/training-prototype/omr \
    && ln -s /srv/chanterlab/data/out /srv/chanterlab/training-prototype/omr/out \
    && for f in trisagion_omr trisagion_vector cherubic_vector anaphora_vector; do \
         ln -s "/srv/chanterlab/data/content/${f}.musicxml" \
               "/srv/chanterlab/training-prototype/content/${f}.musicxml"; \
       done \
    && chown -R 65532:65532 /srv/chanterlab /opt/chanterlab-server

USER 65532:65532
ENTRYPOINT ["python3", "/opt/chanterlab-server/byzorgan-web-server.py"]
