//! Audio/video ingest (P3 media follow-up) — shells out to ffprobe/ffmpeg/fpcalc.
//!
//! ffprobe → validation (decodes the header; a corrupt file errors) + codec/
//! duration/resolution metadata. fpcalc → Chromaprint audio fingerprint (the
//! perceptual hash for audio). ffmpeg → thumbnail (a derived artifact the worker
//! uploads to S3). Dedup is still EXACT FILE (`key_hashes=[dataset_hash]`); the
//! perceptual near-dup search remains the deliberate follow-up.
//!
//! Binaries are resolved from `MediaTools` (env override or PATH), so prod uses
//! the image's `ffmpeg`/`fpcalc` and tests point at the local `.bin/`.

use std::path::PathBuf;
use std::process::Command;
use std::sync::atomic::{AtomicU64, Ordering};

use serde_json::{json, Value};

use crate::contract::{IngestReport, IngestStatus};
use crate::keys::dataset_hash;

const VIDEO_EXTS: [&str; 6] = ["mp4", "mov", "mkv", "webm", "avi", "m4v"];
const AUDIO_EXTS: [&str; 6] = ["mp3", "wav", "flac", "m4a", "ogg", "aac"];

fn ext_of(filename: &str) -> String {
    filename.rsplit('.').next().unwrap_or("").to_lowercase()
}
pub fn is_video(filename: &str) -> bool {
    VIDEO_EXTS.contains(&ext_of(filename).as_str())
}
pub fn is_audio(filename: &str) -> bool {
    AUDIO_EXTS.contains(&ext_of(filename).as_str())
}
pub fn is_av(filename: &str) -> bool {
    is_video(filename) || is_audio(filename)
}

/// Resolved media binaries. `from_env` honours FFPROBE_BIN/FFMPEG_BIN/FPCALC_BIN,
/// else falls back to PATH names (the prod image installs them).
#[derive(Debug, Clone)]
pub struct MediaTools {
    pub ffprobe: PathBuf,
    pub ffmpeg: PathBuf,
    pub fpcalc: PathBuf,
}

impl MediaTools {
    pub fn from_env() -> Self {
        MediaTools {
            ffprobe: bin("FFPROBE_BIN", "ffprobe"),
            ffmpeg: bin("FFMPEG_BIN", "ffmpeg"),
            fpcalc: bin("FPCALC_BIN", "fpcalc"),
        }
    }
    /// True if ffprobe is actually runnable (tests self-skip when absent).
    pub fn available(&self) -> bool {
        Command::new(&self.ffprobe).arg("-version").output().is_ok()
    }
}

fn bin(env_key: &str, default: &str) -> PathBuf {
    std::env::var(env_key)
        .map(PathBuf::from)
        .unwrap_or_else(|_| PathBuf::from(default))
}

static TMP_SEQ: AtomicU64 = AtomicU64::new(0);

/// Write bytes to a uniquely-named temp file (keeping the extension so ffprobe
/// detects the format). Returns a guard that deletes the file on drop.
struct TempFile(PathBuf);
impl Drop for TempFile {
    fn drop(&mut self) {
        let _ = std::fs::remove_file(&self.0);
    }
}
fn temp_write(bytes: &[u8], ext: &str) -> std::io::Result<TempFile> {
    let seq = TMP_SEQ.fetch_add(1, Ordering::Relaxed);
    let name = format!("rowbound-av-{}-{seq}.{ext}", std::process::id());
    let path = std::env::temp_dir().join(name);
    std::fs::write(&path, bytes)?;
    Ok(TempFile(path))
}

pub fn validate_av(bytes: &[u8], filename: &str, tools: &MediaTools) -> IngestReport {
    let ds = dataset_hash(bytes);
    let ext = ext_of(filename);

    let tmp = match temp_write(bytes, &ext) {
        Ok(t) => t,
        Err(e) => return reject(ds, format!("temp write failed: {e}")),
    };

    let probe = Command::new(&tools.ffprobe)
        .args([
            "-v",
            "error",
            "-show_format",
            "-show_streams",
            "-of",
            "json",
        ])
        .arg(&tmp.0)
        .output();
    let probe = match probe {
        Ok(o) if o.status.success() => o,
        Ok(o) => {
            let err = String::from_utf8_lossy(&o.stderr).trim().to_string();
            return reject(ds, format!("ffprobe rejected file: {err}"));
        }
        Err(e) => return reject(ds, format!("ffprobe not runnable: {e}")),
    };

    let meta: Value = serde_json::from_slice(&probe.stdout).unwrap_or_else(|_| json!({}));
    let streams = meta
        .get("streams")
        .and_then(Value::as_array)
        .cloned()
        .unwrap_or_default();
    if streams.is_empty() {
        return reject(ds, "no decodable streams".into());
    }

    let kind = if is_video(filename) { "video" } else { "audio" };
    let duration = meta
        .get("format")
        .and_then(|f| f.get("duration"))
        .and_then(Value::as_str)
        .and_then(|s| s.parse::<f64>().ok());

    let video = streams
        .iter()
        .find(|s| s.get("codec_type").and_then(Value::as_str) == Some("video"));
    let audio = streams
        .iter()
        .find(|s| s.get("codec_type").and_then(Value::as_str) == Some("audio"));

    let mut media_meta = json!({
        "kind": kind,
        "filename": filename,
        "format": meta.get("format").and_then(|f| f.get("format_name")).cloned().unwrap_or(Value::Null),
        "duration": duration,
        "stream_count": streams.len(),
    });
    if let Some(v) = video {
        media_meta["video_codec"] = v.get("codec_name").cloned().unwrap_or(Value::Null);
        media_meta["width"] = v.get("width").cloned().unwrap_or(Value::Null);
        media_meta["height"] = v.get("height").cloned().unwrap_or(Value::Null);
    }
    if let Some(a) = audio {
        media_meta["audio_codec"] = a.get("codec_name").cloned().unwrap_or(Value::Null);
        media_meta["sample_rate"] = a.get("sample_rate").cloned().unwrap_or(Value::Null);
        media_meta["channels"] = a.get("channels").cloned().unwrap_or(Value::Null);
    }

    // Audio fingerprint (Chromaprint) — the perceptual hash for audio.
    let perceptual = if is_audio(filename) {
        fpcalc_fingerprint(&tmp.0, tools).map(|fp| vec![fp])
    } else {
        None
    };

    IngestReport {
        status: IngestStatus::Validated,
        validated_amount: 1,
        dataset_hash: ds.clone(),
        quality_score: 1.0,
        sample: vec![media_meta.clone()],
        key_hashes: vec![ds], // exact-file dedup
        validation_report: json!({ "kind": kind, "assets": 1, "streams": streams.len() }),
        key_hash_ref: None,
        sample_ref: None,
        media_meta: Some(media_meta),
        perceptual_hashes: perceptual,
        errors: vec![],
    }
}

fn fpcalc_fingerprint(path: &std::path::Path, tools: &MediaTools) -> Option<String> {
    let out = Command::new(&tools.fpcalc)
        .args(["-json"])
        .arg(path)
        .output()
        .ok()?;
    if !out.status.success() {
        return None;
    }
    let v: Value = serde_json::from_slice(&out.stdout).ok()?;
    v.get("fingerprint")
        .and_then(Value::as_str)
        .map(String::from)
}

/// Produce a JPEG thumbnail (a derived artifact the worker uploads to S3).
/// Single frame, width 320, aspect preserved.
pub fn make_thumbnail(bytes: &[u8], filename: &str, tools: &MediaTools) -> Result<Vec<u8>, String> {
    let tmp = temp_write(bytes, &ext_of(filename)).map_err(|e| e.to_string())?;
    let out = temp_write(b"", "jpg").map_err(|e| e.to_string())?;
    let status = Command::new(&tools.ffmpeg)
        .args(["-y", "-i"])
        .arg(&tmp.0)
        .args([
            "-frames:v",
            "1",
            "-vf",
            "scale=320:-1",
            "-f",
            "image2",
            "-c:v",
            "mjpeg",
        ])
        .arg(&out.0)
        .output()
        .map_err(|e| format!("ffmpeg not runnable: {e}"))?;
    if !status.status.success() {
        return Err(String::from_utf8_lossy(&status.stderr).trim().to_string());
    }
    std::fs::read(&out.0).map_err(|e| e.to_string())
}

fn reject(ds_hash: String, msg: String) -> IngestReport {
    IngestReport {
        status: IngestStatus::RejectedInvalid,
        validated_amount: 0,
        dataset_hash: ds_hash,
        quality_score: 0.0,
        sample: vec![],
        key_hashes: vec![],
        validation_report: json!({ "kind": "av", "assets": 0, "error": msg }),
        key_hash_ref: None,
        sample_ref: None,
        media_meta: None,
        perceptual_hashes: None,
        errors: vec![msg],
    }
}
