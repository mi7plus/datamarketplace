//! SQS worker pool (async invocation path). Consumes ingest jobs, runs the
//! pipeline, posts the result callback, then deletes the message. Poison messages
//! are left for SQS redrive to the DLQ (configured in infra, P5).
//!
//! Idempotency: jobs are keyed by submission_id + content_hash; reprocessing is
//! safe (staging is delete-then-COPY; the Python callback is a no-op if already
//! processed), so at-least-once SQS delivery is fine.

use crate::callback::Callback;
use crate::config::Config;
use crate::contract::IngestRequest;
use crate::pipeline::Pipeline;
use aws_sdk_sqs::Client as SqsClient;
use std::sync::Arc;

pub async fn run_workers(cfg: Config, pipeline: Pipeline, callback: Callback) {
    let queue_url = match &cfg.sqs_queue_url {
        Some(u) => u.clone(),
        None => {
            tracing::info!("no INGEST_SQS_QUEUE_URL — running sync-only (no workers)");
            return;
        }
    };

    let mut loader = aws_config::defaults(aws_config::BehaviorVersion::latest());
    if let Some(ep) = &cfg.s3_endpoint {
        loader = loader.endpoint_url(ep);
    }
    let shared = loader.load().await;
    let sqs = Arc::new(SqsClient::new(&shared));

    tracing::info!(concurrency = cfg.worker_concurrency, "starting SQS worker pool");
    let mut handles = Vec::new();
    for worker_id in 0..cfg.worker_concurrency {
        let sqs = sqs.clone();
        let queue_url = queue_url.clone();
        let pipeline = pipeline.clone();
        let callback = callback.clone();
        handles.push(tokio::spawn(async move {
            worker_loop(worker_id, sqs, queue_url, pipeline, callback).await;
        }));
    }
    for h in handles {
        let _ = h.await;
    }
}

async fn worker_loop(
    worker_id: usize,
    sqs: Arc<SqsClient>,
    queue_url: String,
    pipeline: Pipeline,
    callback: Callback,
) {
    loop {
        let recv = sqs
            .receive_message()
            .queue_url(&queue_url)
            .max_number_of_messages(1)
            .wait_time_seconds(20) // long poll
            .visibility_timeout(900) // 15 min for large media
            .send()
            .await;

        let messages = match recv {
            Ok(r) => r.messages.unwrap_or_default(),
            Err(e) => {
                tracing::warn!(worker_id, error = %e, "sqs receive failed; backing off");
                tokio::time::sleep(std::time::Duration::from_secs(5)).await;
                continue;
            }
        };

        for msg in messages {
            let body = msg.body.clone().unwrap_or_default();
            let receipt = msg.receipt_handle.clone();

            match serde_json::from_str::<IngestRequest>(&body) {
                Ok(req) => {
                    match process_one(&pipeline, &callback, &req).await {
                        Ok(()) => {
                            // Success -> delete so it isn't redelivered.
                            if let Some(rh) = receipt {
                                let _ = sqs
                                    .delete_message()
                                    .queue_url(&queue_url)
                                    .receipt_handle(rh)
                                    .send()
                                    .await;
                            }
                        }
                        Err(e) => {
                            // Leave the message; SQS redrive -> DLQ after maxReceiveCount.
                            tracing::error!(worker_id, job = %req.job_id, error = %e,
                                "job failed; leaving for redrive/DLQ");
                        }
                    }
                }
                Err(e) => {
                    // Unparseable poison message -> delete (it can never succeed).
                    tracing::error!(worker_id, error = %e, "undecodable message; dropping");
                    if let Some(rh) = receipt {
                        let _ = sqs
                            .delete_message()
                            .queue_url(&queue_url)
                            .receipt_handle(rh)
                            .send()
                            .await;
                    }
                }
            }
        }
    }
}

async fn process_one(
    pipeline: &Pipeline,
    callback: &Callback,
    req: &IngestRequest,
) -> anyhow::Result<()> {
    let report = pipeline.run(req).await?;
    callback.post_result(&report).await?;
    Ok(())
}
