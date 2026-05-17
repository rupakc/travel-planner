variable "project_id" { type = string }
variable "region"     { type = string }

resource "google_artifact_registry_repository" "images" {
  project       = var.project_id
  location      = var.region
  repository_id = "travel-planner"
  format        = "DOCKER"

  cleanup_policies {
    id     = "keep-last-5"
    action = "KEEP"
    most_recent_versions {
      keep_count = 5
    }
  }
}

output "registry_url" {
  value = "${var.region}-docker.pkg.dev/${var.project_id}/travel-planner"
}
