//! Result callback to the Python orchestrator (P0/async path).
//!
//! Workers POST the report to `/internal/ingest-result`; Python flips the
//! submission to VALIDATED/REJECTED_INVALID inside its own transaction (Python
//! stays the single writer to the core schema). The callback is idempotent on
//! the Python side, so retries are safe.

use crate::config::Config;
use crate::contract::IngestReport;
use anyhow::{Context, Result};

#[derive(Clone)]
pub struct Callback {
    http: reqwest::Client,
    url: String,
    token: String,
}

impl Callback {
    pub fn new(cfg: &Config) -> Self {
        Callback {
            http: reqwest::Client::new(),
            url: format!(
                "{}/internal/ingest-result",
                cfg.callback_base_url.trim_end_matches('/')
            ),
            token: cfg.internal_token.clone(),
        }
    }

    pub async fn post_result(&self, report: &IngestReport) -> Result<()> {
        let resp = self
            .http
            .post(&self.url)
            .header("X-Internal-Token", &self.token)
            .json(report)
            .send()
            .await
            .context("post ingest-result")?;

        if !resp.status().is_success() {
            let status = resp.status();
            let body = resp.text().await.unwrap_or_default();
            anyhow::bail!("callback rejected ({status}): {body}");
        }
        Ok(())
    }
}
