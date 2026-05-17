variable "project_name" {
  description = "GCP project name (will be slugified to form the project ID)"
  type        = string
  default     = "travel-planner"
}

variable "billing_account_id" {
  description = "GCP billing account ID"
  type        = string
}

variable "region" {
  description = "GCP region for all resources"
  type        = string
  default     = "europe-west1"
}

variable "admin_email" {
  description = "Email for monitoring alerts"
  type        = string
}

variable "backend_image" {
  description = "Full Artifact Registry image tag for the backend"
  type        = string
}

variable "frontend_image" {
  description = "Full Artifact Registry image tag for the frontend"
  type        = string
}
