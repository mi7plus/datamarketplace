resource "aws_s3_bucket" "data" {
  bucket = "${var.name}-${var.env}-data-${data.aws_caller_identity.me.account_id}"
}

resource "aws_s3_bucket_public_access_block" "data" {
  bucket                  = aws_s3_bucket.data.id
  block_public_acls       = true
  block_public_policy     = true
  ignore_public_acls      = true
  restrict_public_buckets = true
}

resource "aws_s3_bucket_server_side_encryption_configuration" "data" {
  bucket = aws_s3_bucket.data.id
  rule { apply_server_side_encryption_by_default { sse_algorithm = "AES256" } }
}

resource "aws_s3_bucket_versioning" "data" {
  bucket = aws_s3_bucket.data.id
  versioning_configuration { status = "Enabled" }
}

# Cost/liability control: tier old objects down; expire transient prefixes.
# Adjust prefixes to match how storage.py lays out keys (e.g. submissions/, listings/).
resource "aws_s3_bucket_lifecycle_configuration" "data" {
  bucket = aws_s3_bucket.data.id

  rule {
    id     = "tier-down-unsold"
    status = "Enabled"
    filter { prefix = "listings/" }
    transition { days = 60  storage_class = "STANDARD_IA" }
    transition { days = 180 storage_class = "GLACIER" }
  }

  rule {
    id     = "expire-transient-deliveries"
    status = "Enabled"
    filter { prefix = "submissions/" }   # purge after delivery + dispute window
    expiration { days = 30 }             # TODO: set to (window + buffer) per policy
  }
}
