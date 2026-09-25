# AWS Academy Learner Lab does not allow creating new IAM roles/policies, so
# we reuse the pre-provisioned LabRole (it already has permissions for
# Lambda, VPC networking, RDS, ElastiCache and CloudWatch Logs).
data "aws_iam_role" "lab_role" {
  name = "LabRole"
}

# Installs the Lambda's Python dependencies as manylinux wheels (matching the
# Lambda runtime) and copies the handler source next to them, so a single
# `terraform apply` produces a ready-to-deploy package with no manual steps.
resource "null_resource" "lambda_deps" {
  triggers = {
    requirements_hash = filesha256("${path.module}/../lambda/requirements.txt")
    app_hash          = filesha256("${path.module}/../lambda/app.py")
  }

  provisioner "local-exec" {
    working_dir = "${path.module}/../lambda"
    command     = "pip install -r requirements.txt -t package --platform manylinux2014_x86_64 --python-version 3.12 --implementation cp --only-binary=:all: --upgrade"
  }

  provisioner "local-exec" {
    working_dir = "${path.module}/../lambda"
    command     = "python copy_app.py"
  }
}

data "archive_file" "lambda_zip" {
  type        = "zip"
  source_dir  = "${path.module}/../lambda/package"
  output_path = "${path.module}/build/lambda.zip"

  depends_on = [null_resource.lambda_deps]
}

resource "aws_lambda_function" "api" {
  function_name = "${var.project_name}-api"
  description   = "ALB-triggered API backed by RDS PostgreSQL, cached in ElastiCache Redis"

  filename         = data.archive_file.lambda_zip.output_path
  source_code_hash = data.archive_file.lambda_zip.output_base64sha256

  handler       = "app.handler"
  runtime       = "python3.12"
  architectures = ["x86_64"]

  role        = data.aws_iam_role.lab_role.arn
  memory_size = var.lambda_memory_size
  timeout     = var.lambda_timeout

  reserved_concurrent_executions = var.lambda_reserved_concurrency == -1 ? null : var.lambda_reserved_concurrency

  vpc_config {
    subnet_ids         = aws_subnet.private[*].id
    security_group_ids = [aws_security_group.lambda.id]
  }

  environment {
    variables = {
      DB_HOST           = aws_db_instance.postgres.address
      DB_PORT           = tostring(aws_db_instance.postgres.port)
      DB_NAME           = var.db_name
      DB_USER           = var.db_username
      DB_PASSWORD       = random_password.db.result
      REDIS_HOST        = aws_elasticache_cluster.redis.cache_nodes[0].address
      REDIS_PORT        = tostring(aws_elasticache_cluster.redis.cache_nodes[0].port)
      CACHE_TTL_SECONDS = tostring(var.cache_ttl_seconds)
      SEED_ROWS         = "5000"
    }
  }

  tags = {
    Name = "${var.project_name}-api"
  }
}

resource "aws_cloudwatch_log_group" "lambda" {
  name              = "/aws/lambda/${aws_lambda_function.api.function_name}"
  retention_in_days = 3
}
