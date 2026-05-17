variable "project_id"   { type = string }
variable "admin_email"  { type = string }
variable "backend_url"  { type = string }
variable "frontend_url" { type = string }

# ─── Notification channel ────────────────────────────────────────────────────

resource "google_monitoring_notification_channel" "email" {
  project      = var.project_id
  display_name = "Admin Email"
  type         = "email"
  labels = {
    email_address = var.admin_email
  }
}

# ─── Uptime check ─────────────────────────────────────────────────────────────

resource "google_monitoring_uptime_check_config" "backend_health" {
  project      = var.project_id
  display_name = "Backend Health Check"
  timeout      = "10s"
  period       = "60s"

  http_check {
    path         = "/health"
    port         = 443
    use_ssl      = true
    validate_ssl = true
  }

  monitored_resource {
    type = "uptime_url"
    labels = {
      project_id = var.project_id
      host       = replace(replace(var.backend_url, "https://", ""), "/", "")
    }
  }
}

# ─── Alert policies ───────────────────────────────────────────────────────────

resource "google_monitoring_alert_policy" "uptime_failure" {
  project      = var.project_id
  display_name = "Backend Uptime Failure"
  combiner     = "OR"

  conditions {
    display_name = "Uptime check failing > 2 min"
    condition_threshold {
      filter          = "metric.type=\"monitoring.googleapis.com/uptime_check/check_passed\" resource.type=\"uptime_url\""
      comparison      = "COMPARISON_LT"
      threshold_value = 1
      duration        = "120s"
      aggregations {
        alignment_period   = "60s"
        per_series_aligner = "ALIGN_NEXT_OLDER"
        cross_series_reducer = "REDUCE_COUNT_FALSE"
        group_by_fields    = ["resource.labels.host"]
      }
    }
  }

  notification_channels = [google_monitoring_notification_channel.email.id]
  alert_strategy { auto_close = "604800s" }
}

resource "google_monitoring_alert_policy" "high_error_rate" {
  project      = var.project_id
  display_name = "High API Error Rate"
  combiner     = "OR"

  conditions {
    display_name = "5xx error rate > 5% over 5 min"
    condition_threshold {
      filter          = "metric.type=\"run.googleapis.com/request_count\" resource.type=\"cloud_run_revision\" metric.labels.response_code_class=\"5xx\""
      comparison      = "COMPARISON_GT"
      threshold_value = 0.05
      duration        = "300s"
      aggregations {
        alignment_period     = "60s"
        per_series_aligner   = "ALIGN_RATE"
        cross_series_reducer = "REDUCE_SUM"
      }
    }
  }

  notification_channels = [google_monitoring_notification_channel.email.id]
  alert_strategy { auto_close = "604800s" }
}

resource "google_monitoring_alert_policy" "high_latency" {
  project      = var.project_id
  display_name = "High API Latency"
  combiner     = "OR"

  conditions {
    display_name = "p99 latency > 10s over 5 min"
    condition_threshold {
      filter          = "metric.type=\"run.googleapis.com/request_latencies\" resource.type=\"cloud_run_revision\""
      comparison      = "COMPARISON_GT"
      threshold_value = 10000
      duration        = "300s"
      aggregations {
        alignment_period     = "60s"
        per_series_aligner   = "ALIGN_PERCENTILE_99"
        cross_series_reducer = "REDUCE_MAX"
      }
    }
  }

  notification_channels = [google_monitoring_notification_channel.email.id]
  alert_strategy { auto_close = "604800s" }
}

# ─── Log-based metrics ────────────────────────────────────────────────────────

resource "google_logging_metric" "api_request_count" {
  project     = var.project_id
  name        = "api_request_count"
  filter      = "jsonPayload.event=\"api_request\""
  metric_descriptor {
    metric_kind = "DELTA"
    value_type  = "INT64"
    labels {
      key         = "path"
      value_type  = "STRING"
      description = "Request path"
    }
    labels {
      key         = "status_code"
      value_type  = "INT64"
      description = "HTTP status code"
    }
  }
  label_extractors = {
    "path"        = "EXTRACT(jsonPayload.path)"
    "status_code" = "EXTRACT(jsonPayload.status_code)"
  }
}

resource "google_logging_metric" "feature_usage_count" {
  project = var.project_id
  name    = "feature_usage_count"
  filter  = "jsonPayload.event=\"feature_used\""
  metric_descriptor {
    metric_kind = "DELTA"
    value_type  = "INT64"
    labels {
      key        = "feature"
      value_type = "STRING"
    }
    labels {
      key        = "page"
      value_type = "STRING"
    }
  }
  label_extractors = {
    "feature" = "EXTRACT(jsonPayload.feature)"
    "page"    = "EXTRACT(jsonPayload.page)"
  }
}

# ─── Dashboard ────────────────────────────────────────────────────────────────

resource "google_monitoring_dashboard" "main" {
  project        = var.project_id
  dashboard_json = jsonencode({
    displayName = "Travel Planner — Production"
    mosaicLayout = {
      columns = 12
      tiles = [
        {
          width  = 6
          height = 4
          widget = {
            title = "Cloud Run Request Count"
            xyChart = {
              dataSets = [{
                timeSeriesQuery = {
                  timeSeriesFilter = {
                    filter = "metric.type=\"run.googleapis.com/request_count\" resource.type=\"cloud_run_revision\""
                    aggregation = { alignmentPeriod = "60s", perSeriesAligner = "ALIGN_RATE" }
                  }
                }
              }]
            }
          }
        },
        {
          xPos   = 6
          width  = 6
          height = 4
          widget = {
            title = "Cloud Run Error Rate"
            xyChart = {
              dataSets = [{
                timeSeriesQuery = {
                  timeSeriesFilter = {
                    filter = "metric.type=\"run.googleapis.com/request_count\" resource.type=\"cloud_run_revision\" metric.labels.response_code_class=\"5xx\""
                    aggregation = { alignmentPeriod = "60s", perSeriesAligner = "ALIGN_RATE" }
                  }
                }
              }]
            }
          }
        },
        {
          yPos   = 4
          width  = 6
          height = 4
          widget = {
            title = "p50 / p99 Latency (ms)"
            xyChart = {
              dataSets = [{
                timeSeriesQuery = {
                  timeSeriesFilter = {
                    filter = "metric.type=\"run.googleapis.com/request_latencies\" resource.type=\"cloud_run_revision\""
                    aggregation = { alignmentPeriod = "60s", perSeriesAligner = "ALIGN_PERCENTILE_99" }
                  }
                }
              }]
            }
          }
        },
        {
          xPos   = 6
          yPos   = 4
          width  = 6
          height = 4
          widget = {
            title = "Feature Usage"
            xyChart = {
              dataSets = [{
                timeSeriesQuery = {
                  timeSeriesFilter = {
                    filter = "metric.type=\"logging.googleapis.com/user/feature_usage_count\""
                    aggregation = { alignmentPeriod = "3600s", perSeriesAligner = "ALIGN_SUM" }
                  }
                }
              }]
            }
          }
        }
      ]
    }
  })
}
