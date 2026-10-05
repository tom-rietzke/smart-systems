output "amplify_url" {
  description = "Öffentliche Amplify-URL; Anmeldung ist für alle Dashboard-Funktionen erforderlich."
  value       = "https://${var.amplify_branch_name}.${aws_amplify_app.dashboard.default_domain}"
}

output "api_url" {
  description = "HTTP API URL für das Amplify-Frontend."
  value       = aws_apigatewayv2_api.dashboard.api_endpoint
}

output "cognito_user_pool_id" {
  description = "Cognito User Pool ID für die Frontend-Konfiguration."
  value       = aws_cognito_user_pool.dashboard.id
}

output "cognito_user_pool_client_id" {
  description = "Cognito Public Client ID ohne Client-Secret."
  value       = aws_cognito_user_pool_client.dashboard.id
}

output "iot_endpoint" {
  description = "AWS-IoT-MQTT-Endpunkt für den Pi."
  value       = data.aws_iot_endpoint.data.endpoint_address
}

output "device_id" {
  description = "Geräte-ID für die Pi-Bridge-Konfiguration."
  value       = var.device_id
}

output "readings_table" {
  description = "DynamoDB-Tabelle mit Cloud-Temperaturmessungen."
  value       = aws_dynamodb_table.readings.name
}