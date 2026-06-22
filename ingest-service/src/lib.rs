//! Rowbound ingest service — pure, stateless heavy compute.
//!
//! GUARDRAIL (non-negotiable, see the plan): this crate computes and returns a
//! report. It NEVER touches money/lifecycle tables, never decides what is
//! accepted, never moves funds. Python takes `key_hashes` and does the locked
//! allocation/cap/overlap. Keep it that way.

pub mod contract;
pub mod keys;
pub mod limits;
pub mod media;
pub mod tabular;
#[cfg(feature = "queue")]
pub mod worker;

pub use contract::{IngestReport, IngestRequest, IngestStatus, Spec};
pub use limits::Limits;
pub use tabular::validate_dataset;

/// Dispatch a job by file type, applying env-configured file-safety limits.
pub fn ingest(bytes: &[u8], filename: &str, spec: &Spec) -> IngestReport {
    ingest_limited(bytes, filename, spec, &Limits::from_env())
}

/// Dispatch with explicit limits (deterministic — used by tests).
pub fn ingest_limited(bytes: &[u8], filename: &str, spec: &Spec, limits: &Limits) -> IngestReport {
    // Cheap oversize gate first — never load a hostile file into memory.
    if bytes.len() > limits.max_bytes {
        return limits::rejected(
            bytes,
            format!(
                "upload {} bytes exceeds limit {}",
                bytes.len(),
                limits.max_bytes
            ),
        );
    }
    if media::is_image(filename) {
        media::validate_image_limited(bytes, filename, limits.max_image_pixels)
    } else {
        validate_dataset(bytes, filename, spec)
    }
}
