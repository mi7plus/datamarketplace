# rowbound-ingest

Standalone Rust ingest/dedup/media service. Implements
`rowbound-rust-ingest-service-plan.md`.

> **The discipline that makes this safe: Rust computes, Python settles.**
> This service does pure, stateless heavy computation (parse, validate, hash,
> media crunch). It **never** touches money/lifecycle tables and never decides
> what's accepted — it returns a deterministic report and the Python orchestrator
> does the locked allocation. The only DB write it makes is bulk-COPY into the
> `submission_key_staging` table.

## ⚠️ Unverified build status

This crate was written without a Rust toolchain available in the authoring
environment, so it has **not been compiled, `clippy`'d, or `cargo test`'d yet**.
Treat the first `cargo build` as part of review. Run:

```bash
cd rust-ingest
cargo fmt --all
cargo clippy --all-targets -- -D warnings
cargo test --all
cargo build --release
```

The CI job (`.github/workflows/ci.yml` → `rust-ingest`) runs exactly these.

## Architecture

```
src/
  main.rs        axum server: /health + sync /ingest; spawns SQS workers
  config.rs      env-driven config
  contract.rs    Python<->Rust JSON contract (IngestRequest / IngestReport)
  tabular.rs     P1: port of Python ingest.py (validate/hash/sample/stats)
  keys.rs        parity-critical: normalize + key_hash == Python app/keys.py
  media/         P3: image pHash, audio fingerprint scaffold, ffmpeg video
  storage.rs     S3/MinIO get source + put derived artifacts
  staging.rs     P2: COPY normalized key hashes into submission_key_staging
  pipeline.rs    orchestrates a job (fetch -> compute -> stage -> report)
  queue.rs       SQS worker pool (async path)
  callback.rs    POST report to Python /internal/ingest-result
  metrics.rs     P5: Prometheus metrics
```

## Parity (P1)

`key_hash` must be **byte-identical** to Python's `app/keys.py`
(`sha256(repr(normalized_tuple))`) or cross-source dedup against existing
`AcceptedKey` rows breaks. `keys.rs` reproduces Python's tuple/`str` `repr`
(single-quote preference, single-element trailing comma, escaping) and is pinned
to the same **golden vectors** as `backend/tests/test_rust_parity.py`.

**Parity caveats** (covered by shadow tests, discouraged in keys):
- **Float keys:** Python `str(float)` vs Rust `{}` can differ (`1e-05`). Prefer
  string/integer unique keys.
- **Non-printable Unicode in keys:** `repr` escaping approximated for non-ASCII.

Run `INGEST_SHADOW_ENABLED=true` (Python side) to log any divergence on real
uploads before cutover (`INGEST_RUST_ENABLED=true`, P2).

## Run locally

```bash
# Against local MinIO + Postgres (staging table only):
export S3_ENDPOINT_URL=http://localhost:9000
export S3_BUCKET=local-bucket
export AWS_ACCESS_KEY_ID=minio AWS_SECRET_ACCESS_KEY=minio123
export DATABASE_URL=postgresql://postgres:pass@localhost:5432/datamarketplace
export INGEST_INTERNAL_TOKEN=dev-token
export INGEST_CALLBACK_BASE_URL=http://localhost:3001
cargo run --release
# Health: curl localhost:8088/health
```

Without `INGEST_SQS_QUEUE_URL` it runs **sync-only** (no workers); the `/ingest`
endpoint still works for small tabular files and shadow comparison.

## Deploy

See [`../RUST_INGEST_DEPLOY.md`](../RUST_INGEST_DEPLOY.md) — ECR + Fargate
service/workers + SQS + scoped IAM (belongs in the `rowbound-deploy/infra` repo).
