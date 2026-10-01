resource "aws_amplify_app" "dashboard" {
  name         = "${local.prefix}-dashboard"
  repository   = var.amplify_repository_url
  access_token = var.amplify_repository_access_token
  build_spec   = file("${path.module}/../../amplify.yml")
  platform     = "WEB"

  custom_rule {
    source = "</^[^.]+$|\\.(?!(css|gif|ico|jpg|js|png|txt|svg|woff|ttf|map|json)$)([^.]+$)/>"
    status = "200"
    target = "/index.html"
  }

  tags = local.common_tags
}

resource "aws_amplify_branch" "dashboard" {
  app_id      = aws_amplify_app.dashboard.id
  branch_name = var.amplify_branch_name
  framework   = "Vite"
  stage       = "PRODUCTION"

  environment_variables = {
    VITE_API_URL                     = aws_apigatewayv2_api.dashboard.api_endpoint
    VITE_AWS_REGION                  = var.aws_region
    VITE_COGNITO_USER_POOL_ID        = aws_cognito_user_pool.dashboard.id
    VITE_COGNITO_USER_POOL_CLIENT_ID = aws_cognito_user_pool_client.dashboard.id
  }

  enable_auto_build = true
  tags              = local.common_tags
}