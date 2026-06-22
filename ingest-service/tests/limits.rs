//! File-safety limits (P5): oversize + pixel-bomb rejection. Limits are passed
//! explicitly so the tests are deterministic (no env mutation/races).

use std::io::Cursor;

use image::{DynamicImage, ImageBuffer, ImageFormat, Luma};
use rowbound_ingest::contract::Spec;
use rowbound_ingest::media::validate_image_limited;
use rowbound_ingest::{ingest_limited, IngestStatus, Limits};

fn small_png() -> Vec<u8> {
    let buf: ImageBuffer<Luma<u8>, _> = ImageBuffer::from_fn(64, 64, |x, _| Luma([(x * 4) as u8]));
    let mut bytes = Vec::new();
    DynamicImage::ImageLuma8(buf)
        .write_to(&mut Cursor::new(&mut bytes), ImageFormat::Png)
        .unwrap();
    bytes
}

#[test]
fn oversize_upload_is_rejected_before_processing() {
    let limits = Limits {
        max_bytes: 10,
        max_image_pixels: 100_000_000,
    };
    let big = b"name\nAcmeAcmeAcmeAcmeAcmeAcme\n"; // > 10 bytes
    let r = ingest_limited(big, "data.csv", &Spec::default(), &limits);
    assert_eq!(r.status, IngestStatus::RejectedInvalid);
    assert!(r.errors[0].contains("exceeds limit"));
    assert_eq!(r.validation_report["rejected_by"], "file-safety");
}

#[test]
fn within_size_limit_processes_normally() {
    let limits = Limits {
        max_bytes: 10_000,
        max_image_pixels: 100_000_000,
    };
    let csv = b"name\nAcme\nGlobex\n";
    let r = ingest_limited(csv, "data.csv", &Spec::default(), &limits);
    assert_eq!(r.status, IngestStatus::Validated);
    assert_eq!(r.validated_amount, 2);
}

#[test]
fn pixel_bomb_rejected_via_header_dimensions() {
    // 64x64 = 4096 px; cap at 100 → rejected without a full decode.
    let png = small_png();
    let r = validate_image_limited(&png, "huge.png", 100);
    assert_eq!(r.status, IngestStatus::RejectedInvalid);
    assert!(r.errors[0].contains("pixel limit"));
}

#[test]
fn image_within_pixel_limit_validates() {
    let png = small_png();
    let r = validate_image_limited(&png, "ok.png", 1_000_000);
    assert_eq!(r.status, IngestStatus::Validated);
    assert_eq!(r.validated_amount, 1);
}

#[test]
fn oversize_image_caught_by_byte_gate_first() {
    // The byte gate runs before any image work.
    let limits = Limits {
        max_bytes: 5,
        max_image_pixels: 100_000_000,
    };
    let png = small_png();
    let r = ingest_limited(&png, "pic.png", &Spec::default(), &limits);
    assert_eq!(r.status, IngestStatus::RejectedInvalid);
    assert!(r.errors[0].contains("exceeds limit"));
}
