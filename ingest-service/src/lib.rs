//! Rowbound ingest service — pure, stateless heavy compute.
//!
//! GUARDRAIL (non-negotiable, see the plan): this crate computes and returns a
//! report. It NEVER touches money/lifecycle tables, never decides what is
//! accepted, never moves funds. Python takes `key_hashes` and does the locked
//! allocation/cap/overlap. Keep it that way.

pub mod contract;
pub mod keys;
pub mod media;
pub mod tabular;

pub use contract::{IngestReport, IngestRequest, IngestStatus, Spec};
pub use tabular::validate_dataset;

/// Dispatch a job by file type: images → media path, else tabular.
pub fn ingest(bytes: &[u8], filename: &str, spec: &Spec) -> IngestReport {
    if media::is_image(filename) {
        media::validate_image(bytes, filename)
    } else {
        validate_dataset(bytes, filename, spec)
    }
}
