//! The Python ↔ Rust JSON contract.
//!
//! Request: a file (S3 key, or inline base64 for the dev/sync path) + a spec.
//! Report: deterministic validation output. The Rust side NEVER decides what is
//! accepted or paid — it only computes. Python takes `key_hashes` and does the
//! locked allocation/cap/overlap. Media fields are optional and unused until P3.

use serde::{Deserialize, Serialize};

#[derive(Debug, Clone, Deserialize)]
pub struct Column {
    pub name: String,
    #[serde(rename = "type")]
    pub col_type: String,
    #[serde(default = "default_true")]
    pub required: bool,
}

fn default_true() -> bool {
    true
}

#[derive(Debug, Clone, Default, Deserialize)]
pub struct Spec {
    #[serde(default)]
    pub columns: Vec<Column>,
    #[serde(default)]
    pub unique_key: Option<Vec<String>>,
}

/// Inbound job. `content_b64` carries the bytes on the synchronous dev path; in
/// the async/queue path this is instead fetched from `s3_key` (P2+).
#[derive(Debug, Clone, Deserialize)]
pub struct IngestRequest {
    pub filename: String,
    #[serde(default)]
    pub spec: Option<Spec>,
    #[serde(default)]
    pub s3_key: Option<String>,
    #[serde(default)]
    pub content_b64: Option<String>,
    #[serde(default)]
    pub job_id: Option<String>,
}

#[derive(Debug, Clone, Serialize, PartialEq)]
#[serde(rename_all = "SCREAMING_SNAKE_CASE")]
pub enum IngestStatus {
    Validated,
    RejectedInvalid,
}

/// The deterministic report. `key_hashes` is inline on the sync path; at scale
/// these are bulk-written to the staging table / an S3 artifact (`key_hash_ref`).
#[derive(Debug, Clone, Serialize)]
pub struct IngestReport {
    pub status: IngestStatus,
    pub validated_amount: u64,
    pub dataset_hash: String,
    pub quality_score: f64,
    pub sample: Vec<serde_json::Value>,
    pub key_hashes: Vec<String>,
    pub validation_report: serde_json::Value,
    #[serde(skip_serializing_if = "Option::is_none")]
    pub key_hash_ref: Option<String>,
    #[serde(skip_serializing_if = "Option::is_none")]
    pub sample_ref: Option<String>,
    // Media (P3) — absent for tabular.
    #[serde(skip_serializing_if = "Option::is_none")]
    pub media_meta: Option<serde_json::Value>,
    #[serde(skip_serializing_if = "Option::is_none")]
    pub perceptual_hashes: Option<Vec<String>>,
    pub errors: Vec<String>,
}
