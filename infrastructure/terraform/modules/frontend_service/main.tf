variable "project_id"         { type = string }
variable "region"             { type = string }
variable "image"              { type = string }
variable "backend_url"        { type = string }
variable "cloud_run_sa_email" { type = string }

resource "google_cloud_run_v2_service" "frontend" {
  project  = var.project_id
  name     = "travel-planner-frontend"
  location = var.region
  ingress  = "INGRESS_TRAFFIC_ALL"

  template {
    service_account = var.cloud_run_sa_email

    execution_environment = "EXECUTION_ENVIRONMENT_GEN2"

    scaling {
      min_instance_count = 0
      max_instance_count = 3
    }

    containers {
      image = var.image

      resources {
        limits = {
          memory = "256Mi"
          cpu    = "1"
        }
      }

      env {
        name  = "BACKEND_URL"
        value = var.backend_url
      }
    }
  }
}

resource "google_cloud_run_v2_service_iam_member" "frontend_public" {
  project  = var.project_id
  location = var.region
  name     = google_cloud_run_v2_service.frontend.name
  role     = "roles/run.invoker"
  member   = "allUsers"
}

output "url" { value = google_cloud_run_v2_service.frontend.uri }
