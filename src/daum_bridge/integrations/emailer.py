"""Email finished rides as TCX attachments.

This is an alternative to the Strava API upload: every finished ride already
has a TCX document (see :mod:`daum_bridge.integrations.tcx`), so it can be
sent to a mail address and uploaded manually (or kept as a backup) without
any third-party API subscription.

Configuration (``config.yaml`` ``email:`` section or environment):

- ``host`` / ``DAUM_EMAIL_HOST`` (e.g. ``smtp.gmail.com``)
- ``port`` / ``DAUM_EMAIL_PORT`` (587 for STARTTLS, 465 for SSL)
- ``username`` / ``DAUM_EMAIL_USER``
- ``password`` / ``DAUM_EMAIL_PASSWORD`` (for Gmail use an app password)
- ``from_addr`` / ``DAUM_EMAIL_FROM``
- ``to_addr`` / ``DAUM_EMAIL_TO`` (comma-separated recipients allowed)
- ``use_tls`` / ``DAUM_EMAIL_TLS`` (STARTTLS, default true)
- ``use_ssl`` / ``DAUM_EMAIL_SSL`` (implicit TLS, default false)
- ``auto_send`` / ``DAUM_EMAIL_AUTO_SEND`` (send on every finished ride)
"""
from __future__ import annotations

import logging
import smtplib
import ssl
import time
from email.message import EmailMessage
from typing import Optional

from ..config import EmailConfig
from .tcx import build_tcx

log = logging.getLogger(__name__)

TCX_MEDIA_SUBTYPE = "vnd.garmin.tcx+xml"
STRAVA_UPLOAD_URL = "https://www.strava.com/upload/select"


def _fmt_date(ride: dict) -> str:
    start = ride.get("start")
    if not start:
        return "unknown date"
    try:
        return time.strftime("%Y-%m-%d %H:%M", time.localtime(float(start)))
    except (TypeError, ValueError, OSError):
        return "unknown date"


def _fmt_duration(seconds) -> str:
    try:
        total = max(0, int(float(seconds or 0)))
    except (TypeError, ValueError):
        total = 0
    hours, rest = divmod(total, 3600)
    minutes, secs = divmod(rest, 60)
    if hours:
        return f"{hours}h {minutes:02d}m"
    if minutes:
        return f"{minutes}m {secs:02d}s"
    return f"{secs}s"


def _recipients(cfg: EmailConfig, to: Optional[str] = None) -> list[str]:
    raw = to or cfg.to_addr
    return [part.strip() for part in str(raw).replace(";", ",").split(",") if part.strip()]


def build_ride_message(
    ride: dict,
    tcx: str | bytes,
    cfg: EmailConfig,
    to: Optional[str] = None,
    subject: Optional[str] = None,
) -> EmailMessage:
    """Build the TCX email for ``ride`` (without sending it)."""
    ride_id = str(ride.get("id") or "ride")
    date = _fmt_date(ride)
    recipients = _recipients(cfg, to)
    if not recipients:
        raise ValueError("No email recipient configured (email.to_addr or DAUM_EMAIL_TO)")

    if subject is None:
        distance = float(ride.get("distance") or 0)
        subject = f"{cfg.subject_prefix}: {date} ({distance:.1f} km)"

    body = (
        "Hi,\n\n"
        f"your training on {date} is attached as a TCX file.\n\n"
        f"Duration:      {_fmt_duration(ride.get('duration'))}\n"
        f"Distance:      {float(ride.get('distance') or 0):.2f} km\n"
        f"Average power: {float(ride.get('avg_power') or 0):.0f} W\n"
        f"Max power:     {float(ride.get('max_power') or 0):.0f} W\n"
        f"Work:          {float(ride.get('work_kj') or 0):.1f} kJ\n\n"
        f"Upload the file at {STRAVA_UPLOAD_URL} or to any other training "
        "platform.\n\n"
        "-- daum-bridge\n"
    )

    msg = EmailMessage()
    msg["Subject"] = subject
    msg["From"] = cfg.from_addr
    msg["To"] = ", ".join(recipients)
    msg.set_content(body)
    content = tcx.encode("utf-8") if isinstance(tcx, str) else tcx
    msg.add_attachment(
        content,
        maintype="application",
        subtype=TCX_MEDIA_SUBTYPE,
        filename=f"{ride_id}.tcx",
    )
    return msg


def send_ride_email(
    ride: dict,
    cfg: Optional[EmailConfig],
    tcx: Optional[str | bytes] = None,
    to: Optional[str] = None,
    subject: Optional[str] = None,
) -> dict:
    """Send ``ride`` as a TCX attachment. Returns ``{"ok": bool, ...}``."""
    if cfg is None or not cfg.is_configured():
        return {
            "ok": False,
            "error": (
                "Email is not configured. Set email.host/from_addr/to_addr in "
                "config.yaml or DAUM_EMAIL_HOST/DAUM_EMAIL_FROM/DAUM_EMAIL_TO."
            ),
        }
    if not ride:
        return {"ok": False, "error": "No ride to send"}

    try:
        if tcx is None:
            tcx = build_tcx(ride)
        message = build_ride_message(ride, tcx, cfg, to=to, subject=subject)
    except Exception as e:
        log.exception("Could not build ride email")
        return {"ok": False, "error": str(e)}

    try:
        if cfg.use_ssl:
            context = ssl.create_default_context()
            client: smtplib.SMTP = smtplib.SMTP_SSL(
                cfg.host, cfg.port, timeout=cfg.timeout, context=context
            )
        else:
            client = smtplib.SMTP(cfg.host, cfg.port, timeout=cfg.timeout)
        with client:
            client.ehlo()
            if cfg.use_tls and not cfg.use_ssl:
                client.starttls(context=ssl.create_default_context())
                client.ehlo()
            if cfg.username:
                client.login(cfg.username, cfg.password)
            client.send_message(message)
    except Exception as e:
        log.error("Could not send ride email via %s:%s: %s", cfg.host, cfg.port, e)
        return {"ok": False, "error": str(e)}

    log.info("Emailed ride %s to %s", ride.get("id"), message["To"])
    return {
        "ok": True,
        "to": message["To"],
        "subject": str(message["Subject"]),
    }
