resource "aws_db_subnet_group" "this" {
  name       = "${var.name}-${var.env}"
  subnet_ids = module.vpc.private_subnets
}

resource "aws_db_instance" "this" {
  identifier            = "${var.name}-${var.env}"
  engine                = "postgres"
  engine_version        = var.db_engine_version
  instance_class        = var.db_instance_class
  allocated_storage     = 20
  max_allocated_storage = 100 # storage autoscaling

  db_name  = var.db_name
  username = var.db_username
  # AWS manages the master password in Secrets Manager — no password in TF state.
  manage_master_user_password = true

  db_subnet_group_name   = aws_db_subnet_group.this.name
  vpc_security_group_ids = [aws_security_group.rds.id]
  publicly_accessible    = false
  storage_encrypted      = true

  backup_retention_period   = 7
  deletion_protection       = true
  skip_final_snapshot       = false
  final_snapshot_identifier = "${var.name}-${var.env}-final"
}
