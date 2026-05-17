# Deployment

See the root [DEPLOYMENT.md](../DEPLOYMENT.md) for the full step-by-step guide.

## Infrastructure Overview

```
GitHub Actions (CI/CD)
         │
         ▼
Artifact Registry (Docker images)
         │
    ┌────┴──────┐
    ▼           ▼
Cloud Run    Cloud Run
(Backend)    (Frontend)
512MB          256MB
min=0          min=0
         │
         ▼
Cloud Storage (SQLite backup)
Secret Manager (API keys)
Cloud Monitoring (dashboards + alerts)
```

All resources in `europe-west1`.

## Terraform Modules

| Module | Purpose |
|---|---|
| `project` | GCP project + API enablement |
| `iam` | Cloud Run SA + GitHub Actions SA |
| `artifact_registry` | Docker image registry |
| `storage` | SQLite backup bucket (versioned, keep 10) |
| `secrets` | Secret Manager shells (values set by populate-secrets.sh) |
| `backend_service` | Cloud Run v2 backend service |
| `frontend_service` | Cloud Run v2 frontend service |
| `monitoring` | Uptime checks, alert policies, log metrics, dashboard |
