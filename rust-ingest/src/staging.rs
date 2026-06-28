//! Staging-table writer (P2). Bulk-writes normalized key hashes via COPY so the
//! Python allocation step can compute overlap as a SQL anti-join inside its
//! locked transaction (`creditable = staging EXCEPT accepted_keys`).
//!
//! HARD BOUNDARY: this module writes ONLY `submission_key_staging`. It must never
//! touch money/lifecycle tables. The IAM/DB grant for this service is scoped to
//! this table (see RUST_INGEST_DEPLOY.md). Rust computes; Python settles.

use anyhow::{Context, Result};
use sqlx::postgres::{PgPool, PgPoolOptions};
use sqlx::Row;
use std::io::Write;

#[derive(Clone)]
pub struct Staging {
    pool: PgPool,
}

impl Staging {
    pub async fn connect(database_url: &str) -> Result<Self> {
        let pool = PgPoolOptions::new()
            .max_connections(5)
            .connect(database_url)
            .await
            .context("connect staging pool")?;
        Ok(Staging { pool })
    }

    /// Replace this submission's staged hashes with `hashes`, idempotently:
    /// delete-then-COPY inside one transaction, so reprocessing the same job
    /// yields identical staging contents (idempotency guarantee from the plan).
    pub async fn write_key_hashes(&self, submission_id: &str, hashes: &[String]) -> Result<u64> {
        let mut tx = self.pool.begin().await?;

        sqlx::query("DELETE FROM submission_key_staging WHERE submission_id = $1::uuid")
            .bind(submission_id)
            .execute(&mut *tx)
            .await
            .context("clear prior staging rows")?;

        if !hashes.is_empty() {
            // COPY ... FROM STDIN (text format): "submission_id\tkey_hash\n".
            let mut copy = tx
                .copy_in_raw(
                    "COPY submission_key_staging (submission_id, key_hash) \
                     FROM STDIN WITH (FORMAT text)",
                )
                .await
                .context("begin COPY")?;

            let mut buf = Vec::with_capacity(hashes.len() * (37 + 65));
            for h in hashes {
                // key_hash is hex sha256 (safe chars), submission_id is a uuid;
                // neither needs COPY text-format escaping.
                writeln!(buf, "{submission_id}\t{h}").ok();
            }
            copy.send(buf).await.context("COPY send")?;
            copy.finish().await.context("COPY finish")?;
        }

        tx.commit().await?;
        Ok(hashes.len() as u64)
    }

    /// Health probe — confirms the staging table is reachable.
    pub async fn ping(&self) -> Result<()> {
        let row = sqlx::query("SELECT 1 AS ok").fetch_one(&self.pool).await?;
        let _: i32 = row.try_get("ok")?;
        Ok(())
    }
}
