variable "aws_region" {
  description = "AWS-Region für die MobileFrost-Cloud-Ressourcen."
  type        = string
  default     = "eu-central-1"
}

variable "project_name" {
  description = "Kurzer Präfix für AWS-Ressourcennamen."
  type        = string
  default     = "mobilefrost"
}

variable "environment" {
  description = "Namensraum für die Bereitstellung, zum Beispiel demo oder prod."
  type        = string
  default     = "demo"
}

variable "device_id" {
  description = "IoT-Gerätename und Sensor-/Befehlsnamespace."
  type        = string
  default     = "mobilefrost"
}

variable "device_certificate_arn" {
  description = "ARN des separat erzeugten und aktivierten AWS-IoT-Gerätezertifikats."
  type        = string
}

variable "amplify_repository_url" {
  description = "Git-URL des MobileFrost-Repositories, das Amplify bauen soll."
  type        = string
}

variable "amplify_repository_access_token" {
  description = "Repository-Token für den Amplify-Webhook; nie committen und Terraform-State schützen."
  type        = string
  sensitive   = true
}

variable "amplify_branch_name" {
  description = "Git-Branch für die Amplify-Produktion."
  type        = string
  default     = "main"
}

variable "timestream_memory_retention_hours" {
  description = "Timestream-Memory-Aufbewahrung in Stunden."
  type        = number
  default     = 24
}

variable "timestream_magnetic_retention_days" {
  description = "Timestream-Magnetic-Aufbewahrung in Tagen."
  type        = number
  default     = 30
}

variable "tags" {
  description = "Zusätzliche AWS-Ressourcen-Tags."
  type        = map(string)
  default     = {}
}