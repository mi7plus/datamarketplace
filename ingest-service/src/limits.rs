//! File-safety limits (P5): reject oversize uploads and decompression/pixel bombs
//! BEFORE doing heavy work, so a hostile file can't exhaust memory. These run in
//! the ingest service — the natural home for the security plan's file-safety caps.
//!
//! Limits are resolved from env once (`Limits::from_env`) but every check takes
//! them as a parameter, so tests are deterministic (no global env mutation/races).

use serde_json::json;

use crate::contract::{IngestReport, IngestStatus};
use crate::keys::dataset_hash;

#[derive(Debug, Clone, Copy)]
pub struct Limits {
    /// Max raw upload size in bytes.
    pub max_bytes: usize,
    /// Max decoded image pixels (width × height) — guards pixel/decompression bombs.
    pub max_image_pixels: u64,
}

impl Default for Limits {
    fn default() -> Self {
        // 2 GiB upload (a large video still fits), 100 MP image.
        Limits {
            max_bytes: 2 * 1024 * 1024 * 1024,
            max_image_pixels: 100_000_000,
        }
    }
}

impl Limits {
    pub fn from_env() -> Self {
        let d = Limits::default();
        Limits {
            max_bytes: env_usize("MAX_UPLOAD_BYTES", d.max_bytes),
            max_image_pixels: env_u64("MAX_IMAGE_PIXELS", d.max_image_pixels),
        }
    }
}

fn env_usize(k: &str, default: usize) -> usize {
    std::env::var(k)
        .ok()
        .and_then(|v| v.parse().ok())
        .unwrap_or(default)
}
fn env_u64(k: &str, default: u64) -> u64 {
    std::env::var(k)
        .ok()
        .and_then(|v| v.parse().ok())
        .unwrap_or(default)
}

/// A uniform REJECTED report for a file-safety violation (records the dataset
/// hash so the rejection is still auditable/idempotent).
pub fn rejected(bytes: &[u8], reason: impl Into<String>) -> IngestReport {
    let msg = reason.into();
    IngestReport {
        status: IngestStatus::RejectedInvalid,
        validated_amount: 0,
        dataset_hash: dataset_hash(bytes),
        quality_score: 0.0,
        sample: vec![],
        key_hashes: vec![],
        validation_report: json!({ "error": msg, "rejected_by": "file-safety" }),
        key_hash_ref: None,
        sample_ref: None,
        media_meta: None,
        perceptual_hashes: None,
        errors: vec![msg],
    }
}
