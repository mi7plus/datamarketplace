//! HTTP entrypoint (axum). Two surfaces:
//!
//! - `GET /health` — liveness for the ALB / container healthcheck.
//! - `POST /ingest` — synchronous tabular ingest (small files / dev). Body is an
//!   `IngestRequest` with `content_b64`; returns the `IngestReport`.
//!
//! The async queue path (SQS consumer → process S3 object → POST the report to
//! Python's /internal/ingest-result) is the default at scale and is sketched in
//! `run_worker` below — wired in P2/P4 with aws-sdk-{sqs,s3}. The HTTP and queue
//! paths share the same `validate_dataset` core, so a 2 GB video never blocks a
//! request. Either way: Rust computes, Python settles.

use axum::{
    extract::Json, http::StatusCode, response::IntoResponse, routing::get, routing::post, Router,
};
use base64::Engine;
use rowbound_ingest::{ingest as run_ingest, IngestRequest};
use serde_json::json;

#[tokio::main]
async fn main() {
    tracing_subscriber::fmt().with_target(false).init();
    let app = Router::new()
        .route("/health", get(|| async { Json(json!({"status": "ok"})) }))
        .route("/ingest", post(ingest));

    let port = std::env::var("PORT").unwrap_or_else(|_| "8081".into());
    let addr = format!("0.0.0.0:{port}");
    let listener = tokio::net::TcpListener::bind(&addr).await.expect("bind");
    tracing::info!("rowbound-ingest listening on {addr}");
    axum::serve(listener, app).await.expect("serve");
}

async fn ingest(Json(req): Json<IngestRequest>) -> impl IntoResponse {
    let bytes = match &req.content_b64 {
        Some(b64) => match base64::engine::general_purpose::STANDARD.decode(b64) {
            Ok(b) => b,
            Err(e) => {
                return (
                    StatusCode::BAD_REQUEST,
                    Json(json!({"error": format!("bad base64: {e}")})),
                )
                    .into_response()
            }
        },
        None => {
            // The queue path fetches from `s3_key`; the sync endpoint needs inline bytes.
            return (
                StatusCode::BAD_REQUEST,
                Json(json!({"error": "content_b64 required on the synchronous /ingest path (s3_key is for the queue path)"})),
            )
                .into_response();
        }
    };
    let spec = req.spec.clone().unwrap_or_default();
    let report = run_ingest(&bytes, &req.filename, &spec);
    (StatusCode::OK, Json(report)).into_response()
}

// ── Async queue worker (P2/P4) ───────────────────────────────────────────────
// Sketch only — compiled out until the aws-sdk deps land, so the skeleton builds
// and tests run with no AWS. Shape:
//
//   loop {
//       let msg = sqs.receive().await?;                 // {submission_id, s3_key, spec, content_hash}
//       let bytes = s3.get(msg.s3_key).await?;
//       let report = validate_dataset(&bytes, &name, &spec);
//       // bulk COPY report.key_hashes → submission_key_staging (staging table ONLY)
//       // write sample/artifacts to S3
//       http.post(format!("{PY}/internal/ingest-result"), &report).await?;  // idempotent
//       sqs.delete(msg).await?;                          // ack only after the callback succeeds
//   }
//
// Idempotency key: submission_id + content_hash. Poison messages → DLQ (P5).
