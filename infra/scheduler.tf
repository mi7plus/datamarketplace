# Singleton auto-release sweep: EventBridge Scheduler runs ONE Fargate task on a cron,
# reusing the app image with command override `python -m app.sweep`.
# This replaces the in-process APScheduler (disabled via SWEEP_ENABLED=false in compute.tf).
resource "aws_scheduler_schedule" "sweep" {
  name = "${var.name}-${var.env}-auto-release-sweep"
  flexible_time_window { mode = "OFF" }
  schedule_expression = "rate(15 minutes)"

  target {
    arn      = aws_ecs_cluster.this.arn
    role_arn = aws_iam_role.scheduler.arn

    ecs_parameters {
      task_definition_arn = aws_ecs_task_definition.app.arn_without_revision
      launch_type         = "FARGATE"
      network_configuration {
        subnets          = module.vpc.private_subnets
        security_groups  = [aws_security_group.app.id]
        assign_public_ip = false
      }
    }

    input = jsonencode({
      containerOverrides = [{
        name    = "app"
        command = ["python", "-m", "app.sweep"]
      }]
    })
  }
}
