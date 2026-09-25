variable "aws_profile" {
  description = "AWS CLI profile to use (AWS Academy Learner Lab exports credentials under this profile)."
  type        = string
  default     = "academy"
}

variable "aws_region" {
  description = "AWS region to deploy into. AWS Academy Learner Lab is normally locked to us-east-1."
  type        = string
  default     = "us-east-1"
}

variable "project_name" {
  description = "Prefix used to name every resource created by this lab."
  type        = string
  default     = "lab4-cache-demo"
}

variable "vpc_cidr" {
  description = "CIDR block for the VPC created for this lab."
  type        = string
  default     = "10.0.0.0/16"
}

variable "public_subnet_cidrs" {
  description = "CIDR blocks for the two public subnets (used by the ALB)."
  type        = list(string)
  default     = ["10.0.1.0/24", "10.0.2.0/24"]
}

variable "private_subnet_cidrs" {
  description = "CIDR blocks for the two private subnets (used by Lambda, RDS and ElastiCache)."
  type        = list(string)
  default     = ["10.0.11.0/24", "10.0.12.0/24"]
}

variable "db_name" {
  description = "Name of the PostgreSQL database created inside RDS."
  type        = string
  default     = "labdb"
}

variable "db_username" {
  description = "Master username for the RDS PostgreSQL instance."
  type        = string
  default     = "labadmin"
}

variable "db_instance_class" {
  description = "Instance class for the RDS PostgreSQL instance."
  type        = string
  default     = "db.t3.micro"
}

variable "db_allocated_storage" {
  description = "Allocated storage (GB) for the RDS instance."
  type        = number
  default     = 20
}

variable "redis_node_type" {
  description = "Node type for the ElastiCache Redis cluster."
  type        = string
  default     = "cache.t3.micro"
}

variable "lambda_memory_size" {
  description = "Memory (MB) allocated to the Lambda function. Higher memory also grants more vCPU."
  type        = number
  default     = 512
}

variable "lambda_timeout" {
  description = "Timeout (seconds) for the Lambda function."
  type        = number
  default     = 30
}

variable "lambda_reserved_concurrency" {
  description = "Reserved concurrent executions for the Lambda function. Use -1 to leave it unreserved (default), or a positive number to cap concurrency and deliberately stress/throttle the function under load."
  type        = number
  default     = -1
}

variable "cache_ttl_seconds" {
  description = "TTL (seconds) applied to cached items in Redis."
  type        = number
  default     = 120
}
