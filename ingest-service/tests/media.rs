//! Media (P3) — image validation, exact-file dedup, and the perceptual-hash
//! near-vs-far property. Images are generated in-code so the test needs no
//! fixtures and no ffmpeg.

use std::io::Cursor;

use image::{DynamicImage, ImageBuffer, ImageFormat, Luma};
use rowbound_ingest::contract::Spec;
use rowbound_ingest::media::{perceptual_distance, validate_image};
use rowbound_ingest::{ingest, IngestStatus};

fn png(f: impl Fn(u32, u32) -> u8) -> Vec<u8> {
    let buf: ImageBuffer<Luma<u8>, _> = ImageBuffer::from_fn(64, 64, |x, y| Luma([f(x, y)]));
    let mut bytes = Vec::new();
    DynamicImage::ImageLuma8(buf)
        .write_to(&mut Cursor::new(&mut bytes), ImageFormat::Png)
        .unwrap();
    bytes
}

#[test]
fn validates_image_with_metadata_and_exact_file_key() {
    let bytes = png(|x, _| (x * 4) as u8);
    let r = validate_image(&bytes, "photo.png");
    assert_eq!(r.status, IngestStatus::Validated);
    assert_eq!(r.validated_amount, 1);
    // Exact-file dedup: the asset keys on its own content hash.
    assert_eq!(r.key_hashes, vec![r.dataset_hash.clone()]);
    let meta = r.media_meta.unwrap();
    assert_eq!(meta["width"], 64);
    assert_eq!(meta["height"], 64);
    assert!(r.perceptual_hashes.unwrap().len() == 1);
}

#[test]
fn identical_bytes_dedup_to_same_hash() {
    let bytes = png(|x, _| (x * 4) as u8);
    let a = validate_image(&bytes, "a.png");
    let b = validate_image(&bytes, "b.png");
    assert_eq!(a.dataset_hash, b.dataset_hash); // exact-file duplicate collapses
}

#[test]
fn corrupt_image_is_rejected() {
    let r = validate_image(b"this is not a real image", "broken.png");
    assert_eq!(r.status, IngestStatus::RejectedInvalid);
    assert_eq!(r.validated_amount, 0);
    assert!(!r.errors.is_empty());
}

#[test]
fn perceptual_hash_near_is_closer_than_far() {
    // High-frequency pseudo-texture so the 8x8 DCT pHash is discriminative.
    let a = png(|x, y| ((x * 37 + y * 101) % 256) as u8);
    // Brightness shift — pHash is mean-thresholded, so this stays a near-dup.
    let near = png(|x, y| (((x * 37 + y * 101) % 256) + 25).min(255) as u8);
    // A smooth gradient: completely different frequency content → far.
    let far = png(|x, _| (x * 4) as u8);

    let ha = validate_image(&a, "a.png").perceptual_hashes.unwrap()[0].clone();
    let hn = validate_image(&near, "n.png").perceptual_hashes.unwrap()[0].clone();
    let hf = validate_image(&far, "f.png").perceptual_hashes.unwrap()[0].clone();

    let d_near = perceptual_distance(&ha, &hn).unwrap();
    let d_far = perceptual_distance(&ha, &hf).unwrap();
    assert_eq!(perceptual_distance(&ha, &ha).unwrap(), 0);
    assert!(
        d_near < d_far,
        "near-dup distance {d_near} should be < far distance {d_far}"
    );
}

#[test]
fn dispatch_routes_images_to_media_and_csv_to_tabular() {
    let img = png(|x, _| (x * 4) as u8);
    let r_img = ingest(&img, "pic.png", &Spec::default());
    assert_eq!(r_img.validated_amount, 1);
    assert!(r_img.media_meta.is_some());

    let csv = b"name\nAcme\nGlobex\n";
    let r_csv = ingest(csv, "data.csv", &Spec::default());
    assert!(r_csv.media_meta.is_none());
    assert_eq!(r_csv.validated_amount, 2);
}
