//! Audio/video media tests. Fixtures are generated with the local ffmpeg
//! (`.bin/`), and the whole module self-skips when the binaries aren't present
//! (e.g. CI without ffmpeg) so it never fails for a missing dependency.

use std::path::PathBuf;
use std::process::Command;

use rowbound_ingest::av::{is_video, make_thumbnail, validate_av, MediaTools};
use rowbound_ingest::IngestStatus;

fn tools() -> MediaTools {
    MediaTools {
        ffprobe: PathBuf::from(".bin/ffprobe.exe"),
        ffmpeg: PathBuf::from(".bin/ffmpeg.exe"),
        fpcalc: PathBuf::from(".bin/fpcalc.exe"),
    }
}

/// Generate a fixture with ffmpeg's lavfi sources; returns its bytes.
fn generate(t: &MediaTools, input: &[&str], ext: &str) -> Vec<u8> {
    let out = std::env::temp_dir().join(format!("rb-fixture-{}.{ext}", std::process::id()));
    let status = Command::new(&t.ffmpeg)
        .arg("-y")
        .args(input)
        .arg(&out)
        .output()
        .expect("run ffmpeg");
    assert!(status.status.success(), "ffmpeg fixture gen failed");
    let bytes = std::fs::read(&out).unwrap();
    let _ = std::fs::remove_file(&out);
    bytes
}

fn video_fixture(t: &MediaTools) -> Vec<u8> {
    generate(
        t,
        &[
            "-f",
            "lavfi",
            "-i",
            "testsrc=duration=1:size=64x64:rate=1",
            "-pix_fmt",
            "yuv420p",
        ],
        "mp4",
    )
}
fn audio_fixture(t: &MediaTools) -> Vec<u8> {
    generate(
        t,
        &["-f", "lavfi", "-i", "sine=frequency=440:duration=3"],
        "wav",
    )
}

#[test]
fn video_validates_with_metadata_and_exact_file_key() {
    let t = tools();
    if !t.available() {
        eprintln!("ffprobe unavailable — skipping av tests");
        return;
    }
    let bytes = video_fixture(&t);
    let r = validate_av(&bytes, "clip.mp4", &t);
    assert_eq!(r.status, IngestStatus::Validated);
    assert_eq!(r.validated_amount, 1);
    assert_eq!(r.key_hashes, vec![r.dataset_hash.clone()]); // exact-file dedup
    let meta = r.media_meta.unwrap();
    assert_eq!(meta["kind"], "video");
    assert_eq!(meta["width"], 64);
    assert_eq!(meta["height"], 64);
}

#[test]
fn audio_validates_and_gets_chromaprint_fingerprint() {
    let t = tools();
    if !t.available() {
        return;
    }
    let bytes = audio_fixture(&t);
    let r = validate_av(&bytes, "song.wav", &t);
    assert_eq!(r.status, IngestStatus::Validated);
    assert_eq!(r.media_meta.unwrap()["kind"], "audio");
    let fp = r.perceptual_hashes.expect("audio fingerprint present");
    assert_eq!(fp.len(), 1);
    assert!(!fp[0].is_empty());
}

#[test]
fn corrupt_av_is_rejected() {
    let t = tools();
    if !t.available() {
        return;
    }
    let r = validate_av(b"definitely not a real mp4", "broken.mp4", &t);
    assert_eq!(r.status, IngestStatus::RejectedInvalid);
    assert!(!r.errors.is_empty());
}

#[test]
fn thumbnail_is_a_jpeg() {
    let t = tools();
    if !t.available() {
        return;
    }
    let bytes = video_fixture(&t);
    let thumb = make_thumbnail(&bytes, "clip.mp4", &t).expect("thumbnail");
    // JPEG SOI marker.
    assert_eq!(&thumb[..2], &[0xFF, 0xD8]);
    assert!(thumb.len() > 100);
}

#[test]
fn extension_routing() {
    assert!(is_video("a.mp4"));
    assert!(!is_video("a.wav"));
}
