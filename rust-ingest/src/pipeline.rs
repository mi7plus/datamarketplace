//! Job orchestration shared by the sync HTTP path and the SQS workers.
//!
//! fetch source -> validate/hash (tabular) OR validate/fingerprint (media) ->
//! write derived artifacts + staging hashes -> return report. Stateless and
//! side-effect-bounded: reads source, writes derived artifacts + staging hashes,
//! returns a report. NEVER writes money/lifecycle tables.

use crate::contract::{IngestReport, IngestRequest, Modality};
use crate::media;
use crate::staging::Staging;
use crate::storage::S3;
use crate::tabular;
use anyhow::Result;
use std::time::Instant;

#[derive(Clone)]
pub struct Pipeline {
    pub s3: S3,
    pub staging: Option<Staging>,
}

impl Pipeline {
    pub async fn run(&self, req: &IngestRequest) -> Result<IngestReport> {
        let started = Instant::now();
        let bytes = self.s3.get(&req.s3_key).await?;

        let report = match req.modality {
            Modality::Tabular => self.run_tabular(req, &bytes).await?,
            _ => self.run_media(req, &bytes).await?,
        };

        let ok = report
            .status
            .map(|s| matches!(s.0, crate::contract::IngestStatus::Validated))
            .unwrap_or(false);
        crate::metrics::record_job(
            modality_label(req.modality),
            started.elapsed().as_secs_f64(),
            ok,
        );
        crate::metrics::record_records(report.validated_amount);
        Ok(report)
    }

    async fn run_tabular(&self, req: &IngestRequest, bytes: &[u8]) -> Result<IngestReport> {
        let out = tabular::process_tabular(
            bytes,
            &req.filename,
            &req.spec,
            &req.job_id,
            &req.submission_id,
        );
        let mut report = out.report;

        // Stage key hashes for the SQL anti-join (P2). Falls back to inlining the
        // count only if no DB is configured (sync/dev without staging).
        if !out.key_hashes.is_empty() {
            if let Some(staging) = &self.staging {
                staging
                    .write_key_hashes(&req.submission_id, &out.key_hashes)
                    .await?;
                report.key_hash_ref = Some("staging-table".to_string());
            } else {
                // Dev fallback: persist a compact artifact Python can COPY in.
                let artifact = out.key_hashes.join("\n").into_bytes();
                let key = format!("ingest-staging/{}.keyhashes", req.submission_id);
                self.s3.put(&key, artifact, "text/plain").await?;
                report.key_hash_ref = Some(key);
            }
        }
        Ok(report)
    }

    async fn run_media(&self, req: &IngestRequest, bytes: &[u8]) -> Result<IngestReport> {
        use sha2::{Digest, Sha256};
        let dataset_hash = hex::encode(Sha256::digest(bytes));
        let m = media::process_media(req.modality, bytes);

        let mut report = IngestReport {
            job_id: req.job_id.clone(),
            submission_id: req.submission_id.clone(),
            dataset_hash,
            // Media "amount" is 1 unit (the file) unless corrupt. Tabular counting
            // does not apply; exact-file dedup is the first-cut dedup signal.
            validated_amount: if m.meta.corrupt { 0 } else { 1 },
            total_rows: 1,
            media_meta: Some(m.meta.clone()),
            perceptual_hashes: Some(m.perceptual),
            errors: m.errors,
            ..Default::default()
        };
        report.set_status(if m.meta.corrupt {
            crate::contract::IngestStatus::RejectedInvalid
        } else {
            crate::contract::IngestStatus::Validated
        });
        Ok(report)
    }
}

fn modality_label(m: Modality) -> &'static str {
    match m {
        Modality::Tabular => "tabular",
        Modality::Image => "image",
        Modality::Audio => "audio",
        Modality::Video => "video",
    }
}
