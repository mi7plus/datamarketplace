terraform {
  required_version = ">= 1.6"
  required_providers {
    aws = {
      source  = "hashicorp/aws"
      version = "~> 5.50"
    }
  }
  # Recommended: remote state. Create the bucket + lock table once, then uncomment.
  backend "s3" {
     bucket         = "rowbound-tfstate-461236647042"
     key            = "rowbound/terraform.tfstate"
     region         = "eu-north-1"
     dynamodb_table = "rowbound-tflock"
     encrypt        = true
  }
}

provider "aws" {
  region = var.region
  default_tags {
    tags = {
      Project   = "rowbound"
      Env       = var.env
      ManagedBy = "terraform"
    }
  }
}
