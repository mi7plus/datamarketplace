//! Async queue worker (P4). Compiled only with `--features queue` (the deploy
//! image); the default build stays AWS-SDK-free.
//!
//! Loop: long-poll SQS → fetch the S3 object → run the SAME `ingest` core →
//! bulk-`COPY` the normalized key hashes into `submission_key_staging` → POST the
//! report to Python's `/internal/ingest-result` → delete the SQS message only on
//! success (failures fall back to the queue's visibility-timeout retry, then the
//! DLQ after maxReceiveCount). Idempotent: jobs are keyed by submission_id +
//! content_hash; the Python callback no-ops once a submission leaves PENDING and
//! skips staging if the worker already wrote it.
//!
//! GUARDRAIL: the worker writes ONLY derived artifacts + the staging table. It
//! never touches money/lifecycle rows — Python remains the sole core-schema writer.

use std::time::Duration;

use serde::Deserialize;

use crate::{ingest_limited, Limits, Spec};

#[derive(Debug, Deserialize)]
struct Job {
    submission_id: String,
    s3_key: String,
    filename: String,
    #[serde(default)]
    spec: Option<Spec>,
    #[serde(default)]
    content_hash: Option<String>,
}

fn env(key: &str) -> String {
    std::env::var(key).unwrap_or_else(|_| panic!("worker requires env {key}"))
}

pub async fn run() {
    let cfg = aws_config::load_defaults(aws_config::BehaviorVersion::latest()).await;
    let sqs = aws_sdk_sqs::Client::new(&cfg);
    let s3 = aws_sdk_s3::Client::new(&cfg);

    let queue_url = env("INGEST_QUEUE_URL");
    let bucket = env("S3_BUCKET");
    let py_base = env("PY_INTERNAL_BASE"); // e.g. http://app.internal:8000
    let secret = env("INGEST_CALLBACK_SECRET");
    let limits = Limits::from_env();

    let db = sqlx::postgres::PgPoolOptions::new()
        .max_connections(4)
        .connect(&env("DATABASE_URL"))
        .await
        .expect("connect Postgres");
    let http = reqwest::Client::new();

    tracing::info!("ingest worker polling {queue_url}");
    loop {
        let resp = sqs
            .receive_message()
            .queue_url(&queue_url)
            .max_number_of_messages(5)
            .wait_time_seconds(20) // long poll
            .send()
            .await;
        let messages = match resp {
            Ok(r) => r.messages.unwrap_or_default(),
            Err(e) => {
                tracing::error!("sqs receive failed: {e}");
                tokio::time::sleep(Duration::from_secs(5)).await;
                continue;
            }
        };
        for msg in messages {
            let body = msg.body.clone().unwrap_or_default();
            match handle(&body, &s3, &bucket, &db, &http, &py_base, &secret, &limits).await {
                Ok(()) => {
                    if let Some(rh) = msg.receipt_handle() {
                        let _ = sqs
                            .delete_message()
                            .queue_url(&queue_url)
                            .receipt_handle(rh)
                            .send()
                            .await;
                    }
                }
                // Leave the message: visibility timeout → retry → DLQ after maxReceiveCount.
                Err(e) => tracing::error!("job failed (will retry/DLQ): {e}"),
            }
        }
    }
}

#[allow(clippy::too_many_arguments)]
async fn handle(
    body: &str,
    s3: &aws_sdk_s3::Client,
    bucket: &str,
    db: &sqlx::PgPool,
    http: &reqwest::Client,
    py_base: &str,
    secret: &str,
    limits: &Limits,
) -> Result<(), String> {
    let job: Job = serde_json::from_str(body).map_err(|e| format!("bad job json: {e}"))?;

    let obj = s3
        .get_object()
        .bucket(bucket)
        .key(&job.s3_key)
        .send()
        .await
        .map_err(|e| format!("s3 get {}: {e}", job.s3_key))?;
    let bytes = obj
        .body
        .collect()
        .await
        .map_err(|e| format!("s3 body: {e}"))?
        .into_bytes();

    let spec = job.spec.clone().unwrap_or_default();
    let report = ingest_limited(&bytes, &job.filename, &spec, limits);

    // Bulk-write the dedup staging rows (the scale win: hashes go to the table,
    // not through the callback JSON). Idempotent: replace this submission's rows.
    let mut tx = db.begin().await.map_err(|e| e.to_string())?;
    sqlx::query("DELETE FROM submission_key_staging WHERE submission_id = $1::uuid")
        .bind(&job.submission_id)
        .execute(&mut *tx)
        .await
        .map_err(|e| e.to_string())?;
    for (i, kh) in report.key_hashes.iter().enumerate() {
        sqlx::query(
            "INSERT INTO submission_key_staging (id, submission_id, ordinal, key_hash) \
             VALUES (gen_random_uuid(), $1::uuid, $2, $3)",
        )
        .bind(&job.submission_id)
        .bind(i as i32)
        .bind(kh)
        .execute(&mut *tx)
        .await
        .map_err(|e| e.to_string())?;
    }
    tx.commit().await.map_err(|e| e.to_string())?;

    // Hand the report to Python — the sole writer to money/lifecycle tables.
    let payload = serde_json::json!({
        "submission_id": job.submission_id,
        "content_hash": job.content_hash.unwrap_or_else(|| report.dataset_hash.clone()),
        "report": report,
    });
    let resp = http
        .post(format!("{py_base}/internal/ingest-result"))
        .header("X-Internal-Secret", secret)
        .json(&payload)
        .send()
        .await
        .map_err(|e| format!("callback: {e}"))?;
    if !resp.status().is_success() {
        return Err(format!("callback status {}", resp.status()));
    }
    Ok(())
}
