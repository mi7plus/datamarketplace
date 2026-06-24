//! BK-tree perceptual near-dup search: near-duplicates are found within a Hamming
//! threshold; unrelated images are not. Images generated in-code (no fixtures).

use std::io::Cursor;

use image::{DynamicImage, ImageBuffer, ImageFormat, Luma};
use rowbound_ingest::media::validate_image;
use rowbound_ingest::neardup::NearDupIndex;

fn phash(f: impl Fn(u32, u32) -> u8) -> String {
    let buf: ImageBuffer<Luma<u8>, _> = ImageBuffer::from_fn(64, 64, |x, y| Luma([f(x, y)]));
    let mut bytes = Vec::new();
    DynamicImage::ImageLuma8(buf)
        .write_to(&mut Cursor::new(&mut bytes), ImageFormat::Png)
        .unwrap();
    validate_image(&bytes, "x.png").perceptual_hashes.unwrap()[0].clone()
}

fn texture() -> String {
    phash(|x, y| ((x * 37 + y * 101) % 256) as u8)
}
fn texture_brightened() -> String {
    phash(|x, y| (((x * 37 + y * 101) % 256) + 25).min(255) as u8)
}
fn gradient() -> String {
    phash(|x, _| (x * 4) as u8)
}

#[test]
fn finds_near_duplicate_not_unrelated() {
    let mut idx = NearDupIndex::new();
    idx.insert(&texture(), "texture-asset");
    idx.insert(&gradient(), "gradient-asset");
    assert_eq!(idx.len(), 2);

    // A brightened copy of the texture is a near-dup of "texture-asset".
    let hits = idx.query(&texture_brightened(), 8);
    assert!(
        hits.iter().any(|m| m.id == "texture-asset"),
        "expected texture near-dup, got {hits:?}"
    );
    // The unrelated gradient must NOT be reported at this tight threshold.
    assert!(!hits.iter().any(|m| m.id == "gradient-asset"));
}

#[test]
fn exact_duplicate_is_distance_zero_and_nearest_first() {
    let mut idx = NearDupIndex::new();
    let h = texture();
    idx.insert(&gradient(), "far");
    idx.insert(&h, "exact");
    let hits = idx.query(&h, 64);
    assert_eq!(hits[0].id, "exact"); // nearest-first
    assert_eq!(hits[0].distance, 0); // exact perceptual match
}

#[test]
fn empty_index_and_no_match_below_threshold() {
    let mut idx = NearDupIndex::new();
    assert!(idx.is_empty());
    assert!(idx.query(&texture(), 5).is_empty());

    idx.insert(&gradient(), "g");
    // The texture is far from the gradient — not within a tiny threshold.
    assert!(!idx.contains_near(&texture(), 2));
}
