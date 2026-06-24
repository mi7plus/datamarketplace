# Encryption & Key Management

Implements `rowbound-encryption-key-management.md`. **Scope split:** the
application-layer controls live in this repo; the AWS/Terraform controls live in
the separate `rowbound-deploy/infra` repo and are captured here as the spec to
apply there.

**The line we hold:** encrypt at rest (KMS) + in transit (TLS everywhere,
including app→DB) + minimize transient plaintext, while the app/Rust processing
roles retain exactly enough key access to run validation/dedup/media. We do
**not** pursue zero-knowledge encryption — it would disable the dedup-and-validation
moat.

---

## What is implemented in this repo (application layer)

| Item | Where | Notes |
|---|---|---|
| **E1.3** app→Postgres TLS | `backend/app/db.py` | `DB_SSLMODE` (default `prefer`; prod `require`/`verify-full`) + `DB_SSLROOTCERT` via `connect_args` |
| **E2.2** SSE-KMS on S3 puts | `backend/app/storage.py` | `S3_SSE_KMS_KEY_ID` → `ServerSideEncryption=aws:kms` + `BucketKeyEnabled` on every put |
| **E3** Presigned hardening | `backend/app/storage.py`, `backend/app/submissions.py` | TTL default 1h→**5 min**, clamped to `PRESIGNED_URL_TTL_MAX`; HTTPS-only (dev escape hatch `PRESIGNED_ALLOW_HTTP`); `download_limit` enforced via new `download_count` |
| **E5** Envelope encryption | `backend/app/crypto.py`, `storage.py`, `submissions.py` | KMS + dev key providers; AES-256-GCM; sensitive (PII) uploads stored as ciphertext; decrypt-and-stream delivery |
| **E6** CI key check | `.github/workflows/ci.yml` | `secrets-guard` extended to PKCS#8/OpenSSH/AWS-secret/master-key material |

### Configuration (see `backend/.env.example`)

```
DB_SSLMODE=require                 # prod; verify-full + DB_SSLROOTCERT is stronger
PRESIGNED_URL_TTL_SECONDS=300      # the URL is the access grant — keep it short
S3_SSE_KMS_KEY_ID=arn:aws:kms:...  # bucket-default SSE-KMS
ENVELOPE_KMS_KEY_ID=arn:aws:kms:... # turns on envelope encryption for sensitive data
```

With no KMS key configured the code falls back to a **`LocalKeyProvider`** — same
posture as `FakePaymentProvider`: end-to-end functional for dev, deliberately not
real security. **Never run real personal/production data through the dev stack.**

---

## What must be applied in `rowbound-deploy/infra` (AWS / Terraform)

These cannot be done from this repo — verify/apply them in the deploy repo via
`terraform plan` review. Never put keys or secrets in the repo or state.

### E1.1 / E1.2 — Confirm at-rest (verify in the live env, not just the plan)
- **S3:** confirm default encryption is actually applied on the real data bucket.
- **RDS:** confirm `storage_encrypted = true` on the live instance — it cannot be
  toggled after creation without a snapshot/restore, so check now.

### E2.1 — Customer-managed KMS key
```hcl
resource "aws_kms_key" "data" {
  description             = "rowbound data-at-rest"
  enable_key_rotation     = true
  deletion_window_in_days = 30
}
resource "aws_kms_alias" "data" {
  name          = "alias/rowbound-${var.env}-data"
  target_key_id = aws_kms_key.data.id
}
```
- Switch the S3 bucket default encryption rule from `AES256` to `aws:kms` with
  `kms_master_key_id = aws_kms_key.data.arn` and `bucket_key_enabled = true`.
- Point RDS (`kms_key_id`) and Secrets Manager at customer-managed keys (same key
  or, cleaner for blast-radius, separate keys).
- **CloudTrail on for KMS** → audit trail of every decrypt.
- Pass `aws_kms_key.data.arn` into the app/Rust task env as `S3_SSE_KMS_KEY_ID`
  and `ENVELOPE_KMS_KEY_ID`.

### E4 — Transient-plaintext minimization (infra side)
- S3 lifecycle / purge rule for transient request/collect source data after
  delivery + the dispute window (we're a settlement layer, not a warehouse).
  Keep resold catalog listings longer.
- If the Rust service must spill to disk (e.g. ffmpeg), use an **encrypted
  ephemeral volume** and delete immediately after.

### E6 — Key lifecycle & ops
- Automatic KMS rotation on (set above).
- Least-privilege key policy: `kms:Decrypt`/`GenerateDataKey` scoped to the named
  app + Rust roles only; key **admin** separated from key **use**.
- Snapshots inherit the key — ensure restore roles have key access.
- KMS keys are **regional** — handle cross-region implications before replicating.
- A documented rotation / compromise runbook (below).

---

## Key-access matrix (E5 step 4)

Decryption is deliberately *not* zero-knowledge — the processing roles must read
plaintext to run the product. The matrix is the documented carve-out.

| Role | `kms:Decrypt` / `GenerateDataKey` on data key | Why |
|---|---|---|
| App task role | ✅ | Ingest, deliver, generate per-buyer slices |
| Rust processing role | ✅ | Validate schema, count, dedup-hash, perceptual-hash media |
| KMS key admin | ❌ (manage only, no use) | Separation of duties — rotate/disable, can't read data |
| Everything else (incl. raw S3 read) | ❌ | A leaked object alone is undecryptable ciphertext |

---

## Rotation / compromise runbook (E6)

1. **Suspected key/credential compromise:** disable the suspect IAM role's key
   grant first (stops the bleed), then rotate the affected data key(s).
2. **KMS CMK rotation** is automatic (yearly) and transparent — old data keys stay
   unwrappable by the CMK's prior backing key; no re-encrypt needed for SSE-KMS.
3. **Envelope re-key (if a data key is exposed):** read → decrypt → re-encrypt
   with a fresh `GenerateDataKey` → overwrite the object + wrapped key. The
   `RBE1` envelope header is versioned for exactly this.
4. **Audit:** pull CloudTrail KMS decrypt events for the window; confirm only the
   app + Rust roles appear.
5. **Verify restores:** ensure DR/snapshot restore roles still have key access
   after any policy change.

> Encryption is a mitigating control, not a GDPR compliance program — pair it with
> the [LEGAL] items (lawful basis, consent, DPA, retention policy) from the
> security plan, reviewed by counsel.
