variable "project_name"       { type = string }
variable "billing_account_id" { type = string }
variable "region"             { type = string }

locals {
  project_id = "${lower(replace(var.project_name, " ", "-"))}-prod"
}

resource "google_project" "main" {
  name            = var.project_name
  project_id      = local.project_id
  billing_account = var.billing_account_id
}

resource "google_project_service" "apis" {
  for_each = toset([
    "run.googleapis.com",
    "artifactregistry.googleapis.com",
    "secretmanager.googleapis.com",
    "storage.googleapis.com",
    "iam.googleapis.com",
    "cloudresourcemanager.googleapis.com",
    "compute.googleapis.com",
    "monitoring.googleapis.com",
    "logging.googleapis.com",
  ])
  project            = google_project.main.project_id
  service            = each.key
  disable_on_destroy = false
}

output "project_id" { value = google_project.main.project_id }
