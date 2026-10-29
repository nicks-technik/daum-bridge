"""Human-readable date and duration formatting.

The web UI and the email export show the same ride metadata, so the formatting
lives here instead of being duplicated in ``web/app.py`` and
``integrations/emailer.py``. The two only differ in what they print for a
missing or corrupt timestamp, which is why every function takes a ``fallback``
argument rather than hard-coding one message.
"""

from __future__ import annotations

import time


def format_datetime(value, fallback: str = "-") -> str:
    """Format a UNIX timestamp as ``YYYY-MM-DD HH:MM`` in local time.

    Used for ride start times in tables, emails and the web UI. An unparseable
    value (missing key, ``None``, a string from a hand-edited file) returns
    ``fallback`` so a single corrupt ride cannot break a whole page.
    """
    try:
        return time.strftime("%Y-%m-%d %H:%M", time.localtime(float(value)))
    except (TypeError, ValueError, OSError):
        return fallback


def format_duration(seconds, fallback: str = "0s") -> str:
    """Format a duration in seconds as ``2h 05m`` / ``12m 30s`` / ``8s``.

    Hours and minutes are only shown when non-zero, which keeps short rides
    readable ("45s") without hiding the hours on a long one ("3h 12m").
    """
    try:
        total = max(0, int(float(seconds or 0)))
    except (TypeError, ValueError):
        return fallback
    hours, rest = divmod(total, 3600)
    minutes, remaining_seconds = divmod(rest, 60)
    if hours:
        return f"{hours}h {minutes:02d}m"
    if minutes:
        return f"{minutes}m {remaining_seconds:02d}s"
    return f"{remaining_seconds}s"
