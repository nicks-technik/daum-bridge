"""Power control for the machine running the bridge.

The Raspberry Pi has no power button, so the only clean way to switch the whole
setup off is to ask the OS to power down. This module isolates that single
privileged call so nothing else in the bridge needs to think about privilege
escalation.

The bridge never runs as root and never prompts for a password: it calls
``sudo -n`` (non-interactive) and relies on a *scoped* sudoers rule that grants
exactly the shutdown binary. That is deliberate — the web UI has no
authentication and listens on ``0.0.0.0``, so a blanket ``NOPASSWD: ALL`` rule
would hand root to anyone who can reach the port. See ``docs/installation.md``
for the rule.

Failures are returned as a result dict rather than raised: the button has to be
able to explain *why* nothing happened (no sudo installed, no rule in place,
shutdown refused), and a traceback in the browser would not do that.
"""

from __future__ import annotations

import logging
import subprocess

log = logging.getLogger(__name__)

#: sudo itself. Fixed path, because a privileged call must not depend on PATH.
SUDO_BINARY = "/usr/bin/sudo"

#: ``shutdown`` as shipped by Debian/Raspberry Pi OS. ``/sbin`` is a symlink to
#: ``/usr/sbin`` on merged-usr systems, so the sudoers rule lists both spellings.
SHUTDOWN_BINARY = "/sbin/shutdown"

#: A hung sudo must not occupy a web worker indefinitely.
SHUTDOWN_TIMEOUT = 15.0

#: What sudo prints when the rule is missing but a password would be required.
#: Without ``-n`` sudo would sit waiting for input until the timeout.
_PASSWORD_MARKERS = (
    "a password is required",
    "a terminal is required",
    "no tty present",
    "sorry, you must have a tty",
)


def shutdown_system() -> dict:
    """Power off the machine immediately.

    Returns a JSON-friendly dict with ``ok``, ``error`` and the command that was
    executed, so the web UI can show either "shutting down" or the reason it
    could not. ``ok`` is true only when ``shutdown`` itself accepted the request.
    """
    command = [SUDO_BINARY, "-n", SHUTDOWN_BINARY, "-h", "now"]
    printable = " ".join(command)

    try:
        completed = subprocess.run(
            command,
            capture_output=True,
            text=True,
            timeout=SHUTDOWN_TIMEOUT,
            check=False,
        )
    except FileNotFoundError:
        return _failure(
            f"sudo was not found at {SUDO_BINARY}. The shutdown button needs "
            "sudo plus the sudoers rule described in docs/installation.md.",
            printable,
        )
    except subprocess.TimeoutExpired:
        return _failure(
            f"'{printable}' did not return within {SHUTDOWN_TIMEOUT:.0f} s.",
            printable,
        )
    except OSError as e:
        return _failure(f"Could not run '{printable}': {e}", printable)

    if completed.returncode == 0:
        log.info("Shutdown requested: %s", printable)
        return {"ok": True, "error": None, "command": printable}

    detail = (completed.stderr or completed.stdout or "").strip()
    if not detail or any(marker in detail.lower() for marker in _PASSWORD_MARKERS):
        # sudo refused before running anything: the rule is not installed.
        detail = (
            "sudo refused the shutdown without a password. Install the scoped "
            "sudoers rule from docs/installation.md (NOPASSWD for the shutdown "
            "binary only)."
        )
    log.warning("Shutdown failed (exit %s): %s", completed.returncode, detail)
    return {"ok": False, "error": detail, "command": printable}


def _failure(message: str, command: str) -> dict:
    """Build the result dict for a call that never reached ``shutdown``."""
    log.warning("Shutdown failed: %s", message)
    return {"ok": False, "error": message, "command": command}
