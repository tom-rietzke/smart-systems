resource "aws_cloudwatch_log_group" "iot_rule_errors" {
  name              = "/aws/iot/${local.prefix}/rule-errors"
  retention_in_days = 14
  tags              = local.common_tags
}

resource "aws_iam_role" "iot_readings" {
  name = "${local.prefix}-iot-readings"
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

resource "aws_iam_role_policy" "iot_readings_write" {
  name = "${local.prefix}-readings-write"
  role = aws_iam_role.iot_readings.id
  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [{
      Effect   = "Allow"
      Action   = ["dynamodb:PutItem"]
      Resource = aws_dynamodb_table.readings.arn
    }]
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
  description = "Store MobileFrost cloud temperature readings in DynamoDB."
  enabled     = true
  sql         = "SELECT * FROM 'mobilefrost/cloud/temperatures/+'"
  sql_version = "2016-03-23"

  dynamodbv2 {
    role_arn = aws_iam_role.iot_readings.arn

    put_item {
      table_name = aws_dynamodb_table.readings.name
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