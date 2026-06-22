variable "region"  { type = string }
variable "env"     { type = string  default = "prod" }
variable "name"    { type = string  default = "rowbound" }

# Networking
variable "vpc_cidr" { type = string default = "10.0.0.0/16" }
variable "azs"      { type = list(string) }   # e.g. ["eu-west-1a","eu-west-1b"]

# RDS
variable "db_name"           { type = string default = "rowbound" }
variable "db_username"       { type = string default = "rowbound" }
variable "db_instance_class" { type = string default = "db.t4g.micro" }
variable "db_engine_version" { type = string default = "16" }   # match your local PG major

# App
variable "app_image_tag"  { type = string default = "latest" }   # CI overrides per deploy
variable "app_cpu"        { type = number default = 512 }
variable "app_memory"     { type = number default = 1024 }
variable "app_desired"    { type = number default = 2 }
variable "frontend_url"   { type = string }                      # deployed Nuxt origin (for CORS)
variable "stripe_use_real"{ type = string default = "true" }

# DNS / TLS
variable "acm_certificate_arn" { type = string }                 # cert for the ALB (api domain)

# CI/CD (GitHub OIDC)
variable "github_org"  { type = string }                         # e.g. "mi7plus"
variable "github_repo" { type = string default = "datamarketplace" }
