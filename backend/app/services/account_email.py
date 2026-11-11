"""Localised account emails: verify, password reset, already registered.

Multipart text + inline-styled HTML, no remote images. Wording comes from
``app/i18n/emails/<lang>.json`` (unknown locales fall back to English). With
SMTP unset and dev links on, the link is logged instead of sent. The
recipient address is never logged.
"""

import asyncio
import html
import json
import logging
import re
from email.message import EmailMessage
from email.utils import formatdate, make_msgid
from functools import cache
from pathlib import Path
from typing import Literal
from urllib.parse import urlparse

from ..core.config import settings
from ..core.urls import public_base_url, public_url
from .alert_email import _POLICY, _mail_domain, _sender, send_message

logger = logging.getLogger(__name__)

Kind = Literal["verify", "reset", "already_registered"]
_DIR = Path(__file__).resolve().parent.parent / "i18n" / "emails"
_FALLBACK = "en"


def dev_links_enabled() -> bool:
    if settings.smtp_host:
        return False
    if settings.email_log_links:
        return True
    return (urlparse(public_base_url()).hostname or "") in ("localhost", "127.0.0.1")


def email_delivery_available() -> bool:
    return bool(settings.smtp_host) or dev_links_enabled()


@cache
def _catalog(lang: str) -> dict[str, str]:
    return json.loads((_DIR / f"{lang}.json").read_text(encoding="utf-8"))


def _lang(locale: str | None) -> str:
    base = (locale or "").strip().lower().replace("_", "-").split("-")[0]
    return base if base and (_DIR / f"{base}.json").is_file() else _FALLBACK


def _fill(text: str, values: dict[str, str]) -> str:
    return re.sub(r"\{\{(\w+)\}\}", lambda m: values.get(m.group(1), m.group(0)), text)


def build_account_message(
    kind: Kind, to: str, *, link: str | None, locale: str | None, username: str
) -> EmailMessage:
    cat = _catalog(_lang(locale))
    values = {
        "minutes": str(settings.account_token_ttl_minutes),
        "username": username,
    }
    t = {
        k: _fill(cat[f"{kind}.{k}"], values)
        for k in ("subject", "heading", "body", "button", "ignore")
    }
    footer = cat["footer"]
    url = link or public_url("/login")

    msg = EmailMessage(policy=_POLICY)
    msg["Subject"] = t["subject"]
    msg["From"] = _sender()
    msg["To"] = to
    msg["Date"] = formatdate(localtime=False, usegmt=True)
    msg["Message-ID"] = make_msgid(domain=_mail_domain())
    msg.set_content(
        "\n".join(
            [t["heading"], "", t["body"], "", f"{t['button']}: {url}", "", t["ignore"]]
            + ["", footer]
        )
        + "\n"
    )
    e = {k: html.escape(v) for k, v in t.items()}
    btn = (
        "display:inline-block;padding:10px 18px;border-radius:999px;"
        "font-weight:600;font-size:14px;text-decoration:none;"
        "background:#0284c7;color:#ffffff;"
    )
    msg.add_alternative(
        f"""<!doctype html>
<html lang="{_lang(locale)}"><body style="margin:0;padding:24px;background:#f0f9ff;font-family:-apple-system,Segoe UI,Roboto,Helvetica,Arial,sans-serif;color:#0f172a;">
<table role="presentation" width="100%" cellpadding="0" cellspacing="0" style="max-width:520px;margin:0 auto;background:#ffffff;border-radius:16px;border:1px solid #e2e8f0;">
<tr><td style="padding:24px 28px;">
<p style="margin:0 0 4px;font-size:12px;letter-spacing:.08em;text-transform:uppercase;color:#0d9488;font-weight:700;">Voyager</p>
<h1 style="margin:0 0 8px;font-size:20px;line-height:1.3;">{e["heading"]}</h1>
<p style="margin:0 0 16px;font-size:14px;color:#475569;">{e["body"]}</p>
<p style="margin:20px 0 0;"><a href="{html.escape(url)}" style="{btn}">{e["button"]}</a></p>
<p style="margin:20px 0 0;font-size:12px;color:#94a3b8;">{e["ignore"]}</p>
</td></tr></table>
<p style="max-width:520px;margin:12px auto 0;font-size:11px;color:#94a3b8;text-align:center;">{html.escape(footer)}</p>
</body></html>
""",
        subtype="html",
    )
    return msg


async def send_account_email(
    kind: Kind,
    to: str,
    *,
    link: str | None,
    locale: str | None,
    username: str,
) -> bool:
    """Send (or, in dev, log the link of) an account email. Never raises."""
    try:
        if dev_links_enabled():
            logger.info("account_email.dev_link kind=%s url=%s", kind, link)
            return True
        if not settings.smtp_host:
            return False
        msg = build_account_message(
            kind, to, link=link, locale=locale, username=username
        )
        await asyncio.to_thread(send_message, msg)
        logger.info("account_email.sent kind=%s", kind)
        return True
    except Exception as exc:
        logger.warning(
            "account_email.failed kind=%s error=%s", kind, type(exc).__name__
        )
        return False
