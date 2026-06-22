//! Media ingest (P3, first cut) — images.
//!
//! Per the plan: validate (format/dimensions/corruption), compute a perceptual
//! hash, and dedup on EXACT FILE (`dataset_hash`) for now. Perceptual *near-dup
//! search* is approximate-nearest-neighbour over hash space (Hamming distance) —
//! a different data structure (BK-tree / pgvector bit-distance), built as a
//! deliberate follow-up, NOT wired into the allocation path here. We compute and
//! return the perceptual hash so that follow-up has its input.
//!
//! A media submission is treated as a single asset: `validated_amount = 1` and
//! `key_hashes = [dataset_hash]`, so exact-file duplicates collapse in the SAME
//! per-record dedup anti-join the tabular path uses — no new settlement logic.
//!
//! Audio fingerprinting (symphonia + chromaprint-style) and ffmpeg
//! transcode/thumbnail are the external-binary parts; structured as follow-ups
//! (see `transcode_stub`) rather than built here.

use image_hasher::{HashAlg, HasherConfig, ImageHash};
use serde_json::json;

use crate::contract::{IngestReport, IngestStatus};
use crate::keys::dataset_hash;

const IMAGE_EXTS: [&str; 6] = ["png", "jpg", "jpeg", "gif", "bmp", "webp"];

pub fn is_image(filename: &str) -> bool {
    let ext = filename.rsplit('.').next().unwrap_or("").to_lowercase();
    IMAGE_EXTS.contains(&ext.as_str())
}

/// Gradient ("dHash") perceptual hash: thresholds each pixel against its
/// neighbour, so it's robust to brightness/contrast shifts and near-duplicates
/// land within a small Hamming distance, while different images diverge. (The
/// DCT "pHash" variant is available via `.preproc_dct()` but produced degenerate
/// output for low-frequency inputs at this hash size — gradient is the reliable
/// default; DCT tuning is a follow-up.) Returns the base64 form for the report.
fn phash(img: &image::DynamicImage) -> ImageHash {
    HasherConfig::new()
        .hash_size(8, 8)
        .hash_alg(HashAlg::Gradient)
        .to_hasher()
        .hash_image(img)
}

/// Hamming distance between two base64 perceptual hashes (for the future
/// near-dup index; exposed now for tests). Errors if either fails to decode.
pub fn perceptual_distance(a: &str, b: &str) -> Result<u32, String> {
    let ha = ImageHash::<Box<[u8]>>::from_base64(a).map_err(|e| format!("{e:?}"))?;
    let hb = ImageHash::<Box<[u8]>>::from_base64(b).map_err(|e| format!("{e:?}"))?;
    Ok(ha.dist(&hb))
}

pub fn validate_image(bytes: &[u8], filename: &str) -> IngestReport {
    validate_image_limited(
        bytes,
        filename,
        crate::limits::Limits::default().max_image_pixels,
    )
}

pub fn validate_image_limited(bytes: &[u8], filename: &str, max_pixels: u64) -> IngestReport {
    use std::io::Cursor;
    let ds_hash = dataset_hash(bytes);

    // Pixel-bomb guard: read dimensions from the header (no full decode) and
    // reject before allocating a giant pixel buffer.
    match image::ImageReader::new(Cursor::new(bytes)).with_guessed_format() {
        Ok(reader) => match reader.into_dimensions() {
            Ok((w, h)) => {
                if (w as u64) * (h as u64) > max_pixels {
                    return reject(
                        ds_hash,
                        format!("image {w}x{h} exceeds pixel limit {max_pixels}"),
                    );
                }
            }
            Err(e) => return reject(ds_hash, format!("unreadable image header: {e}")),
        },
        Err(e) => return reject(ds_hash, format!("unreadable image: {e}")),
    }

    let img = match image::load_from_memory(bytes) {
        Ok(img) => img,
        Err(e) => return reject(ds_hash, format!("undecodable/corrupt image: {e}")),
    };
    let (w, h) = (img.width(), img.height());
    if w == 0 || h == 0 {
        return reject(ds_hash, "image has zero dimension".into());
    }

    let format = image::guess_format(bytes)
        .ok()
        .map(|f| format!("{f:?}"))
        .unwrap_or_else(|| "unknown".into());
    let phash_b64 = phash(&img).to_base64();

    let media_meta = json!({
        "kind": "image",
        "format": format,
        "width": w,
        "height": h,
        "filename": filename,
    });

    IngestReport {
        status: IngestStatus::Validated,
        validated_amount: 1, // one asset
        dataset_hash: ds_hash.clone(),
        quality_score: 1.0,
        sample: vec![media_meta.clone()],
        // Exact-file dedup: the asset keys on its own content hash.
        key_hashes: vec![ds_hash],
        validation_report: json!({
            "kind": "image", "assets": 1, "width": w, "height": h, "format": format,
        }),
        key_hash_ref: None,
        sample_ref: None,
        media_meta: Some(media_meta),
        perceptual_hashes: Some(vec![phash_b64]),
        errors: vec![],
    }
}

fn reject(ds_hash: String, msg: String) -> IngestReport {
    IngestReport {
        status: IngestStatus::RejectedInvalid,
        validated_amount: 0,
        dataset_hash: ds_hash,
        quality_score: 0.0,
        sample: vec![],
        key_hashes: vec![],
        validation_report: json!({ "kind": "image", "assets": 0, "error": msg }),
        key_hash_ref: None,
        sample_ref: None,
        media_meta: None,
        perceptual_hashes: None,
        errors: vec![msg],
    }
}

// ── ffmpeg transcode / thumbnail + audio fingerprint (follow-up) ─────────────
// External-binary work, not built here. Shape, for when it lands:
//   * thumbnail: ffmpeg -i in -vf scale=320:-1 -frames:v 1 thumb.jpg  → write to S3
//   * transcode: ffmpeg -i in -c:v libx264 -preset fast out.mp4       → write to S3
//   * audio fp:  symphonia decode → chromaprint-style fingerprint → perceptual_hashes
// All produce *derived artifacts*; none touch money/lifecycle. Keep it that way.
