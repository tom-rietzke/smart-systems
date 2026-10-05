locals {
  prefix = "${var.project_name}-${var.environment}"
  api_routes = toset([
    "GET /api/temperatures",
    "GET /api/drive",
    "POST /api/drive/start",
    "POST /api/drive/stop",
    "POST /api/actuators/fan",
    "POST /api/actuators/flap",
    "GET /api/commands/{request_id}",
  ])
  common_tags = merge(var.tags, {
    Project     = var.project_name
    Environment = var.environment
  })
}

resource "aws_cognito_user_pool" "dashboard" {
  name                     = "${local.prefix}-users"
  username_attributes      = ["email"]
  auto_verified_attributes = ["email"]

  admin_create_user_config {
    allow_admin_create_user_only = true
  }

  password_policy {
    minimum_length                   = 12
    require_lowercase                = true
    require_numbers                  = true
    require_symbols                  = true
    require_uppercase                = true
    temporary_password_validity_days = 7
  }

  schema {
    attribute_data_type = "String"
    name                = "email"
    required            = true
    mutable             = true
  }

  tags = local.common_tags
}

resource "aws_cognito_user_pool_client" "dashboard" {
  name                          = "${local.prefix}-web"
  user_pool_id                  = aws_cognito_user_pool.dashboard.id
  generate_secret               = false
  explicit_auth_flows           = ["ALLOW_USER_SRP_AUTH", "ALLOW_REFRESH_TOKEN_AUTH"]
  prevent_user_existence_errors = "ENABLED"
  enable_token_revocation       = true
  access_token_validity         = 60
  id_token_validity             = 60
  refresh_token_validity        = 30
  supported_identity_providers  = ["COGNITO"]

  token_validity_units {
    access_token  = "minutes"
    id_token      = "minutes"
    refresh_token = "days"
  }
}

resource "aws_dynamodb_table" "operations" {
  name         = "${local.prefix}-operations"
  billing_mode = "PAY_PER_REQUEST"
  hash_key     = "pk"
  range_key    = "sk"

  attribute {
    name = "pk"
    type = "S"
  }

  attribute {
    name = "sk"
    type = "S"
  }

  point_in_time_recovery {
    enabled = false
  }

  server_side_encryption {
    enabled = true
  }

  tags = local.common_tags
}

resource "aws_dynamodb_table" "readings" {
  name         = "${local.prefix}-readings"
  billing_mode = "PAY_PER_REQUEST"
  hash_key     = "sensor_id"
  range_key    = "timestamp"

  attribute {
    name = "sensor_id"
    type = "S"
  }

  attribute {
    name = "timestamp"
    type = "S"
  }

  point_in_time_recovery {
    enabled = false
  }

  server_side_encryption {
    enabled = true
  }

  tags = local.common_tags
}

data "aws_iot_endpoint" "data" {
  endpoint_type = "iot:Data-ATS"
}