# Rust ingest service (P4) — its own ECR image, an SQS work queue + DLQ, an HTTP
# service (sync small files) and an autoscaling worker pool (SQS consumers). The
# worker writes ONLY derived artifacts + the dedup staging table and calls Python's
# /internal/ingest-result; Python stays the sole writer to money/lifecycle tables.

# --- ECR ---
resource "aws_ecr_repository" "ingest" {
  name                 = "${var.name}-ingest"
  image_tag_mutability = "MUTABLE"
  image_scanning_configuration {
    scan_on_push = true
  }
}

# --- SQS work queue + dead-letter queue ---
resource "aws_sqs_queue" "ingest_dlq" {
  name                      = "${var.name}-${var.env}-ingest-dlq"
  message_retention_seconds = 1209600 # 14 days
}

resource "aws_sqs_queue" "ingest" {
  name                       = "${var.name}-${var.env}-ingest"
  visibility_timeout_seconds = 900 # ≥ worst-case job time; big media gets a long lease
  redrive_policy = jsonencode({
    deadLetterTargetArn = aws_sqs_queue.ingest_dlq.arn
    maxReceiveCount     = 5 # poison jobs land in the DLQ after 5 tries
  })
}

# --- IAM: ingest task role (S3 bucket + this queue only; NO money tables) ---
resource "aws_iam_role" "ingest_task" {
  name               = "${var.name}-${var.env}-ingest-task"
  assume_role_policy = aws_iam_role.task_exec.assume_role_policy
}
resource "aws_iam_role_policy" "ingest_task" {
  role = aws_iam_role.ingest_task.name
  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [
      {
        Effect   = "Allow"
        Action   = ["s3:GetObject", "s3:PutObject", "s3:ListBucket"]
        Resource = [aws_s3_bucket.data.arn, "${aws_s3_bucket.data.arn}/*"]
      },
      {
        Effect   = "Allow"
        Action   = ["sqs:ReceiveMessage", "sqs:DeleteMessage", "sqs:GetQueueAttributes"]
        Resource = [aws_sqs_queue.ingest.arn]
      },
    ]
  })
}

# Let the APP enqueue jobs onto the ingest queue (send only).
resource "aws_iam_role_policy" "app_sqs_send" {
  role = aws_iam_role.task.name
  policy = jsonencode({
    Version   = "2012-10-17"
    Statement = [{ Effect = "Allow", Action = ["sqs:SendMessage"], Resource = [aws_sqs_queue.ingest.arn] }]
  })
}
# The ingest task execution role reuses task_exec (already allowed to read the
# app + DB secrets and write logs).

resource "aws_cloudwatch_log_group" "ingest" {
  name              = "/ecs/${var.name}-ingest-${var.env}"
  retention_in_days = 30
}

locals {
  ingest_image = "${aws_ecr_repository.ingest.repository_url}:${var.ingest_image_tag}"

  ingest_env = [
    { name = "AWS_REGION", value = var.region },
    { name = "USE_S3", value = "true" },
    { name = "S3_BUCKET", value = aws_s3_bucket.data.bucket },
    { name = "INGEST_QUEUE_URL", value = aws_sqs_queue.ingest.url },
    # The worker calls the app's internal callback over the private network.
    { name = "PY_INTERNAL_BASE", value = "http://${aws_lb.this.dns_name}" },
  ]
  ingest_secrets = [
    { name = "DATABASE_URL", valueFrom = "${aws_secretsmanager_secret.app.arn}:DATABASE_URL::" },
    { name = "INGEST_CALLBACK_SECRET", valueFrom = "${aws_secretsmanager_secret.app.arn}:INGEST_CALLBACK_SECRET::" },
  ]
}

# --- HTTP service task (sync small-file path) ---
resource "aws_ecs_task_definition" "ingest_http" {
  family                   = "${var.name}-${var.env}-ingest-http"
  requires_compatibilities = ["FARGATE"]
  network_mode             = "awsvpc"
  cpu                      = 512
  memory                   = 1024
  execution_role_arn       = aws_iam_role.task_exec.arn
  task_role_arn            = aws_iam_role.ingest_task.arn

  container_definitions = jsonencode([{
    name         = "ingest"
    image        = local.ingest_image
    essential    = true
    portMappings = [{ containerPort = 8081 }]
    environment  = local.ingest_env
    logConfiguration = {
      logDriver = "awslogs"
      options = {
        "awslogs-group"         = aws_cloudwatch_log_group.ingest.name
        "awslogs-region"        = var.region
        "awslogs-stream-prefix" = "http"
      }
    }
  }])
}

# --- Worker task (SQS consumer; same image, `worker` command, more memory) ---
resource "aws_ecs_task_definition" "ingest_worker" {
  family                   = "${var.name}-${var.env}-ingest-worker"
  requires_compatibilities = ["FARGATE"]
  network_mode             = "awsvpc"
  cpu                      = 1024
  memory                   = 2048 # media is memory-hungry
  execution_role_arn       = aws_iam_role.task_exec.arn
  task_role_arn            = aws_iam_role.ingest_task.arn

  container_definitions = jsonencode([{
    name        = "ingest"
    image       = local.ingest_image
    essential   = true
    command     = ["rowbound-ingest", "worker"]
    environment = local.ingest_env
    secrets     = local.ingest_secrets
    logConfiguration = {
      logDriver = "awslogs"
      options = {
        "awslogs-group"         = aws_cloudwatch_log_group.ingest.name
        "awslogs-region"        = var.region
        "awslogs-stream-prefix" = "worker"
      }
    }
  }])
}

resource "aws_ecs_service" "ingest_http" {
  name            = "${var.name}-${var.env}-ingest-http"
  cluster         = aws_ecs_cluster.this.id
  task_definition = aws_ecs_task_definition.ingest_http.arn
  desired_count   = 1
  launch_type     = "FARGATE"
  network_configuration {
    subnets          = module.vpc.private_subnets
    security_groups  = [aws_security_group.app.id]
    assign_public_ip = false
  }
  lifecycle { ignore_changes = [task_definition, desired_count] }
}

resource "aws_ecs_service" "ingest_worker" {
  name            = "${var.name}-${var.env}-ingest-worker"
  cluster         = aws_ecs_cluster.this.id
  task_definition = aws_ecs_task_definition.ingest_worker.arn
  desired_count   = 1
  launch_type     = "FARGATE"
  network_configuration {
    subnets          = module.vpc.private_subnets
    security_groups  = [aws_security_group.app.id]
    assign_public_ip = false
  }
  lifecycle { ignore_changes = [task_definition, desired_count] }
}

# --- Autoscale the worker pool on queue backlog ---
resource "aws_appautoscaling_target" "ingest_worker" {
  max_capacity       = 10
  min_capacity       = 1
  resource_id        = "service/${aws_ecs_cluster.this.name}/${aws_ecs_service.ingest_worker.name}"
  scalable_dimension = "ecs:service:DesiredCount"
  service_namespace  = "ecs"
}

# Target-track on visible messages PER running task so the pool grows with backlog.
resource "aws_appautoscaling_policy" "ingest_worker_backlog" {
  name               = "${var.name}-${var.env}-ingest-backlog"
  policy_type        = "TargetTrackingScaling"
  resource_id        = aws_appautoscaling_target.ingest_worker.resource_id
  scalable_dimension = aws_appautoscaling_target.ingest_worker.scalable_dimension
  service_namespace  = aws_appautoscaling_target.ingest_worker.service_namespace

  target_tracking_scaling_policy_configuration {
    target_value       = 20 # ~messages-visible per task; tune to job duration
    scale_in_cooldown  = 120
    scale_out_cooldown = 30
    customized_metric_specification {
      metrics {
        label = "messages visible"
        id    = "m1"
        metric_stat {
          metric {
            namespace   = "AWS/SQS"
            metric_name = "ApproximateNumberOfMessagesVisible"
            dimensions {
              name  = "QueueName"
              value = aws_sqs_queue.ingest.name
            }
          }
          stat = "Average"
        }
        return_data = true
      }
    }
  }
}
