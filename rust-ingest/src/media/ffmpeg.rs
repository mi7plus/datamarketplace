//! Video validation + thumbnail/transcode via ffmpeg/ffprobe shell-out.
//!
//! Pragmatic per the plan ("shell out to ffmpeg"). The binaries must be present
//! in the worker image (the Dockerfile installs them). A perceptual hash for
//! video is derived from a sampled thumbnail frame (image pHash), with exact-file
//! dedup (`dataset_hash`) as the first-cut dedup signal.

use crate::contract::{MediaMeta, PerceptualHashes};
use crate::media::MediaOutput;
use std::io::Write;
use std::process::Command;

pub fn process_video(bytes: &[u8]) -> MediaOutput {
    let mut errors = Vec::new();

    // ffprobe needs a file; write to a temp path, probe, extract a thumbnail.
    let tmp = match write_temp(bytes, "mp4") {
        Ok(p) => p,
        Err(e) => {
            errors.push(format!("temp write failed: {e}"));
            return corrupt(errors);
        }
    };

    let meta = match ffprobe(&tmp) {
        Ok(m) => m,
        Err(e) => {
            errors.push(format!("ffprobe failed: {e}"));
            let _ = std::fs::remove_file(&tmp);
            return corrupt(errors);
        }
    };

    // Perceptual hash from a thumbnail frame (best-effort).
    let mut perceptual = PerceptualHashes::default();
    match extract_thumbnail(&tmp) {
        Ok(jpeg) => {
            let out = crate::media::image::process(&jpeg);
            perceptual.phash = out.perceptual.phash;
        }
        Err(e) => errors.push(format!("thumbnail extract failed: {e}")),
    }

    let _ = std::fs::remove_file(&tmp);
    MediaOutput {
        meta,
        perceptual,
        errors,
    }
}

fn corrupt(errors: Vec<String>) -> MediaOutput {
    MediaOutput {
        meta: MediaMeta {
            corrupt: true,
            ..Default::default()
        },
        perceptual: PerceptualHashes::default(),
        errors,
    }
}

fn write_temp(bytes: &[u8], ext: &str) -> std::io::Result<std::path::PathBuf> {
    let mut path = std::env::temp_dir();
    path.push(format!("rb-ingest-{}.{ext}", uuid_like()));
    let mut f = std::fs::File::create(&path)?;
    f.write_all(bytes)?;
    Ok(path)
}

fn uuid_like() -> String {
    use std::time::{SystemTime, UNIX_EPOCH};
    let nanos = SystemTime::now()
        .duration_since(UNIX_EPOCH)
        .map(|d| d.as_nanos())
        .unwrap_or(0);
    format!("{nanos}")
}

fn ffprobe(path: &std::path::Path) -> Result<MediaMeta, String> {
    let out = Command::new("ffprobe")
        .args([
            "-v",
            "error",
            "-select_streams",
            "v:0",
            "-show_entries",
            "stream=codec_name,width,height:format=duration",
            "-of",
            "default=noprint_wrappers=1:nokey=0",
        ])
        .arg(path)
        .output()
        .map_err(|e| e.to_string())?;

    if !out.status.success() {
        return Err(String::from_utf8_lossy(&out.stderr).to_string());
    }
    let text = String::from_utf8_lossy(&out.stdout);
    let mut meta = MediaMeta::default();
    for line in text.lines() {
        if let Some((k, v)) = line.split_once('=') {
            match k.trim() {
                "codec_name" => meta.codec = Some(v.trim().to_string()),
                "width" => meta.width = v.trim().parse().ok(),
                "height" => meta.height = v.trim().parse().ok(),
                "duration" => meta.duration_secs = v.trim().parse().ok(),
                _ => {}
            }
        }
    }
    meta.container = Some("video".into());
    Ok(meta)
}

fn extract_thumbnail(path: &std::path::Path) -> Result<Vec<u8>, String> {
    let mut out_path = std::env::temp_dir();
    out_path.push(format!("rb-thumb-{}.jpg", uuid_like()));

    let status = Command::new("ffmpeg")
        .args(["-y", "-i"])
        .arg(path)
        .args(["-vf", "thumbnail", "-frames:v", "1"])
        .arg(&out_path)
        .status()
        .map_err(|e| e.to_string())?;

    if !status.success() {
        return Err("ffmpeg thumbnail returned non-zero".into());
    }
    let data = std::fs::read(&out_path).map_err(|e| e.to_string())?;
    let _ = std::fs::remove_file(&out_path);
    Ok(data)
}
