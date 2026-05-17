output "project_id" {
  value = var.project_id
}

output "backend_url" {
  value = module.backend_service.url
}

output "frontend_url" {
  value = module.frontend_service.url
}

output "backup_bucket" {
  value = module.storage.bucket_name
}
