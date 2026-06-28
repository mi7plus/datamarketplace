# Route 53 hosted zone + ACM cert for the API (provisioned FIRST so the
# nameservers can be delegated at the registrar before the rest applies).
# The API is served at api.<domain_name>; the frontend (app.<domain_name>) is
# Amplify and handled out of band (human gate).

locals {
  api_domain = "api.${var.domain_name}"
}

resource "aws_route53_zone" "primary" {
  name = var.domain_name
}

# DNS-validated cert for the API hostname (the ALB HTTPS listener uses it).
resource "aws_acm_certificate" "api" {
  domain_name       = local.api_domain
  validation_method = "DNS"
  lifecycle {
    create_before_destroy = true
  }
}

resource "aws_route53_record" "api_cert_validation" {
  for_each = {
    for dvo in aws_acm_certificate.api.domain_validation_options : dvo.domain_name => {
      name   = dvo.resource_record_name
      type   = dvo.resource_record_type
      record = dvo.resource_record_value
    }
  }
  zone_id         = aws_route53_zone.primary.zone_id
  name            = each.value.name
  type            = each.value.type
  records         = [each.value.record]
  ttl             = 60
  allow_overwrite = true
}

resource "aws_acm_certificate_validation" "api" {
  certificate_arn         = aws_acm_certificate.api.arn
  validation_record_fqdns = [for r in aws_route53_record.api_cert_validation : r.fqdn]
}

# api.<domain> → the ALB.
resource "aws_route53_record" "api" {
  zone_id = aws_route53_zone.primary.zone_id
  name    = local.api_domain
  type    = "A"
  alias {
    name                   = aws_lb.this.dns_name
    zone_id                = aws_lb.this.zone_id
    evaluate_target_health = true
  }
}
