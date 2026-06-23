//! Per-job metrics (P5). Prometheus exporter on a side port; counters/histograms
//! for throughput and failures. Queue-backlog alerting is wired in infra against
//! SQS `ApproximateNumberOfMessagesVisible`.

use crate::config::Config;
use metrics_exporter_prometheus::PrometheusBuilder;
use std::net::SocketAddr;

pub fn init(cfg: &Config) {
    let addr: SocketAddr = cfg
        .metrics_addr
        .parse()
        .unwrap_or_else(|_| "0.0.0.0:9090".parse().unwrap());
    if let Err(e) = PrometheusBuilder::new()
        .with_http_listener(addr)
        .install()
    {
        tracing::warn!(error = %e, "prometheus exporter failed to start");
    }
}

pub fn record_job(modality: &str, duration_secs: f64, ok: bool) {
    metrics::counter!("ingest_jobs_total", "modality" => modality.to_string(),
        "result" => if ok { "ok" } else { "error" }.to_string())
        .increment(1);
    metrics::histogram!("ingest_job_duration_seconds", "modality" => modality.to_string())
        .record(duration_secs);
}

pub fn record_records(n: i64) {
    metrics::counter!("ingest_records_total").increment(n.max(0) as u64);
}
