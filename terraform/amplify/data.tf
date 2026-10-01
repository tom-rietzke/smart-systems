resource "aws_cloudwatch_log_group" "iot_rule_errors" {
  name              = "/aws/iot/${local.prefix}/rule-errors"
  retention_in_days = 14
  tags              = local.common_tags
}

resource "aws_iam_role" "iot_timestream" {
  name = "${local.prefix}-iot-timestream"
  assume_role_policy = jsonencode({
    Version = "2012-10-17"
    Statement = [{
      Effect    = "Allow"
      Principal = { Service = "iot.amazonaws.com" }
      Action    = "sts:AssumeRole"
    }]
  })
  tags = local.common_tags
}

resource "aws_iam_role_policy" "iot_timestream_write" {
  name = "${local.prefix}-timestream-write"
  role = aws_iam_role.iot_timestream.id
  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [
      {
        Effect   = "Allow"
        Action   = ["timestream:WriteRecords"]
        Resource = aws_timestreamwrite_table.temperatures.arn
      },
      {
        Effect   = "Allow"
        Action   = ["timestream:DescribeEndpoints"]
        Resource = "*"
      },
    ]
  })
}

resource "aws_iam_role" "iot_logs" {
  name = "${local.prefix}-iot-logs"
  assume_role_policy = jsonencode({
    Version = "2012-10-17"
    Statement = [{
      Effect    = "Allow"
      Principal = { Service = "iot.amazonaws.com" }
      Action    = "sts:AssumeRole"
    }]
  })
  tags = local.common_tags
}

resource "aws_iam_role_policy" "iot_logs_write" {
  name = "${local.prefix}-iot-log-write"
  role = aws_iam_role.iot_logs.id
  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [{
      Effect   = "Allow"
      Action   = ["logs:CreateLogStream", "logs:PutLogEvents"]
      Resource = "${aws_cloudwatch_log_group.iot_rule_errors.arn}:*"
    }]
  })
}

resource "aws_iot_topic_rule" "temperatures" {
  name        = replace("${local.prefix}_temperatures", "-", "_")
  description = "Write MobileFrost cloud temperature readings to Timestream."
  enabled     = true
  sql         = "SELECT sensor_id, value AS temperature_c FROM 'mobilefrost/cloud/temperatures/+'"
  sql_version = "2016-03-23"

  timestream {
    database_name = aws_timestreamwrite_database.temperatures.database_name
    table_name    = aws_timestreamwrite_table.temperatures.table_name
    role_arn      = aws_iam_role.iot_timestream.arn

    dimension {
      name  = "sensor_id"
      value = sensor_id
    }

    timestamp {
      unit  = "MILLISECONDS"
      value = epoch_ms
    }
  }

  error_action {
    cloudwatch_logs {
      log_group_name = aws_cloudwatch_log_group.iot_rule_errors.name
      role_arn       = aws_iam_role.iot_logs.arn
    }
  }
  tags = local.common_tags
}

resource "aws_iot_topic_rule" "command_acknowledgements" {
  name        = replace("${local.prefix}_command_acks", "-", "_")
  description = "Store acknowledgements returned by the MobileFrost Pi bridge."
  enabled     = true
  sql         = "SELECT * FROM 'mobilefrost/device/status/${var.device_id}/commands'"
  sql_version = "2016-03-23"

  lambda {
    function_arn = aws_lambda_function.ack.arn
  }

  error_action {
    cloudwatch_logs {
      log_group_name = aws_cloudwatch_log_group.iot_rule_errors.name
      role_arn       = aws_iam_role.iot_logs.arn
    }
  }
  tags = local.common_tags
}

resource "aws_lambda_permission" "iot_ack_rule" {
  statement_id  = "AllowIotAcknowledgementRule"
  action        = "lambda:InvokeFunction"
  function_name = aws_lambda_function.ack.function_name
  principal     = "iot.amazonaws.com"
  source_arn    = aws_iot_topic_rule.command_acknowledgements.arn
}