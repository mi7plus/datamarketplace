//! S3 access — read source files, write derived artifacts (sample, thumbnails,
//! transcodes, hash files). Supports MinIO via a custom endpoint.
//!
//! Rust reads source + writes *derived* artifacts only. It is never the writer of
//! money/lifecycle state.

use crate::config::Config;
use anyhow::{Context, Result};
use aws_sdk_s3::primitives::ByteStream;
use aws_sdk_s3::Client;

#[derive(Clone)]
pub struct S3 {
    client: Client,
    bucket: String,
    max_bytes: usize,
}

impl S3 {
    pub async fn new(cfg: &Config) -> Result<Self> {
        let mut loader =
            aws_config::defaults(aws_config::BehaviorVersion::latest());
        if let Some(ep) = &cfg.s3_endpoint {
            loader = loader.endpoint_url(ep);
        }
        let shared = loader.load().await;
        let mut s3_cfg = aws_sdk_s3::config::Builder::from(&shared);
        if cfg.s3_endpoint.is_some() {
            // MinIO needs path-style addressing.
            s3_cfg = s3_cfg.force_path_style(true);
        }
        Ok(S3 {
            client: Client::from_conf(s3_cfg.build()),
            bucket: cfg.s3_bucket.clone(),
            max_bytes: cfg.max_file_bytes,
        })
    }

    /// Fetch an object, enforcing the size cap (P5 oversize/bomb guard).
    pub async fn get(&self, key: &str) -> Result<Vec<u8>> {
        let resp = self
            .client
            .get_object()
            .bucket(&self.bucket)
            .key(key)
            .send()
            .await
            .with_context(|| format!("s3 get {key}"))?;

        if let Some(len) = resp.content_length() {
            if len as usize > self.max_bytes {
                anyhow::bail!("object {key} exceeds max_file_bytes ({len} bytes)");
            }
        }

        let data = resp.body.collect().await?.into_bytes();
        if data.len() > self.max_bytes {
            anyhow::bail!("object {key} exceeds max_file_bytes after read");
        }
        Ok(data.to_vec())
    }

    /// Write a derived artifact (sample/thumbnail/hash file).
    pub async fn put(&self, key: &str, body: Vec<u8>, content_type: &str) -> Result<()> {
        self.client
            .put_object()
            .bucket(&self.bucket)
            .key(key)
            .body(ByteStream::from(body))
            .content_type(content_type)
            .send()
            .await
            .with_context(|| format!("s3 put {key}"))?;
        Ok(())
    }
}
