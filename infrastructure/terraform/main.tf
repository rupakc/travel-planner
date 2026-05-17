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
    time = {
      source  = "hashicorp/time"
      version = "~> 0.9"
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

# ─── APIs ─────────────────────────────────────────────────────────────────────

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
  project            = var.project_id
  service            = each.key
  disable_on_destroy = false
}

# ─── Modules ──────────────────────────────────────────────────────────────────

# Resolve project number so we can reference the default Compute SA
data "google_project" "current" {
  project_id = var.project_id
}

# Discover the email of the SA running Terraform (the GitHub Actions deployer SA)
data "google_client_openid_userinfo" "deployer" {}

locals {
  default_compute_sa = "${data.google_project.current.number}-compute@developer.gserviceaccount.com"
}

# Grant the deployer SA permission to assign SAs to Cloud Run services
resource "google_project_iam_member" "deployer_sa_user" {
  project    = var.project_id
  role       = "roles/iam.serviceAccountUser"
  member     = "serviceAccount:${data.google_client_openid_userinfo.deployer.email}"
  depends_on = [google_project_service.apis]
}

# Wait for IAM propagation before deploying Cloud Run services
resource "time_sleep" "iam_propagation" {
  create_duration = "30s"
  depends_on      = [google_project_iam_member.deployer_sa_user]
}

# Grant the default Compute SA the permissions Cloud Run needs at runtime
resource "google_project_iam_member" "compute_sa_secret_accessor" {
  project    = var.project_id
  role       = "roles/secretmanager.secretAccessor"
  member     = "serviceAccount:${local.default_compute_sa}"
  depends_on = [google_project_service.apis]
}

resource "google_project_iam_member" "compute_sa_storage_admin" {
  project    = var.project_id
  role       = "roles/storage.objectAdmin"
  member     = "serviceAccount:${local.default_compute_sa}"
  depends_on = [google_project_service.apis]
}

module "storage" {
  source     = "./modules/storage"
  project_id = var.project_id
  region     = var.region
  depends_on = [google_project_service.apis]
}

module "backend_service" {
  source        = "./modules/backend_service"
  project_id    = var.project_id
  region        = var.region
  image         = var.backend_image
  backup_bucket = module.storage.bucket_name
  depends_on    = [module.storage, google_project_iam_member.compute_sa_secret_accessor, time_sleep.iam_propagation]
}

module "frontend_service" {
  source      = "./modules/frontend_service"
  project_id  = var.project_id
  region      = var.region
  image       = var.frontend_image
  backend_url = module.backend_service.url
  depends_on  = [module.backend_service, time_sleep.iam_propagation]
}

module "monitoring" {
  source       = "./modules/monitoring"
  project_id   = var.project_id
  admin_email  = var.admin_email
  backend_url  = module.backend_service.url
  frontend_url = module.frontend_service.url
  depends_on   = [module.backend_service, module.frontend_service]
}
