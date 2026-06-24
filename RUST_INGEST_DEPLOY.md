# Rust Ingest Service — Deploy (P4) & Hardening (P5)

Implements P4/P5 of `rowbound-rust-ingest-service-plan.md`. The Terraform belongs
in the separate **`rowbound-deploy/infra`** repo (same split as the encryption
track) — this file is the spec to apply there. Apply via `terraform plan` review;
never put secrets in the repo or state.

## Topology

```
                       ┌─────────────────────────────┐
  upload ─► FastAPI ───┤ S3 (raw)  +  SQS (ingest)    │
  (PENDING)            └──────────────┬──────────────┘
                                      │ consume
                          ┌───────────▼───────────┐
                          │ Fargate WORKERS (Rust)│  autoscale on queue depth
                          │  validate/hash/media  │
                          └───────────┬───────────┘
            COPY key hashes           │ POST /internal/ingest-result
        submission_key_staging ◄──────┤   (Python flips VALIDATED/REJECTED)
                                      ▼
                          Fargate SERVICE (Rust /health, sync /ingest)
```

Python remains the **single writer** to the core schema; Rust writes only
`submission_key_staging` + derived S3 artifacts.

## P4 — Terraform sketch (`rowbound-deploy/infra`)

### ECR + SQS (with DLQ)
```hcl
resource "aws_ecr_repository" "ingest" {
  name = "rowbound-${var.env}-ingest"
}

resource "aws_sqs_queue" "ingest_dlq" {
  name                      = "rowbound-${var.env}-ingest-dlq"
  message_retention_seconds = 1209600 # 14 days
}

resource "aws_sqs_queue" "ingest" {
  name                       = "rowbound-${var.env}-ingest"
  visibility_timeout_seconds = 900     # >= worker visibility_timeout (large media)
  redrive_policy = jsonencode({
    deadLetterTargetArn = aws_sqs_queue.ingest_dlq.arn
    maxReceiveCount     = 5            # poison jobs -> DLQ after 5 tries
  })
}
```

### Scoped IAM (least privilege — the key safety property)
```hcl
data "aws_iam_policy_document" "ingest_task" {
  statement {                                   # source + derived artifacts only
    actions   = ["s3:GetObject", "s3:PutObject"]
    resources = ["${aws_s3_bucket.data.arn}/*"]
  }
  statement {                                   # consume the queue
    actions   = ["sqs:ReceiveMessage", "sqs:DeleteMessage", "sqs:GetQueueAttributes"]
    resources = [aws_sqs_queue.ingest.arn]
  }
  statement {                                   # decrypt for envelope datasets (E5)
    actions   = ["kms:Decrypt", "kms:GenerateDataKey"]
    resources = [aws_kms_key.data.arn]
  }
}
# NOTE: the DB grant for this task's DATABASE_URL must be a role with privileges
# ONLY on submission_key_staging (INSERT/DELETE/SELECT). No grants on money/
# lifecycle tables — enforce in SQL: GRANT ... ON submission_key_staging TO ingest;
```

### Fargate service + workers
- **Service** (`/health`, sync `/ingest`): 1–2 tasks, small CPU.
- **Workers** (SQS consumers): autoscale on `ApproximateNumberOfMessagesVisible`.
  Media workers get **more CPU/memory + longer timeouts** than tabular.
- Same VPC/subnets as FastAPI + RDS; security group allows egress to S3/SQS/KMS
  and the Postgres port. ffmpeg ships in the image (see `rust-ingest/Dockerfile`).

### Build/push
```bash
aws ecr get-login-password | docker login --username AWS --password-stdin <ecr>
docker build -t <ecr>/rowbound-ingest:$(git rev-parse --short HEAD) rust-ingest
docker push <ecr>/rowbound-ingest:...
```

## Runtime env (task definition)

| Var | Purpose |
|---|---|
| `S3_BUCKET`, `S3_ENDPOINT_URL` | source + artifacts (endpoint empty on real AWS) |
| `INGEST_SQS_QUEUE_URL` | queue to consume (unset → sync-only) |
| `INGEST_WORKER_CONCURRENCY` | consumer tasks per worker |
| `DATABASE_URL` | staging-table-scoped role |
| `INGEST_CALLBACK_BASE_URL` | FastAPI internal URL |
| `INGEST_INTERNAL_TOKEN` | shared secret for callback + sync gate |
| `INGEST_MAX_FILE_BYTES` | oversize/decompression-bomb cap (P5) |
| `INGEST_METRICS_ADDR` | Prometheus exporter bind |

## P5 — Hardening & observability (in code + infra)

- **DLQ + redrive:** above (poison jobs isolated, retained 14 days).
- **Idempotency:** jobs keyed `submission_id + content_hash`; staging is
  delete-then-COPY; the Python callback is a no-op on non-PENDING submissions.
- **Resource caps:** `INGEST_MAX_FILE_BYTES` enforced on S3 fetch (`storage.rs`);
  corrupt media → `REJECTED_INVALID` rather than a crash.
- **Metrics:** `ingest_jobs_total`, `ingest_job_duration_seconds`,
  `ingest_records_total` (`metrics.rs`). Alert on DLQ depth + queue backlog.
- **Structured logs:** JSON tracing; correlate by `job_id` / `submission_id`.

## Cutover sequence (P1 → P2)

1. Deploy workers; keep Python ingest authoritative.
2. `INGEST_SHADOW_ENABLED=true` on FastAPI → log parity divergences on real traffic.
3. When parity holds, `INGEST_RUST_ENABLED=true` and switch allocation to the
   `submission_key_staging` EXCEPT anti-join inside the existing locked
   transaction. **The real-DB allocation/dedup tests stay green throughout.**
