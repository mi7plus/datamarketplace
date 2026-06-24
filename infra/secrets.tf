# App-level secrets you populate (DB master secret is created by RDS automatically).
# Create empty, then set values via console/CLI or a separate process — NOT in TF state.
resource "aws_secretsmanager_secret" "app" {
  name       = "${var.name}/${var.env}/app"
  kms_key_id = aws_kms_key.data.arn # CMK (E2)
}

# Placeholder version so ECS can reference keys; replace values out-of-band.
resource "aws_secretsmanager_secret_version" "app" {
  secret_id = aws_secretsmanager_secret.app.id
  secret_string = jsonencode({
    SECRET_KEY            = "REPLACE_ME"
    STRIPE_SECRET_KEY     = "REPLACE_ME"
    STRIPE_WEBHOOK_SECRET = "REPLACE_ME"
    # Shared secret the ingest worker presents to POST /internal/ingest-result,
    # and the full DATABASE_URL the worker's sqlx pool connects with.
    INGEST_CALLBACK_SECRET = "REPLACE_ME"
    DATABASE_URL           = "REPLACE_ME"
  })
  lifecycle { ignore_changes = [secret_string] } # don't clobber real values on apply
}
