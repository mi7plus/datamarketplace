data "aws_caller_identity" "me" {}

# --- ECS task EXECUTION role (pull image, read secrets for injection, write logs) ---
resource "aws_iam_role" "task_exec" {
  name = "${var.name}-${var.env}-task-exec"
  assume_role_policy = jsonencode({
    Version = "2012-10-17"
    Statement = [{ Effect = "Allow", Principal = { Service = "ecs-tasks.amazonaws.com" }, Action = "sts:AssumeRole" }]
  })
}
resource "aws_iam_role_policy_attachment" "task_exec_managed" {
  role       = aws_iam_role.task_exec.name
  policy_arn = "arn:aws:iam::aws:policy/service-role/AmazonECSTaskExecutionRolePolicy"
}
resource "aws_iam_role_policy" "task_exec_secrets" {
  role = aws_iam_role.task_exec.name
  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [{
      Effect   = "Allow"
      Action   = ["secretsmanager:GetSecretValue"]
      Resource = [aws_secretsmanager_secret.app.arn, aws_db_instance.this.master_user_secret[0].secret_arn]
    }]
  })
}

# --- ECS TASK role (the app's own AWS permissions: just its S3 bucket) ---
resource "aws_iam_role" "task" {
  name = "${var.name}-${var.env}-task"
  assume_role_policy = aws_iam_role.task_exec.assume_role_policy
}
resource "aws_iam_role_policy" "task_s3" {
  role = aws_iam_role.task.name
  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [{
      Effect   = "Allow"
      Action   = ["s3:GetObject", "s3:PutObject", "s3:DeleteObject", "s3:ListBucket"]
      Resource = [aws_s3_bucket.data.arn, "${aws_s3_bucket.data.arn}/*"]
    }]
  })
}

# --- EventBridge Scheduler role (run the sweep task) ---
resource "aws_iam_role" "scheduler" {
  name = "${var.name}-${var.env}-scheduler"
  assume_role_policy = jsonencode({
    Version = "2012-10-17"
    Statement = [{ Effect = "Allow", Principal = { Service = "scheduler.amazonaws.com" }, Action = "sts:AssumeRole" }]
  })
}
resource "aws_iam_role_policy" "scheduler_runtask" {
  role = aws_iam_role.scheduler.name
  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [
      { Effect = "Allow", Action = ["ecs:RunTask"], Resource = ["${aws_ecs_task_definition.app.arn_without_revision}:*"] },
      { Effect = "Allow", Action = ["iam:PassRole"], Resource = [aws_iam_role.task.arn, aws_iam_role.task_exec.arn] }
    ]
  })
}

# --- GitHub OIDC deploy role (no long-lived AWS keys in CI) ---
resource "aws_iam_openid_connect_provider" "github" {
  url             = "https://token.actions.githubusercontent.com"
  client_id_list  = ["sts.amazonaws.com"]
  thumbprint_list = ["6938fd4d98bab03faadb97b34396831e3780aea1"]
}
resource "aws_iam_role" "github_deploy" {
  name = "${var.name}-${var.env}-github-deploy"
  assume_role_policy = jsonencode({
    Version = "2012-10-17"
    Statement = [{
      Effect    = "Allow"
      Principal = { Federated = aws_iam_openid_connect_provider.github.arn }
      Action    = "sts:AssumeRoleWithWebIdentity"
      Condition = {
        StringEquals = { "token.actions.githubusercontent.com:aud" = "sts.amazonaws.com" }
        StringLike   = { "token.actions.githubusercontent.com:sub" = "repo:${var.github_org}/${var.github_repo}:*" }
      }
    }]
  })
}
resource "aws_iam_role_policy" "github_deploy" {
  role = aws_iam_role.github_deploy.name
  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [
      { Effect = "Allow", Action = ["ecr:GetAuthorizationToken"], Resource = "*" },
      { Effect = "Allow", Action = ["ecr:BatchCheckLayerAvailability","ecr:InitiateLayerUpload","ecr:UploadLayerPart","ecr:CompleteLayerUpload","ecr:PutImage","ecr:BatchGetImage","ecr:GetDownloadUrlForLayer"], Resource = aws_ecr_repository.app.arn },
      { Effect = "Allow", Action = ["ecs:RegisterTaskDefinition","ecs:UpdateService","ecs:DescribeServices","ecs:DescribeTaskDefinition","ecs:RunTask","ecs:DescribeTasks"], Resource = "*" },
      { Effect = "Allow", Action = ["iam:PassRole"], Resource = [aws_iam_role.task.arn, aws_iam_role.task_exec.arn] }
    ]
  })
}
