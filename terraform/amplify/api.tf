data "archive_file" "lambda_package" {
  type        = "zip"
  source_dir  = "${path.module}/../../src"
  output_path = "${path.module}/.terraform/mobilefrost-lambda.zip"
}

resource "aws_iam_role" "api_lambda" {
  name = "${local.prefix}-api-lambda"
  assume_role_policy = jsonencode({
    Version = "2012-10-17"
    Statement = [{
      Effect    = "Allow"
      Principal = { Service = "lambda.amazonaws.com" }
      Action    = "sts:AssumeRole"
    }]
  })
  tags = local.common_tags
}

resource "aws_iam_role_policy_attachment" "api_lambda_logs" {
  role       = aws_iam_role.api_lambda.name
  policy_arn = "arn:${data.aws_partition.current.partition}:iam::aws:policy/service-role/AWSLambdaBasicExecutionRole"
}

resource "aws_iam_role_policy" "api_lambda_data" {
  name = "${local.prefix}-api-data-access"
  role = aws_iam_role.api_lambda.id
  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [
      {
        Effect   = "Allow"
        Action   = ["timestream:Select"]
        Resource = aws_timestreamwrite_table.temperatures.arn
      },
      {
        Effect   = "Allow"
        Action   = ["timestream:DescribeEndpoints"]
        Resource = "*"
      },
      {
        Effect = "Allow"
        Action = [
          "dynamodb:GetItem",
          "dynamodb:PutItem",
          "dynamodb:UpdateItem",
          "dynamodb:DeleteItem",
          "dynamodb:TransactWriteItems",
        ]
        Resource = aws_dynamodb_table.operations.arn
      },
      {
        Effect   = "Allow"
        Action   = ["iot:Publish"]
        Resource = "arn:${data.aws_partition.current.partition}:iot:${var.aws_region}:${data.aws_caller_identity.current.account_id}:topic/mobilefrost/commands/${var.device_id}/actuators/*"
      },
    ]
  })
}

resource "aws_lambda_function" "api" {
  function_name    = "${local.prefix}-api"
  role             = aws_iam_role.api_lambda.arn
  runtime          = "python3.12"
  handler          = "mobilefrost.cloud_api.lambda_handler"
  filename         = data.archive_file.lambda_package.output_path
  source_code_hash = data.archive_file.lambda_package.output_base64sha256
  timeout          = 15
  memory_size      = 256

  environment {
    variables = {
      TIMESTREAM_DATABASE   = aws_timestreamwrite_database.temperatures.database_name
      TIMESTREAM_TABLE      = aws_timestreamwrite_table.temperatures.table_name
      OPERATIONS_TABLE      = aws_dynamodb_table.operations.name
      DEVICE_ID             = var.device_id
      AWS_IOT_DATA_ENDPOINT = data.aws_iot_endpoint.data.endpoint_address
    }
  }

  depends_on = [aws_iam_role_policy_attachment.api_lambda_logs]
  tags       = local.common_tags
}

resource "aws_iam_role" "ack_lambda" {
  name = "${local.prefix}-ack-lambda"
  assume_role_policy = jsonencode({
    Version = "2012-10-17"
    Statement = [{
      Effect    = "Allow"
      Principal = { Service = "lambda.amazonaws.com" }
      Action    = "sts:AssumeRole"
    }]
  })
  tags = local.common_tags
}

resource "aws_iam_role_policy_attachment" "ack_lambda_logs" {
  role       = aws_iam_role.ack_lambda.name
  policy_arn = "arn:${data.aws_partition.current.partition}:iam::aws:policy/service-role/AWSLambdaBasicExecutionRole"
}

resource "aws_iam_role_policy" "ack_lambda_data" {
  name = "${local.prefix}-ack-update-command"
  role = aws_iam_role.ack_lambda.id
  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [{
      Effect   = "Allow"
      Action   = ["dynamodb:UpdateItem"]
      Resource = aws_dynamodb_table.operations.arn
    }]
  })
}

resource "aws_lambda_function" "ack" {
  function_name    = "${local.prefix}-ack"
  role             = aws_iam_role.ack_lambda.arn
  runtime          = "python3.12"
  handler          = "mobilefrost.cloud_ack.lambda_handler"
  filename         = data.archive_file.lambda_package.output_path
  source_code_hash = data.archive_file.lambda_package.output_base64sha256
  timeout          = 10
  memory_size      = 128

  environment {
    variables = {
      OPERATIONS_TABLE = aws_dynamodb_table.operations.name
      DEVICE_ID        = var.device_id
    }
  }

  depends_on = [aws_iam_role_policy_attachment.ack_lambda_logs]
  tags       = local.common_tags
}

resource "aws_apigatewayv2_api" "dashboard" {
  name          = "${local.prefix}-api"
  protocol_type = "HTTP"

  cors_configuration {
    allow_origins = ["https://${var.amplify_branch_name}.${aws_amplify_app.dashboard.default_domain}"]
    allow_methods = ["GET", "POST", "OPTIONS"]
    allow_headers = ["authorization", "content-type"]
    max_age       = 3600
  }
  tags = local.common_tags
}

resource "aws_apigatewayv2_authorizer" "cognito" {
  api_id           = aws_apigatewayv2_api.dashboard.id
  name             = "${local.prefix}-cognito-jwt"
  authorizer_type  = "JWT"
  identity_sources = ["$request.header.Authorization"]

  jwt_configuration {
    audience = [aws_cognito_user_pool_client.dashboard.id]
    issuer   = "https://cognito-idp.${var.aws_region}.amazonaws.com/${aws_cognito_user_pool.dashboard.id}"
  }
}

resource "aws_apigatewayv2_integration" "api_lambda" {
  api_id                 = aws_apigatewayv2_api.dashboard.id
  integration_type       = "AWS_PROXY"
  integration_method     = "POST"
  integration_uri        = aws_lambda_function.api.invoke_arn
  payload_format_version = "2.0"
}

resource "aws_apigatewayv2_route" "authenticated" {
  for_each = local.api_routes

  api_id             = aws_apigatewayv2_api.dashboard.id
  route_key          = each.value
  target             = "integrations/${aws_apigatewayv2_integration.api_lambda.id}"
  authorization_type = "JWT"
  authorizer_id      = aws_apigatewayv2_authorizer.cognito.id
}

resource "aws_apigatewayv2_stage" "default" {
  api_id      = aws_apigatewayv2_api.dashboard.id
  name        = "$default"
  auto_deploy = true
  tags        = local.common_tags
}

resource "aws_lambda_permission" "api_gateway" {
  statement_id  = "AllowDashboardHttpApi"
  action        = "lambda:InvokeFunction"
  function_name = aws_lambda_function.api.function_name
  principal     = "apigateway.amazonaws.com"
  source_arn    = "${aws_apigatewayv2_api.dashboard.execution_arn}/*/*"
}