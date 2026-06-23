//! The Python <-> Rust JSON contract (P0).
//!
//! Request: what the orchestrator hands a worker (or the sync endpoint).
//! Report:  the deterministic result Rust produces. Python takes the hashes and
//!          does the locked allocation itself — Rust never decides what's paid.
//!
//! These structs are the single source of truth for the wire format; the Python
//! side (`app/ingest_client.py`, `app/internal.py`) mirrors them.

use serde::{Deserialize, Serialize};

/// A column in the request spec (mirrors the Python spec `columns[]`).
#[derive(Clone, Debug, Deserialize, Serialize)]
pub struct SpecColumn {
    pub name: String,
    #[serde(rename = "type")]
    pub col_type: String,
    #[serde(default = "default_true")]
    pub required: bool,
}

fn default_true() -> bool {
    true
}

/// The request spec. `unique_key` drives dedup-key hashing.
#[derive(Clone, Debug, Default, Deserialize, Serialize)]
pub struct Spec {
    #[serde(default)]
    pub columns: Vec<SpecColumn>,
    #[serde(default)]
    pub unique_key: Vec<String>,
}

/// Modality of the source object.
#[derive(Clone, Copy, Debug, Deserialize, Serialize, PartialEq, Eq)]
#[serde(rename_all = "lowercase")]
pub enum Modality {
    Tabular,
    Image,
    Audio,
    Video,
}

impl Default for Modality {
    fn default() -> Self {
        Modality::Tabular
    }
}

/// Inbound job. `job_id` = submission_id + content_hash for idempotency.
#[derive(Clone, Debug, Deserialize, Serialize)]
pub struct IngestRequest {
    pub job_id: String,
    pub submission_id: String,
    pub s3_key: String,
    /// Original filename (drives CSV vs JSONL selection, like Python).
    #[serde(default)]
    pub filename: String,
    #[serde(default)]
    pub content_hash: String,
    #[serde(default)]
    pub modality: Modality,
    #[serde(default)]
    pub spec: Option<Spec>,
}

/// Validation status, mirroring the Python lifecycle vocabulary.
#[derive(Clone, Copy, Debug, Deserialize, Serialize, PartialEq, Eq)]
#[serde(rename_all = "SCREAMING_SNAKE_CASE")]
pub enum IngestStatus {
    Validated,
    RejectedInvalid,
}

/// Per-record statistics surfaced to the buyer (matches Python `stats`).
#[derive(Clone, Debug, Default, Deserialize, Serialize)]
pub struct Stats {
    pub conformance_rate: f64,
    pub duplicate_density: f64,
    pub null_rate: f64,
    pub quality_score: f64,
}

/// Media format metadata (P3).
#[derive(Clone, Debug, Default, Deserialize, Serialize)]
pub struct MediaMeta {
    pub container: Option<String>,
    pub codec: Option<String>,
    pub width: Option<u32>,
    pub height: Option<u32>,
    pub duration_secs: Option<f64>,
    pub corrupt: bool,
}

/// Perceptual hashes (P3). Hex-encoded; Hamming distance compares near-dupes.
#[derive(Clone, Debug, Default, Deserialize, Serialize)]
pub struct PerceptualHashes {
    /// pHash for images (hex).
    pub phash: Option<String>,
    /// Chromaprint-style audio fingerprint (hex), when computed.
    pub audio_fingerprint: Option<String>,
}

/// The deterministic report. `key_hash_ref` points at the staging artifact /
/// table rather than inlining millions of hashes (scaling fix from the plan).
#[derive(Clone, Debug, Default, Deserialize, Serialize)]
pub struct IngestReport {
    pub job_id: String,
    pub submission_id: String,
    #[serde(skip_serializing_if = "Option::is_none")]
    pub status: Option<IngestStatusWrapper>,
    pub validated_amount: i64,
    pub dataset_hash: String,
    pub duplicate_rows: i64,
    pub rejected_rows: i64,
    pub total_rows: i64,
    pub quality_score: f64,
    pub stats: Stats,
    /// First N conforming rows, formula-neutralized (preview).
    pub sample: Vec<serde_json::Value>,
    /// Where normalized key hashes were staged: "staging-table" or an S3 key.
    #[serde(skip_serializing_if = "Option::is_none")]
    pub key_hash_ref: Option<String>,
    /// Count of staged key hashes (== validated_amount when unique_key present).
    pub key_hash_count: i64,
    #[serde(skip_serializing_if = "Option::is_none")]
    pub media_meta: Option<MediaMeta>,
    #[serde(skip_serializing_if = "Option::is_none")]
    pub perceptual_hashes: Option<PerceptualHashes>,
    #[serde(default)]
    pub errors: Vec<String>,
}

// serde can't rename_all an enum *and* keep it Optional cleanly inline, so wrap.
#[derive(Clone, Copy, Debug, Deserialize, Serialize)]
pub struct IngestStatusWrapper(pub IngestStatus);

impl IngestReport {
    pub fn set_status(&mut self, s: IngestStatus) {
        self.status = Some(IngestStatusWrapper(s));
    }
}
