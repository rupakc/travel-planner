"""Structured JSON logging for Cloud Run / Cloud Logging."""

import json
import logging
import sys


class JSONFormatter(logging.Formatter):
    def format(self, record: logging.LogRecord) -> str:
        payload = {
            "severity": record.levelname,
            "message": record.getMessage(),
            "module": record.module,
        }
        if record.exc_info:
            payload["exception"] = self.formatException(record.exc_info)
        request_id = getattr(record, "request_id", None)
        if request_id:
            payload["request_id"] = request_id
        return json.dumps(payload)


class RedactSecrets(logging.Filter):
    """Masks third-party API keys sent in request headers (Tripadvisor's
    ``X-API-Key``, Google TIM's ``X-Goog-Api-Key``) should one ever reach a log line, e.g. via an exception
    that echoes request headers."""

    def filter(self, record: logging.LogRecord) -> bool:
        from .config import settings

        secrets = [
            s
            for s in (settings.tripadvisor_api_key, settings.tim_api_key)
            if s and len(s) >= 8
        ]
        if not secrets:
            return True
        msg = record.getMessage()
        exc = ""
        if record.exc_info:
            exc = logging.Formatter().formatException(record.exc_info)
        if not any(s in msg or s in exc for s in secrets):
            return True
        for s in secrets:
            msg = msg.replace(s, "[redacted]")
            exc = exc.replace(s, "[redacted]")
        record.msg = msg + (f"\n{exc}" if exc else "")
        record.args = None
        record.exc_info = None
        record.exc_text = None
        return True


def configure_logging(json_logs: bool = True) -> None:
    handler = logging.StreamHandler(sys.stdout)
    handler.addFilter(RedactSecrets())
    if json_logs:
        handler.setFormatter(JSONFormatter())
    logging.basicConfig(
        level=logging.INFO,
        handlers=[handler],
        force=True,
    )
    # Quieten noisy third-party loggers
    for noisy in ("httpx", "httpcore", "uvicorn.access"):
        logging.getLogger(noisy).setLevel(logging.WARNING)
