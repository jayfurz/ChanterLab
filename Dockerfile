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

# These empty mount points are populated at deployment time. The catalog PVC
# mounts at omr/out; the four generated built-ins mount as individual content/
# files. No catalog or OMR pipeline material is baked into this image.
RUN mkdir -p /srv/chanterlab/training-prototype/omr/out \
             /opt/chanterlab-server \
    && chown -R 65532:65532 /srv/chanterlab /opt/chanterlab-server

# Open question for the migration owner: byzorgan-web-server.py is host-owned
# and absent from this repository. Until it is moved into a versioned build
# context, the tenant deployment must inject that single file read-only at the
# following path (for example with a ConfigMap volume). It must honor WEBROOT.
USER 65532:65532
ENTRYPOINT ["python3", "/opt/chanterlab-server/byzorgan-web-server.py"]
