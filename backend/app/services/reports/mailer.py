"""Email delivery with pluggable backends: smtp | file (outbox) | console."""
from __future__ import annotations

import asyncio
import logging
import re
from datetime import UTC, datetime
from email.message import EmailMessage
from pathlib import Path
from typing import Any

import aiosmtplib

from app.core.config import settings

log = logging.getLogger(__name__)


def _html_to_text(html: str) -> str:
    text = re.sub(r"<style.*?</style>", "", html, flags=re.S | re.I)
    text = re.sub(r"<br\s*/?>|</p>|</div>|</tr>|</li>|</h\d>", "\n", text, flags=re.I)
    text = re.sub(r"<[^>]+>", "", text)
    text = re.sub(r"\n\s*\n+", "\n\n", text)
    return text.strip()


def _write_outbox(raw: bytes, html: str, subject: str) -> Path:
    out_dir = Path(settings.outbox_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now(UTC).strftime("%Y%m%dT%H%M%S%f")
    safe_subject = re.sub(r"[^a-zA-Z0-9]+", "-", subject)[:60].strip("-")
    path = out_dir / f"{stamp}-{safe_subject}.eml"
    path.write_bytes(raw)
    (out_dir / f"{stamp}-{safe_subject}.html").write_text(html, encoding="utf-8")
    return path


async def send_email(recipients: list[str], subject: str, html: str) -> str:
    """Send an email. Returns a human-readable delivery info string."""
    backend = settings.resolved_email_backend
    msg = EmailMessage()
    msg["From"] = settings.smtp_from
    msg["To"] = ", ".join(recipients)
    msg["Subject"] = subject
    msg.set_content(_html_to_text(html))
    msg.add_alternative(html, subtype="html")

    if backend == "smtp":
        kwargs: dict[str, Any] = {"hostname": settings.smtp_host, "port": settings.smtp_port, "timeout": 30}
        if settings.smtp_use_ssl:
            kwargs["use_tls"] = True
        elif settings.smtp_use_tls:
            kwargs["start_tls"] = True
        if settings.smtp_user:
            kwargs["username"] = settings.smtp_user
            kwargs["password"] = settings.smtp_password
        await aiosmtplib.send(msg, **kwargs)
        return f"Sent via SMTP {settings.smtp_host}:{settings.smtp_port} to {', '.join(recipients)}"

    if backend == "console":
        log.info("=== EMAIL to %s: %s ===\n%s", recipients, subject, _html_to_text(html)[:2000])
        return "Printed to server console (EMAIL_BACKEND=console)"

    # file outbox (default in dev) – file IO off the event loop
    path = await asyncio.to_thread(_write_outbox, bytes(msg), html, subject)
    return f"Saved to outbox: {path.name} (configure SMTP_HOST to send real emails)"
