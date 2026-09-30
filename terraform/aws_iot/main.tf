terraform {
  required_version = ">= 1.5.0"

  required_providers {
    aws = {
      source  = "hashicorp/aws"
      version = ">= 5.0, < 7.0"
    }
  }
}

provider "aws" {
  region = var.aws_region

  default_tags {
    tags = {
      Project   = var.project_name
      ManagedBy = "Terraform"
    }
  }
}

variable "aws_region" {
  description = "AWS region for IoT Core and Timestream."
  type        = string
  default     = "eu-central-1"
}

variable "project_name" {
  description = "Prefix used for AWS resource names."
  type        = string
  default     = "mobilefrost"
}

variable "device_certificate_arn" {
  description = "Optional ARN of the separately created device certificate."
  type        = string
  default     = ""
}

data "aws_caller_identity" "current" {}

data "aws_iot_endpoint" "data" {
  endpoint_type = "iot:Data-ATS"
}

locals {
  database_name = "${var.project_name}_temperatures"
  table_name    = "temperature_readings"
  cloud_topic   = "mobilefrost/cloud/temperatures"
  rule_name     = "${replace(var.project_name, "-", "_")}_temperatures_to_timestream"
}

resource "aws_iot_thing" "mobilefrost" {
  name = var.project_name
}

resource "aws_iot_policy" "temperature_publish" {
  name = "${var.project_name}_temperature_publish"

  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [
      {
        Effect   = "Allow"
        Action   = "iot:Connect"
        Resource = "arn:aws:iot:${var.aws_region}:${data.aws_caller_identity.current.account_id}:client/${aws_iot_thing.mobilefrost.name}"
      },
      {
        Effect   = "Allow"
        Action   = "iot:Publish"
        Resource = "arn:aws:iot:${var.aws_region}:${data.aws_caller_identity.current.account_id}:topic/${local.cloud_topic}/*"
      }
    ]
  })
}

resource "aws_iot_thing_principal_attachment" "device" {
  count = var.device_certificate_arn == "" ? 0 : 1

  principal = var.device_certificate_arn
  thing     = aws_iot_thing.mobilefrost.name
}

resource "aws_iot_policy_attachment" "device" {
  count = var.device_certificate_arn == "" ? 0 : 1

  policy = aws_iot_policy.temperature_publish.name
  target = var.device_certificate_arn
}

resource "aws_timestreamwrite_database" "temperatures" {
  database_name = local.database_name
}

resource "aws_timestreamwrite_table" "temperatures" {
  database_name = aws_timestreamwrite_database.temperatures.database_name
  table_name    = local.table_name

  retention_properties {
    memory_store_retention_period_in_hours  = 24
    magnetic_store_retention_period_in_days = 30
  }
}

resource "aws_iam_role" "timestream_writer" {
  name = "${var.project_name}_iot_timestream_writer"

  assume_role_policy = jsonencode({
    Version = "2012-10-17"
    Statement = [{
      Effect = "Allow"
      Principal = {
        Service = "iot.amazonaws.com"
      }
      Action = "sts:AssumeRole"
      Condition = {
        StringEquals = {
          "aws:SourceAccount" = data.aws_caller_identity.current.account_id
        }
        ArnLike = {
          "aws:SourceArn" = "arn:aws:iot:${var.aws_region}:${data.aws_caller_identity.current.account_id}:rule/${local.rule_name}"
        }
      }
    }]
  })
}

resource "aws_iam_role_policy" "timestream_writer" {
  name = "${var.project_name}_timestream_write"
  role = aws_iam_role.timestream_writer.id

  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [
      {
        Effect   = "Allow"
        Action   = "timestream:WriteRecords"
        Resource = aws_timestreamwrite_table.temperatures.arn
      },
      {
        Effect   = "Allow"
        Action   = "timestream:DescribeEndpoints"
        Resource = "*"
      }
    ]
  })
}

resource "aws_cloudwatch_log_group" "rule_errors" {
  name              = "/aws/iot/${var.project_name}/rule-errors"
  retention_in_days = 14
}

resource "aws_iam_role" "rule_error_logger" {
  name = "${var.project_name}_iot_rule_error_logger"

  assume_role_policy = jsonencode({
    Version = "2012-10-17"
    Statement = [{
      Effect = "Allow"
      Principal = {
        Service = "iot.amazonaws.com"
      }
      Action = "sts:AssumeRole"
      Condition = {
        StringEquals = {
          "aws:SourceAccount" = data.aws_caller_identity.current.account_id
        }
        ArnLike = {
          "aws:SourceArn" = "arn:aws:iot:${var.aws_region}:${data.aws_caller_identity.current.account_id}:rule/${local.rule_name}"
        }
      }
    }]
  })
}

resource "aws_iam_role_policy" "rule_error_logger" {
  name = "${var.project_name}_iot_rule_error_logs"
  role = aws_iam_role.rule_error_logger.id

  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [{
      Effect = "Allow"
      Action = [
        "logs:CreateLogStream",
        "logs:PutLogEvents"
      ]
      Resource = "${aws_cloudwatch_log_group.rule_errors.arn}:*"
    }]
  })
}

resource "aws_iot_topic_rule" "temperatures_to_timestream" {
  name        = local.rule_name
  description = "Stores MobileFrost cloud temperature readings in Timestream."
  enabled     = true
  sql         = "SELECT value AS temperature_c FROM '${local.cloud_topic}/+'"
  sql_version = "2016-03-23"

  depends_on = [
    aws_iam_role_policy.timestream_writer,
    aws_iam_role_policy.rule_error_logger
  ]

  timestream {
    database_name = aws_timestreamwrite_database.temperatures.database_name
    table_name    = aws_timestreamwrite_table.temperatures.table_name
    role_arn      = aws_iam_role.timestream_writer.arn

    dimension {
      name  = "sensor_id"
      value = "$${sensor_id}"
    }

    timestamp {
      value = "$${epoch_ms}"
      unit  = "MILLISECONDS"
    }
  }

  error_action {
    cloudwatch_logs {
      log_group_name = aws_cloudwatch_log_group.rule_errors.name
      role_arn       = aws_iam_role.rule_error_logger.arn
    }
  }
}

output "iot_endpoint" {
  description = "AWS IoT Core ATS data endpoint."
  value       = data.aws_iot_endpoint.data.endpoint_address
}

output "thing_name" {
  description = "AWS IoT Thing name used as the MQTT client ID."
  value       = aws_iot_thing.mobilefrost.name
}

output "cloud_topic" {
  description = "Topic prefix accepted by the device policy."
  value       = "${local.cloud_topic}/<sensor_id>"
}

output "timestream_database" {
  description = "Timestream database containing the temperature table."
  value       = aws_timestreamwrite_database.temperatures.database_name
}

output "timestream_table" {
  description = "Timestream table containing the temperature readings."
  value       = aws_timestreamwrite_table.temperatures.table_name
}