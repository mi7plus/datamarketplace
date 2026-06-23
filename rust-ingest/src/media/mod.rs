//! Media ingest (P3): format/corruption validation, metadata, perceptual hashing.
//!
//! Dedup discipline from the plan: tabular dedup is exact-key SQL equality;
//! media dedup is DIFFERENT — start with EXACT-FILE dedup (`dataset_hash`) and
//! treat perceptual near-dup search as a deliberate follow-up over Hamming space
//! (BK-tree / pgvector bit-distance), NOT a reuse of the tabular anti-join.
//!
//! This module computes the perceptual hash (so the index can be built later) but
//! does not itself do approximate nearest-neighbor search.

pub mod audio;
pub mod ffmpeg;
pub mod image;

use crate::contract::{MediaMeta, Modality, PerceptualHashes};

pub struct MediaOutput {
    pub meta: MediaMeta,
    pub perceptual: PerceptualHashes,
    pub errors: Vec<String>,
}

/// Validate + fingerprint a media object by modality. Never fails hard on a
/// corrupt file — it reports `corrupt: true` so Python can REJECT_INVALID.
pub fn process_media(modality: Modality, bytes: &[u8]) -> MediaOutput {
    match modality {
        Modality::Image => image::process(bytes),
        Modality::Audio => audio::process(bytes),
        Modality::Video => ffmpeg::process_video(bytes),
        Modality::Tabular => MediaOutput {
            meta: MediaMeta::default(),
            perceptual: PerceptualHashes::default(),
            errors: vec!["process_media called with tabular modality".into()],
        },
    }
}
