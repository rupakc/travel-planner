variable "project_id"    { type = string }
variable "region"        { type = string }
variable "image"         { type = string }
variable "backup_bucket" { type = string }
variable "frontend_url" {
  type    = string
  default = ""
}

locals {
  cors_origins = compact([
    var.frontend_url,
    "http://localhost:5174",
    "http://localhost:5173",
  ])
}

resource "google_cloud_run_v2_service" "backend" {
  project  = var.project_id
  name     = "travel-planner-backend"
  location = var.region
  ingress  = "INGRESS_TRAFFIC_ALL"

  template {
    execution_environment = "EXECUTION_ENVIRONMENT_GEN2"

    scaling {
      min_instance_count = 0
      max_instance_count = 5
    }

    containers {
      image = var.image

      ports {
        container_port = 8001
      }

      resources {
        limits = {
          memory = "1Gi"
          cpu    = "1"
        }
      }

      env {
        name  = "BACKUP_BUCKET"
        value = var.backup_bucket
      }
      env {
        name  = "DATA_DIR"
        value = "/tmp/data"
      }
      env {
        name  = "AGENTS_DIR"
        value = "/app/.agents"
      }
      env {
        name  = "LOG_FORMAT"
        value = "json"
      }
      env {
        name  = "CORS_ORIGINS"
        value = jsonencode(local.cors_origins)
      }

      env {
        name = "ANTHROPIC_API_KEY"
        value_source {
          secret_key_ref {
            secret  = "anthropic-api-key"
            version = "latest"
          }
        }
      }
      env {
        name = "JWT_SECRET_KEY"
        value_source {
          secret_key_ref {
            secret  = "jwt-secret-key"
            version = "latest"
          }
        }
      }
      env {
        name = "ADMIN_PASSWORD"
        value_source {
          secret_key_ref {
            secret  = "admin-password"
            version = "latest"
          }
        }
      }
      env {
        name = "SERPAPI_KEY"
        value_source {
          secret_key_ref {
            secret  = "serpapi-key"
            version = "latest"
          }
        }
      }
      env {
        name = "SERPER_KEY"
        value_source {
          secret_key_ref {
            secret  = "serper-key"
            version = "latest"
          }
        }
      }

      liveness_probe {
        http_get {
          path = "/health"
        }
        period_seconds    = 30
        failure_threshold = 3
      }

      startup_probe {
        http_get {
          path = "/health"
        }
        initial_delay_seconds = 10
        period_seconds        = 5
        failure_threshold     = 10
      }
    }
  }
}

resource "google_cloud_run_v2_service_iam_member" "backend_public" {
  project  = var.project_id
  location = var.region
  name     = google_cloud_run_v2_service.backend.name
  role     = "roles/run.invoker"
  member   = "allUsers"
}

output "url" { value = google_cloud_run_v2_service.backend.uri }
