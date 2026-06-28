//! Image validation + perceptual hashing (pHash).

use crate::contract::{MediaMeta, PerceptualHashes};
use crate::media::MediaOutput;
use image::imageops::FilterType;
use image::GenericImageView;

pub fn process(bytes: &[u8]) -> MediaOutput {
    let mut errors = Vec::new();

    // Decode. A decode failure == corrupt/unsupported -> report, don't panic.
    let img = match image::load_from_memory(bytes) {
        Ok(img) => img,
        Err(e) => {
            errors.push(format!("image decode failed: {e}"));
            return MediaOutput {
                meta: MediaMeta {
                    corrupt: true,
                    ..Default::default()
                },
                perceptual: PerceptualHashes::default(),
                errors,
            };
        }
    };

    let (width, height) = img.dimensions();
    let format = image::guess_format(bytes)
        .ok()
        .map(format_name)
        .map(|s| s.to_string());

    // 64-bit average-hash (aHash). Hand-rolled on the `image` crate to avoid the
    // img_hash/image version conflict. Hamming distance over these 64 bits is the
    // near-dup signal the (future) BK-tree / pgvector index consumes.
    let phash = average_hash(&img);

    MediaOutput {
        meta: MediaMeta {
            container: format,
            codec: None,
            width: Some(width),
            height: Some(height),
            duration_secs: None,
            corrupt: false,
        },
        perceptual: PerceptualHashes {
            phash: Some(hex::encode(phash.to_be_bytes())),
            audio_fingerprint: None,
        },
        errors,
    }
}

/// Average-hash: 8x8 grayscale, bit set where the pixel exceeds the mean.
fn average_hash(img: &image::DynamicImage) -> u64 {
    let small = img.resize_exact(8, 8, FilterType::Triangle).to_luma8();
    let pixels: Vec<u8> = small.pixels().map(|p| p.0[0]).collect();
    let sum: u32 = pixels.iter().map(|&p| p as u32).sum();
    let mean = (sum / pixels.len() as u32) as u8;
    let mut bits: u64 = 0;
    for (i, &p) in pixels.iter().enumerate().take(64) {
        if p > mean {
            bits |= 1 << i;
        }
    }
    bits
}

fn format_name(f: image::ImageFormat) -> &'static str {
    match f {
        image::ImageFormat::Png => "png",
        image::ImageFormat::Jpeg => "jpeg",
        image::ImageFormat::Gif => "gif",
        image::ImageFormat::WebP => "webp",
        image::ImageFormat::Bmp => "bmp",
        image::ImageFormat::Tiff => "tiff",
        _ => "other",
    }
}
