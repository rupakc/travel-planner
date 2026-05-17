variable "project_id" { type = string }
variable "region"     { type = string }

resource "google_storage_bucket" "sqlite_backup" {
  project                     = var.project_id
  name                        = "${var.project_id}-sqlite-backup"
  location                    = var.region
  uniform_bucket_level_access = true
  force_destroy               = false

  versioning {
    enabled = true
  }

  lifecycle_rule {
    condition { num_newer_versions = 10 }
    action    { type = "Delete" }
  }
}

output "bucket_name" { value = google_storage_bucket.sqlite_backup.name }
