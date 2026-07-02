locals {
  db_secret_arn = aws_db_instance.this.master_user_secret[0].secret_arn

  # Non-secret env for the container
  app_environment = [
    { name = "AWS_REGION", value = var.region },
    { name = "USE_S3", value = "true" }, # real AWS S3 via the task role (storage.py)
    { name = "S3_BUCKET", value = aws_s3_bucket.data.bucket },
    # E2/E5: the CMK the app uses for SSE-KMS puts + envelope-encrypting sensitive data.
    { name = "S3_SSE_KMS_KEY_ID", value = aws_kms_key.data.arn },
    { name = "ENVELOPE_KMS_KEY_ID", value = aws_kms_key.data.arn },
    { name = "POSTGRES_HOST", value = aws_db_instance.this.address },
    { name = "POSTGRES_PORT", value = "5432" },
    { name = "POSTGRES_DB", value = var.db_name },
    { name = "FRONTEND_URL", value = var.frontend_url },
    # Public base of the API itself — used to build email-verification links and the
    # OAuth redirect_uri. MUST be the real https host or Google rejects the callback
    # (default is http://localhost:3001, which only works for local dev).
    { name = "PUBLIC_API_URL", value = "https://${local.api_domain}" },
    { name = "STRIPE_USE_REAL", value = var.stripe_use_real },
    # Disable the in-process scheduler — the sweep runs as an EventBridge singleton
    # (scheduler.tf). The env var name must match app/sweep.py (SWEEP_ENABLED).
    { name = "SWEEP_ENABLED", value = "false" },
    # Ingest queue the app enqueues jobs onto (the Rust worker consumes it).
    { name = "INGEST_QUEUE_URL", value = aws_sqs_queue.ingest.url },
  ]

  # Secrets injected from Secrets Manager (ARN:json-key::)
  app_secrets = [
    { name = "POSTGRES_USER", valueFrom = "${local.db_secret_arn}:username::" },
    { name = "POSTGRES_PASSWORD", valueFrom = "${local.db_secret_arn}:password::" },
    { name = "SECRET_KEY", valueFrom = "${aws_secretsmanager_secret.app.arn}:SECRET_KEY::" },
    { name = "STRIPE_SECRET_KEY", valueFrom = "${aws_secretsmanager_secret.app.arn}:STRIPE_SECRET_KEY::" },
    { name = "STRIPE_WEBHOOK_SECRET", valueFrom = "${aws_secretsmanager_secret.app.arn}:STRIPE_WEBHOOK_SECRET::" },
    # The app verifies this against the X-Internal-Secret header on callbacks.
    { name = "INGEST_CALLBACK_SECRET", valueFrom = "${aws_secretsmanager_secret.app.arn}:INGEST_CALLBACK_SECRET::" },
    # Social login (Google OIDC). Keys must exist in the rowbound/prod/app secret JSON.
    { name = "GOOGLE_CLIENT_ID", valueFrom = "${aws_secretsmanager_secret.app.arn}:GOOGLE_CLIENT_ID::" },
    { name = "GOOGLE_CLIENT_SECRET", valueFrom = "${aws_secretsmanager_secret.app.arn}:GOOGLE_CLIENT_SECRET::" },
  ]
}

resource "aws_cloudwatch_log_group" "app" {
  name              = "/ecs/${var.name}-${var.env}"
  retention_in_days = 30
}

resource "aws_ecs_cluster" "this" {
  name = "${var.name}-${var.env}"
  setting {
    name  = "containerInsights"
    value = "enabled"
  }
}

resource "aws_ecs_task_definition" "app" {
  family                   = "${var.name}-${var.env}"
  requires_compatibilities = ["FARGATE"]
  network_mode             = "awsvpc"
  cpu                      = var.app_cpu
  memory                   = var.app_memory
  execution_role_arn       = aws_iam_role.task_exec.arn
  task_role_arn            = aws_iam_role.task.arn

  container_definitions = jsonencode([{
    name         = "app"
    image        = "${aws_ecr_repository.app.repository_url}:${var.app_image_tag}"
    essential    = true
    portMappings = [{ containerPort = 8000 }]
    environment  = local.app_environment
    secrets      = local.app_secrets
    logConfiguration = {
      logDriver = "awslogs"
      options = {
        "awslogs-group"         = aws_cloudwatch_log_group.app.name
        "awslogs-region"        = var.region
        "awslogs-stream-prefix" = "app"
      }
    }
  }])
}

# --- ALB ---
resource "aws_lb" "this" {
  name               = "${var.name}-${var.env}"
  load_balancer_type = "application"
  subnets            = module.vpc.public_subnets
  security_groups    = [aws_security_group.alb.id]
}
resource "aws_lb_target_group" "app" {
  name        = "${var.name}-${var.env}"
  port        = 8000
  protocol    = "HTTP"
  vpc_id      = module.vpc.vpc_id
  target_type = "ip"
  health_check {
    path    = "/health"
    matcher = "200"
  }
}
resource "aws_lb_listener" "https" {
  load_balancer_arn = aws_lb.this.arn
  port              = 443
  protocol          = "HTTPS"
  ssl_policy        = "ELBSecurityPolicy-TLS13-1-2-2021-06"
  certificate_arn   = aws_acm_certificate_validation.api.certificate_arn
  default_action {
    type             = "forward"
    target_group_arn = aws_lb_target_group.app.arn
  }
}
resource "aws_lb_listener" "http_redirect" {
  load_balancer_arn = aws_lb.this.arn
  port              = 80
  protocol          = "HTTP"
  default_action {
    type = "redirect"
    redirect {
      port        = "443"
      protocol    = "HTTPS"
      status_code = "HTTP_301"
    }
  }
}

# --- Service ---
resource "aws_ecs_service" "app" {
  name            = "${var.name}-${var.env}"
  cluster         = aws_ecs_cluster.this.id
  task_definition = aws_ecs_task_definition.app.arn
  desired_count   = var.app_desired
  launch_type     = "FARGATE"

  network_configuration {
    subnets          = module.vpc.private_subnets
    security_groups  = [aws_security_group.app.id]
    assign_public_ip = false
  }
  load_balancer {
    target_group_arn = aws_lb_target_group.app.arn
    container_name   = "app"
    container_port   = 8000
  }
  depends_on = [aws_lb_listener.https]
  lifecycle { ignore_changes = [task_definition, desired_count] } # CI manages the running revision
}
