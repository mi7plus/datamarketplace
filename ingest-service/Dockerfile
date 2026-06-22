# Rowbound ingest service (Rust) — production image, built WITH the queue worker.
# One image serves both roles: default cmd = HTTP service; `worker` arg = SQS consumer.
FROM rust:1.96-slim AS build
RUN apt-get update && apt-get install -y --no-install-recommends pkg-config && rm -rf /var/lib/apt/lists/*
WORKDIR /src
COPY Cargo.toml Cargo.lock ./
COPY src ./src
COPY tests ./tests
# --features queue pulls in aws-sdk/sqlx/reqwest for the worker path.
RUN cargo build --release --features queue

FROM debian:bookworm-slim
RUN apt-get update && apt-get install -y --no-install-recommends ca-certificates curl && rm -rf /var/lib/apt/lists/*
COPY --from=build /src/target/release/rowbound-ingest /usr/local/bin/rowbound-ingest
RUN useradd -m -u 10001 appuser
USER appuser
EXPOSE 8081
HEALTHCHECK --interval=30s --timeout=5s --start-period=20s --retries=3 \
  CMD curl -fsS http://localhost:8081/health || exit 1
# Default: HTTP service. Override with ["rowbound-ingest","worker"] for the worker.
CMD ["rowbound-ingest"]
