terraform {
  required_version = ">= 1.6"

  required_providers {
    google = {
      source  = "hashicorp/google"
      version = "~> 5.0"
    }
    google-beta = {
      source  = "hashicorp/google-beta"
      version = "~> 5.0"
    }
  }

  backend "gcs" {
    # bucket and prefix set via -backend-config in CI
  }
}

provider "google" {
  project = var.project_id
  region  = var.region
}

provider "google-beta" {
  project = var.project_id
  region  = var.region
}

# ─── Modules ──────────────────────────────────────────────────────────────────

module "iam" {
  source     = "./modules/iam"
  project_id = var.project_id
  region     = var.region
}

module "artifact_registry" {
  source     = "./modules/artifact_registry"
  project_id = var.project_id
  region     = var.region
}

module "storage" {
  source     = "./modules/storage"
  project_id = var.project_id
  region     = var.region
}

module "backend_service" {
  source             = "./modules/backend_service"
  project_id         = var.project_id
  region             = var.region
  image              = var.backend_image
  backup_bucket      = module.storage.bucket_name
  cloud_run_sa_email = module.iam.cloud_run_sa_email
  depends_on         = [module.iam, module.storage]
}

module "frontend_service" {
  source             = "./modules/frontend_service"
  project_id         = var.project_id
  region             = var.region
  image              = var.frontend_image
  backend_url        = module.backend_service.url
  cloud_run_sa_email = module.iam.cloud_run_sa_email
  depends_on         = [module.backend_service]
}

module "monitoring" {
  source       = "./modules/monitoring"
  project_id   = var.project_id
  admin_email  = var.admin_email
  backend_url  = module.backend_service.url
  frontend_url = module.frontend_service.url
  depends_on   = [module.backend_service, module.frontend_service]
}
