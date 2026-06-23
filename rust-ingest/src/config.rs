//! Runtime configuration, read once from the environment at startup.
//!
//! Mirrors the Python service's env conventions (S3_BUCKET, DATABASE_URL, etc.)
//! so the two halves deploy from the same secret set.

use std::env;

#[derive(Clone, Debug)]
pub struct Config {
    /// HTTP bind address for the sync path + /health.
    pub bind_addr: String,
    /// S3 bucket holding source files + derived artifacts.
    pub s3_bucket: String,
    /// Optional custom endpoint (MinIO in dev). Empty = real AWS.
    pub s3_endpoint: Option<String>,
    /// SQS queue URL the worker pool consumes. Empty = sync-only (no workers).
    pub sqs_queue_url: Option<String>,
    /// Number of concurrent SQS consumer tasks.
    pub worker_concurrency: usize,
    /// Postgres URL — used ONLY for COPY into submission_key_staging.
    pub database_url: Option<String>,
    /// Base URL of the Python orchestrator for the result callback.
    pub callback_base_url: String,
    /// Shared secret asserted on the internal callback (matches Python side).
    pub internal_token: String,
    /// Hard cap on a single source file (decompression-bomb / oversize guard, P5).
    pub max_file_bytes: usize,
    /// Prometheus metrics bind address.
    pub metrics_addr: String,
}

impl Config {
    pub fn from_env() -> Self {
        Config {
            bind_addr: env::var("INGEST_BIND_ADDR").unwrap_or_else(|_| "0.0.0.0:8088".into()),
            s3_bucket: env::var("S3_BUCKET").unwrap_or_else(|_| "datamarketplace".into()),
            s3_endpoint: non_empty(env::var("S3_ENDPOINT_URL").ok()),
            sqs_queue_url: non_empty(env::var("INGEST_SQS_QUEUE_URL").ok()),
            worker_concurrency: env::var("INGEST_WORKER_CONCURRENCY")
                .ok()
                .and_then(|v| v.parse().ok())
                .unwrap_or(4),
            database_url: non_empty(env::var("DATABASE_URL").ok()),
            callback_base_url: env::var("INGEST_CALLBACK_BASE_URL")
                .unwrap_or_else(|_| "http://localhost:3001".into()),
            internal_token: env::var("INGEST_INTERNAL_TOKEN").unwrap_or_default(),
            max_file_bytes: env::var("INGEST_MAX_FILE_BYTES")
                .ok()
                .and_then(|v| v.parse().ok())
                .unwrap_or(100 * 1024 * 1024), // 100 MB, matches Python MAX_FILE_BYTES
            metrics_addr: env::var("INGEST_METRICS_ADDR").unwrap_or_else(|_| "0.0.0.0:9090".into()),
        }
    }
}

fn non_empty(v: Option<String>) -> Option<String> {
    v.filter(|s| !s.trim().is_empty())
}
