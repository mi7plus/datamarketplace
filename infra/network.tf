# VPC via the community module (concise + battle-tested).
module "vpc" {
  source  = "terraform-aws-modules/vpc/aws"
  version = "~> 5.8"

  name = "${var.name}-${var.env}"
  cidr = var.vpc_cidr
  azs  = var.azs

  public_subnets  = [for i, _ in var.azs : cidrsubnet(var.vpc_cidr, 4, i)]
  private_subnets = [for i, _ in var.azs : cidrsubnet(var.vpc_cidr, 4, i + 8)]

  enable_nat_gateway   = true
  single_nat_gateway   = true   # cost-saving for MVP; HA NAT later
  enable_dns_hostnames = true
}

# --- Security groups ---
resource "aws_security_group" "alb" {
  name_prefix = "${var.name}-alb-"
  vpc_id      = module.vpc.vpc_id
  ingress { from_port = 443 to_port = 443 protocol = "tcp" cidr_blocks = ["0.0.0.0/0"] }
  ingress { from_port = 80  to_port = 80  protocol = "tcp" cidr_blocks = ["0.0.0.0/0"] }
  egress  { from_port = 0   to_port = 0   protocol = "-1"  cidr_blocks = ["0.0.0.0/0"] }
  lifecycle { create_before_destroy = true }
}

resource "aws_security_group" "app" {
  name_prefix = "${var.name}-app-"
  vpc_id      = module.vpc.vpc_id
  ingress {
    from_port       = 8000 to_port = 8000 protocol = "tcp"
    security_groups = [aws_security_group.alb.id]   # only the ALB may reach the app
  }
  egress { from_port = 0 to_port = 0 protocol = "-1" cidr_blocks = ["0.0.0.0/0"] }
  lifecycle { create_before_destroy = true }
}

resource "aws_security_group" "rds" {
  name_prefix = "${var.name}-rds-"
  vpc_id      = module.vpc.vpc_id
  ingress {
    from_port       = 5432 to_port = 5432 protocol = "tcp"
    security_groups = [aws_security_group.app.id]   # only the app may reach Postgres
  }
  lifecycle { create_before_destroy = true }
}
