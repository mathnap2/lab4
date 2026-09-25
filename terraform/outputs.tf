output "alb_dns_name" {
  description = "Public DNS name of the ALB. Use it as the base URL for the load test tool."
  value       = aws_lb.main.dns_name
}

output "alb_url" {
  description = "Convenience full URL of the ALB."
  value       = "http://${aws_lb.main.dns_name}"
}

output "rds_endpoint" {
  description = "RDS PostgreSQL endpoint (host:port)."
  value       = aws_db_instance.postgres.endpoint
}

output "redis_endpoint" {
  description = "ElastiCache Redis endpoint (host:port)."
  value       = "${aws_elasticache_cluster.redis.cache_nodes[0].address}:${aws_elasticache_cluster.redis.cache_nodes[0].port}"
}

output "lambda_function_name" {
  description = "Name of the deployed Lambda function."
  value       = aws_lambda_function.api.function_name
}

output "vpc_id" {
  description = "ID of the VPC created for this lab."
  value       = aws_vpc.main.id
}
