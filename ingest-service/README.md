# rowbound-ingest (Rust)

Heavy per-record compute for Rowbound — tabular validation, normalized key
hashing, dedup-hash + sample extraction. Built to grow into media
(validation/transcode/perceptual hashing) per `rowbound-rust-ingest-service-plan.md`.

## The one rule

**Rust computes, Python settles.** This service is stateless: it reads a source
file, returns a deterministic report, and may write *derived* artifacts. It
**never** touches money/lifecycle tables, never decides what is accepted, never
moves funds. Python takes the `key_hashes` and does the locked allocation / cap /
`AcceptedKey` overlap inside its existing Postgres transaction — unchanged.

## Status (phased build)

| Phase | State | Notes |
|---|---|---|
| P0 contract + skeleton | ✅ | `axum` `/health` + sync `POST /ingest`; serde contract in `contract.rs`. |
| P1 tabular port + parity | ✅ | Port of `app/ingest.py`; **byte-identical hash parity** with Python proven (`tests/parity.rs` + live shadow check). Cut-over NOT done — Python ingest is still the live path. |
| P2 staging anti-join cut-over | ⛔ deferred | Needs the `submission_key_staging` table + the Python `EXCEPT` anti-join + the `/internal/ingest-result` callback. Touches the live path — do behind a flag with shadow parity first. |
| P3 media | ⛔ deferred | image/audio validation, transcode (ffmpeg), perceptual hashing. Net new. |
| P4 deploy | partial | Rust CI job added (`.github/workflows/ci.yml`). ECR/Fargate/SQS/IAM = the AWS plan. |
| P5 hardening/obs | ⛔ deferred | DLQ, metrics, decompression-bomb caps. |

## Run / test

```bash
cargo test                              # incl. Python-parity hashes
cargo clippy --all-targets -- -D warnings
cargo fmt --check
PORT=8081 cargo run                     # then POST /ingest
```

`POST /ingest` (synchronous dev/small-file path) body:

```json
{ "filename": "data.csv",
  "spec": { "columns": [{"name":"email","type":"string"}], "unique_key": ["email"] },
  "content_b64": "<base64 of the file>" }
```

returns an `IngestReport` (`status`, `validated_amount`, `dataset_hash`,
`quality_score`, `sample`, `key_hashes`, `validation_report`). The async queue
path (SQS → S3 → POST `/internal/ingest-result`) shares the same `validate_dataset`
core so large media never blocks a request — sketched in `src/main.rs`, wired in P2/P4.

## Parity is load-bearing

The cross-source dedup anti-join only works if a record hashes identically here
and in Python. `keys.rs` reproduces Python's `sha256(repr(normalized_tuple))`
exactly (1-tuple trailing comma, quote selection, control-char escapes). The
`tests/parity.rs` hashes are captured from the live Python `app/keys.py`; if
either side's normalization changes, CI fails. Float-typed *key* columns are the
one documented residual edge (Python `str(float)` repr) — P1 shadow mode is the
backstop before any cut-over.
