# E2 — customer-managed KMS key for data at rest (S3, RDS, Secrets).
# SSE-S3 (AWS-owned key) can't be rotated on your terms, audited per-access, or
# revoked. A CMK gives rotation, CloudTrail access logging, and revocation —
# which matter for GDPR custody and breach posture. Decrypt is granted NARROWLY:
# only the app + Rust ingest task roles, so a leaked object alone is undecryptable.

resource "aws_kms_key" "data" {
  description             = "rowbound ${var.env} data-at-rest"
  enable_key_rotation     = true
  deletion_window_in_days = 30
  # Root retains administrative control; USE is delegated to named roles via the
  # IAM policies below (this avoids a key-policy <-> role dependency cycle).
  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [{
      Sid       = "EnableRootAndIamDelegation"
      Effect    = "Allow"
      Principal = { AWS = "arn:aws:iam::${data.aws_caller_identity.me.account_id}:root" }
      Action    = "kms:*"
      Resource  = "*"
    }]
  })
}

resource "aws_kms_alias" "data" {
  name          = "alias/rowbound-${var.env}-data"
  target_key_id = aws_kms_key.data.id
}

# Narrow decrypt/encrypt grant — app task role + Rust ingest task role only.
data "aws_iam_policy_document" "kms_use" {
  statement {
    effect    = "Allow"
    actions   = ["kms:Decrypt", "kms:GenerateDataKey", "kms:DescribeKey"]
    resources = [aws_kms_key.data.arn]
  }
}

resource "aws_iam_role_policy" "app_kms" {
  role   = aws_iam_role.task.name
  policy = data.aws_iam_policy_document.kms_use.json
}

resource "aws_iam_role_policy" "ingest_kms" {
  role   = aws_iam_role.ingest_task.name
  policy = data.aws_iam_policy_document.kms_use.json
}

# The ECS execution role decrypts Secrets Manager values at task start, so it needs
# Decrypt on the key the secrets are encrypted under.
resource "aws_iam_role_policy" "task_exec_kms" {
  role = aws_iam_role.task_exec.name
  policy = jsonencode({
    Version   = "2012-10-17"
    Statement = [{ Effect = "Allow", Action = ["kms:Decrypt"], Resource = [aws_kms_key.data.arn] }]
  })
}

# --- CloudTrail: an audit trail of every KMS use (Decrypt/GenerateDataKey) ---
resource "aws_s3_bucket" "trail" {
  bucket        = "${var.name}-${var.env}-cloudtrail-${data.aws_caller_identity.me.account_id}"
  force_destroy = false
}

resource "aws_s3_bucket_public_access_block" "trail" {
  bucket                  = aws_s3_bucket.trail.id
  block_public_acls       = true
  block_public_policy     = true
  ignore_public_acls      = true
  restrict_public_buckets = true
}

data "aws_iam_policy_document" "trail_bucket" {
  statement {
    sid    = "AWSCloudTrailAclCheck"
    effect = "Allow"
    principals {
      type        = "Service"
      identifiers = ["cloudtrail.amazonaws.com"]
    }
    actions   = ["s3:GetBucketAcl"]
    resources = [aws_s3_bucket.trail.arn]
  }
  statement {
    sid    = "AWSCloudTrailWrite"
    effect = "Allow"
    principals {
      type        = "Service"
      identifiers = ["cloudtrail.amazonaws.com"]
    }
    actions   = ["s3:PutObject"]
    resources = ["${aws_s3_bucket.trail.arn}/AWSLogs/${data.aws_caller_identity.me.account_id}/*"]
    condition {
      test     = "StringEquals"
      variable = "s3:x-amz-acl"
      values   = ["bucket-owner-full-control"]
    }
  }
}

resource "aws_s3_bucket_policy" "trail" {
  bucket = aws_s3_bucket.trail.id
  policy = data.aws_iam_policy_document.trail_bucket.json
}

resource "aws_cloudtrail" "main" {
  name                          = "${var.name}-${var.env}"
  s3_bucket_name                = aws_s3_bucket.trail.id
  include_global_service_events = true
  is_multi_region_trail         = true
  enable_log_file_validation    = true
  depends_on                    = [aws_s3_bucket_policy.trail]
  # Management events (default) include KMS Decrypt/GenerateDataKey calls.
}
