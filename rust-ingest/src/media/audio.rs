//! Audio validation + fingerprint scaffolding.
//!
//! P3 scope: decode/validate with symphonia and emit duration + a coarse
//! fingerprint placeholder. A production chromaprint-style fingerprint (the
//! audio analogue of pHash) is a deliberate follow-up — flagged here so the
//! contract field (`audio_fingerprint`) already exists for the index to consume.

use crate::contract::{MediaMeta, PerceptualHashes};
use crate::media::MediaOutput;
use std::io::Cursor;
use symphonia::core::formats::FormatOptions;
use symphonia::core::io::MediaSourceStream;
use symphonia::core::meta::MetadataOptions;
use symphonia::core::probe::Hint;

pub fn process(bytes: &[u8]) -> MediaOutput {
    let mut errors = Vec::new();

    let mss = MediaSourceStream::new(Box::new(Cursor::new(bytes.to_vec())), Default::default());
    let probe = symphonia::default::get_probe();
    let probed = probe.format(
        &Hint::new(),
        mss,
        &FormatOptions::default(),
        &MetadataOptions::default(),
    );

    let format = match probed {
        Ok(p) => p,
        Err(e) => {
            errors.push(format!("audio probe failed: {e}"));
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

    // Pull codec + duration from the default track when available.
    let mut codec = None;
    let mut duration_secs = None;
    if let Some(track) = format.format.default_track() {
        codec = Some(format!("{:?}", track.codec_params.codec));
        if let (Some(n_frames), Some(rate)) =
            (track.codec_params.n_frames, track.codec_params.sample_rate)
        {
            duration_secs = Some(n_frames as f64 / rate as f64);
        }
    }

    MediaOutput {
        meta: MediaMeta {
            container: None,
            codec,
            width: None,
            height: None,
            duration_secs,
            corrupt: false,
        },
        // TODO(P3-followup): real chromaprint fingerprint over decoded PCM.
        perceptual: PerceptualHashes::default(),
        errors,
    }
}
