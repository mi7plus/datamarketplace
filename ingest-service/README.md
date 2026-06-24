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
| P2 staging anti-join + callback | ✅ Python side | `submission_key_staging` table + migration, the `EXCEPT` anti-join in `accept_submission` (flag `USE_STAGING_DEDUP`, in-Python fallback default), and `POST /internal/ingest-result` (idempotent, secret-gated) all landed in the backend with tests. Remaining: the Rust worker bulk-`COPY` into staging + the queue wiring (P4), and flipping the flag on after a shadow window. |
| P3 media — images | ✅ | `media.rs`: image validate (format/dimensions/corruption) + metadata + gradient perceptual hash + **exact-file dedup**. Tests: validation, exact-file dedup, corruption reject, near-dup < far-dup. |
| P3 media — audio/video | ✅ | `av.rs` shells out to **ffprobe** (validate + codec/duration/resolution metadata), **fpcalc** (Chromaprint audio fingerprint), **ffmpeg** (JPEG thumbnail). `tests/av.rs` generates fixtures with the local ffmpeg and self-skips if the binaries are absent. Prod image installs `ffmpeg`+`libchromaprint-tools`; tests point `MediaTools` at a gitignored `.bin/`. Still exact-file dedup. |
| P3 perceptual near-dup search | ✅ | `neardup.rs`: BK-tree over Hamming distance of image perceptual hashes — `insert(hash, id)` + `query(hash, max_distance)` (nearest-first) + `contains_near`. Detection only — does NOT touch allocation (exact-file `dataset_hash` stays the dedup key). Tests: near-dup found within threshold, unrelated not, exact = distance 0. Audio Chromaprint near-dup (correlation-based) is a separate problem, not this index. |
| P4 deploy | ✅ scaffolded | Worker SQS/S3/callback loop in `src/worker.rs` behind the `queue` feature (compiles + clippy-clean; built into the deploy image via `Dockerfile --features queue`). Terraform in `infra/ingest.tf`: own ECR repo, SQS queue + DLQ, HTTP service + autoscaling worker pool (scales on queue backlog), IAM scoped to the bucket + queue (no money tables). `terraform validate` passes. Not applied (no AWS account here). |
| P5 file-safety caps | ✅ | `limits.rs`: oversize-upload + image pixel-bomb rejection (header-only dimension read, before decode). Configurable via `MAX_UPLOAD_BYTES` / `MAX_IMAGE_PIXELS`; tested. Deferred (need the queue): DLQ for poison jobs, per-job metrics, queue-backlog alerts. |

## Media binaries (local dev)

The audio/video path shells out to `ffprobe`/`ffmpeg`/`fpcalc`. In prod they're in
the image (`apt-get install ffmpeg libchromaprint-tools`). Locally, drop the
executables in `ingest-service/.bin/` (gitignored) — FFmpeg from ffmpeg.org's
recommended Windows build, `fpcalc` from the AcoustID Chromaprint releases — or
install them on PATH. `tests/av.rs` self-skips when they're missing. Override paths
with `FFPROBE_BIN` / `FFMPEG_BIN` / `FPCALC_BIN`.

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
