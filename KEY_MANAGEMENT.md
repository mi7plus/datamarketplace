# Encryption & Key Management

Implements `rowbound-encryption-key-management.md`. **Scope split:** the
application-layer controls live in `backend/`; the AWS/Terraform controls now live
in this repo's `infra/` (see `infra/kms.tf`). Both are committed; the Terraform is
`terraform validate`-clean but must still be `terraform apply`-ed against a real
account, and the live-env confirmations (E1.1/E1.2) verified there.

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
| **E2** CMK (infra) | `infra/kms.tf`, `s3.tf`, `rds.tf`, `secrets.tf` | `aws_kms_key.data` (rotation on, 30-day window) + alias; S3 default enc `aws:kms` + `bucket_key_enabled`; RDS `kms_key_id`; Secrets `kms_key_id`; Decrypt/GenerateDataKey scoped to the app + ingest roles; CloudTrail (multi-region) for KMS audit. CMK ARN wired into both task defs as `S3_SSE_KMS_KEY_ID` + `ENVELOPE_KMS_KEY_ID`. |

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

### E2.1 — Customer-managed KMS key — ✅ IMPLEMENTED in `infra/kms.tf`
`aws_kms_key.data` + alias (rotation on, 30-day window); S3 default encryption
switched to `aws:kms` + `bucket_key_enabled`; RDS `kms_key_id` and Secrets Manager
`kms_key_id` point at the CMK; CloudTrail (multi-region, log-file validation)
records every KMS use; the CMK ARN is wired into the app + ingest task envs as
`S3_SSE_KMS_KEY_ID` and `ENVELOPE_KMS_KEY_ID`. Remaining: `terraform apply` and
confirm CloudTrail shows only the app + ingest roles decrypting. (A single CMK is
used for S3/RDS/Secrets; split into separate keys later if you want tighter
blast-radius isolation.)

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
