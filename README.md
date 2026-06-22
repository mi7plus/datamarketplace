# Rowbound — AWS deploy assets

Claude Code-ready starting files for the AWS deployment plan. **A reviewable skeleton, not a turnkey prod config** — run `terraform plan` and read every change before applying. Pairs with `rowbound-aws-deployment-plan.md`.

## Layout
```
backend/Dockerfile            FastAPI image (gunicorn + uvicorn workers, non-root, /health)
backend/.dockerignore
infra/                        Terraform (VPC, RDS, S3, Secrets, IAM, ECR, ECS+ALB, sweep schedule, OIDC)
.github/workflows/deploy.yml  OIDC → build/push ECR → migrate (one-off task) → roll ECS
```
These mirror the repo's own `backend/` and `.github/workflows/` — copy them in (don't overwrite your existing `ci.yml`; `deploy.yml` is separate).

## Order of operations
1. **Code prep (Phase 2) — done in this repo:** `app/main.py` exposes `GET /health` (+ deep `GET /health/db`); `storage.py` uses **real S3** when `USE_S3=true` (no endpoint → AWS, task-role creds, bucket region, SigV4 presigning); `db.py` accepts `DATABASE_URL` (12-factor) with a `POSTGRES_*` fallback; the app does **not** run migrations or `create_all` at startup; the in-process sweep is gated off via `SWEEP_ENABLED=false` (the EventBridge schedule runs `python -m app.sweep` instead).
2. **Provision infra:**
   ```
   cd infra
   cp terraform.tfvars.example terraform.tfvars   # fill region, azs, acm_certificate_arn, frontend_url, github_*
   terraform init && terraform plan && terraform apply
   ```
   (Create an ACM cert for your api domain first; put its ARN in tfvars.)
3. **Populate app secrets** (out-of-band, not in TF state): set real values on the `rowbound/prod/app` secret (`SECRET_KEY`, `STRIPE_SECRET_KEY`, `STRIPE_WEBHOOK_SECRET`). The DB master secret is created by RDS automatically.
4. **Wire CI:** in `deploy.yml` replace `<ACCOUNT_ID>` with your account and confirm `AWS_REGION`/names match the terraform outputs. Push the first image (the ECS service needs an image to become healthy — either let `deploy.yml` run, or push a `:latest` manually once).
5. **DNS/TLS:** point the api domain at the ALB and the app domain at Amplify/CloudFront (Route 53 + ACM).
6. **Stripe webhook:** register `https://<api-domain>/<webhook-path>`; store its signing secret in the app secret.
7. **Frontend:** connect the repo to Amplify Hosting (SSR), set `NUXT_PUBLIC_API_BASE` to the api URL.

## Deliberate design choices
- **Migrations run as a one-off Fargate task before traffic shifts** — never from the autoscaled service (would race across tasks).
- **The sweep is a singleton** via EventBridge Scheduler → one Fargate run-task (`python -m app.sweep`), replacing in-process APScheduler so it can't fire per-instance.
- **No static AWS keys in CI** — GitHub OIDC assumes `*-github-deploy`.
- **No secrets in state/repo** — app secret values are set out-of-band; `ignore_changes` keeps Terraform from clobbering them.
- **RDS master password is AWS-managed** (`manage_master_user_password`) — never in TF state.

## Before real users
Run the security plan's **S1 (authz/IDOR)** and **S3 (payout redirection)** items first, and the Phase 10 hardening (WAF, scoped IAM, backups, secrets CI check). Deploying ≠ safe to open.

## Known TODOs / placeholders
- `<ACCOUNT_ID>`, cert ARN, domains, region, and subnet/SG ids in `deploy.yml` (or wire them via SSM params / terraform outputs).
- Confirm `db_engine_version` matches your local Postgres major.
- Tune S3 lifecycle prefixes in `s3.tf` to your actual key layout.
- `single_nat_gateway = true` is a cost-saving MVP choice; use HA NAT for prod resilience.
