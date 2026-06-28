output "route53_nameservers" {
  description = "Set these 4 NS records at your registrar to delegate the domain (Gate A)."
  value       = aws_route53_zone.primary.name_servers
}

output "api_certificate_arn" {
  value = aws_acm_certificate_validation.api.certificate_arn
}

output "api_domain" {
  value = local.api_domain
}
