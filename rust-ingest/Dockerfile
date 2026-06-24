# Multi-stage build for the Rowbound ingest service.
# Media workers need ffmpeg/ffprobe present at runtime (P3 transcode/thumbnail).

FROM rust:1.81-bookworm AS build
WORKDIR /app
# Cache deps: copy manifests first, then sources.
COPY Cargo.toml Cargo.lock* ./
RUN mkdir src && echo "fn main() {}" > src/main.rs && echo "" > src/lib.rs \
    && cargo build --release || true
COPY src ./src
COPY tests ./tests
RUN touch src/main.rs src/lib.rs && cargo build --release

FROM debian:bookworm-slim AS runtime
RUN apt-get update \
    && apt-get install -y --no-install-recommends ffmpeg ca-certificates \
    && rm -rf /var/lib/apt/lists/*
COPY --from=build /app/target/release/rowbound-ingest /usr/local/bin/rowbound-ingest

# Non-root.
RUN useradd -r -u 10001 ingest
USER ingest

EXPOSE 8088 9090
ENTRYPOINT ["/usr/local/bin/rowbound-ingest"]
