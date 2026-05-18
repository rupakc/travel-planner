variable "project_id" { type = string }

locals {
  secret_names = ["anthropic-api-key", "jwt-secret-key", "admin-password", "serpapi-key"]
}

resource "google_secret_manager_secret" "secrets" {
  for_each  = toset(local.secret_names)
  project   = var.project_id
  secret_id = each.key

  replication {
    auto {}
  }
}

# Secret values are populated by infrastructure/scripts/populate-secrets.sh
# Terraform only creates the secret shells.

output "secret_ids" {
  value = { for k, v in google_secret_manager_secret.secrets : k => v.secret_id }
}
