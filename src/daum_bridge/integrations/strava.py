"""Strava integration: OAuth tokens, TCX generation and activity upload.

Strava no longer allows creating manual activities through the API, so a
ride has to be uploaded as a file. This module builds a TCX document from
the recorded ride samples (see :mod:`daum_bridge.integrations.tcx`) and
posts it to the ``/uploads`` endpoint, then polls until Strava has
processed it.

Configuration (``config.yaml`` ``strava:`` section or environment):

- ``client_id`` / ``STRAVA_CLIENT_ID``
- ``client_secret`` / ``STRAVA_CLIENT_SECRET``
- ``refresh_token`` / ``STRAVA_REFRESH_TOKEN``
- ``access_token`` / ``STRAVA_ACCESS_TOKEN`` (optional, short lived)
- ``token_file`` / ``STRAVA_TOKENS_FILE`` (refreshed tokens are cached here)

Run ``daum-bridge strava-auth`` once to obtain a refresh token.
"""
from __future__ import annotations

import json
import logging
import os
import time
import urllib.error
import urllib.parse
import urllib.request
import uuid
from datetime import datetime
from pathlib import Path
from typing import Any, Optional

from .tcx import DEFAULT_NAME, build_tcx

log = logging.getLogger(__name__)

API_BASE = "https://www.strava.com/api/v3"
OAUTH_TOKEN_URL = "https://www.strava.com/oauth/token"
OAUTH_AUTHORIZE_URL = "https://www.strava.com/oauth/authorize"
DEFAULT_SCOPE = "activity:write,activity:read"
DEFAULT_TOKEN_FILE = "strava.tokens.json"


class StravaError(RuntimeError):
    """Raised when Strava rejects a request."""


def _error_message(body: bytes | str) -> str:
    text = body.decode("utf-8", "replace") if isinstance(body, bytes) else str(body)
    try:
        data = json.loads(text)
    except ValueError:
        return text.strip()[:300]
    if isinstance(data, dict):
        for key in ("message", "error", "errors"):
            if data.get(key):
                value = data[key]
                return value if isinstance(value, str) else json.dumps(value)
    return text.strip()[:300]


def _encode_multipart(
    fields: dict[str, str],
    files: dict[str, tuple[str, bytes, str]],
) -> tuple[bytes, str]:
    """Encode a multipart/form-data body without external dependencies."""
    boundary = f"----daum-bridge-{uuid.uuid4().hex}"
    chunks: list[bytes] = []
    for name, value in fields.items():
        chunks.append(f"--{boundary}\r\n".encode())
        chunks.append(f'Content-Disposition: form-data; name="{name}"\r\n\r\n'.encode())
        chunks.append(str(value).encode("utf-8"))
        chunks.append(b"\r\n")
    for name, (filename, content, content_type) in files.items():
        chunks.append(f"--{boundary}\r\n".encode())
        chunks.append(
            f'Content-Disposition: form-data; name="{name}"; filename="{filename}"\r\n'.encode()
        )
        chunks.append(f"Content-Type: {content_type}\r\n\r\n".encode())
        chunks.append(content)
        chunks.append(b"\r\n")
    chunks.append(f"--{boundary}--\r\n".encode())
    return b"".join(chunks), boundary


class StravaClient:
    """Minimal Strava API client focused on uploading ride files."""

    def __init__(
        self,
        client_id: str = "",
        client_secret: str = "",
        refresh_token: str = "",
        access_token: str = "",
        expires_at: float = 0.0,
        token_file: str = DEFAULT_TOKEN_FILE,
        timeout: float = 30.0,
        poll_interval: float = 2.0,
        poll_timeout: float = 120.0,
    ):
        self.client_id = str(client_id or os.environ.get("STRAVA_CLIENT_ID", "") or "")
        self.client_secret = str(
            client_secret or os.environ.get("STRAVA_CLIENT_SECRET", "") or ""
        )
        self.refresh_token = str(
            refresh_token or os.environ.get("STRAVA_REFRESH_TOKEN", "") or ""
        )
        self.access_token = str(
            access_token or os.environ.get("STRAVA_ACCESS_TOKEN", "") or ""
        )
        self.expires_at = float(expires_at or 0.0)
        self.token_file = str(
            token_file or os.environ.get("STRAVA_TOKENS_FILE", DEFAULT_TOKEN_FILE)
        )
        self.timeout = float(timeout)
        self.poll_interval = float(poll_interval)
        self.poll_timeout = float(poll_timeout)
        self._load_cached_tokens()

    # ------------------------------------------------------------------
    # Construction helpers
    # ------------------------------------------------------------------
    @classmethod
    def from_config(cls, config: Any) -> "StravaClient":
        """Build a client from a :class:`daum_bridge.config.StravaConfig`."""

        def _get(name: str, default: Any = "") -> Any:
            return getattr(config, name, default)

        return cls(
            client_id=_get("client_id"),
            client_secret=_get("client_secret"),
            refresh_token=_get("refresh_token"),
            access_token=_get("access_token"),
            token_file=_get("token_file", DEFAULT_TOKEN_FILE),
            poll_timeout=_get("poll_timeout", 120.0),
        )

    def is_configured(self) -> bool:
        """Return True when a request could be authenticated."""
        if self.refresh_token:
            return bool(self.client_id and self.client_secret)
        return bool(self.access_token)

    # ------------------------------------------------------------------
    # Token handling
    # ------------------------------------------------------------------
    def _load_cached_tokens(self) -> None:
        path = Path(self.token_file)
        if not path.exists():
            return
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, ValueError) as e:
            log.debug("Cannot read Strava token cache %s: %s", path, e)
            return
        if not isinstance(data, dict):
            return
        cached_refresh = str(data.get("refresh_token") or "")
        cached_access = str(data.get("access_token") or "")
        # Only trust the cache when it belongs to the configured account.
        if cached_refresh and (not self.refresh_token or cached_refresh == self.refresh_token):
            self.refresh_token = cached_refresh
            if cached_access:
                self.access_token = cached_access
                self.expires_at = float(data.get("expires_at") or 0.0)

    def _save_cached_tokens(self) -> None:
        if not (self.refresh_token or self.access_token):
            return
        path = Path(self.token_file)
        data = {
            "access_token": self.access_token,
            "refresh_token": self.refresh_token,
            "expires_at": self.expires_at,
        }
        try:
            path.parent.mkdir(parents=True, exist_ok=True)
            tmp = path.with_suffix(path.suffix + ".tmp")
            tmp.write_text(json.dumps(data, indent=2), encoding="utf-8")
            try:
                os.chmod(tmp, 0o600)
            except OSError:
                pass
            tmp.replace(path)
        except OSError as e:
            log.warning("Could not write Strava token cache %s: %s", path, e)

    def authorization_url(
        self,
        redirect_uri: str = "http://localhost",
        scope: str = DEFAULT_SCOPE,
        state: Optional[str] = None,
    ) -> str:
        """Return the URL the user must open to grant access."""
        if not self.client_id:
            raise StravaError("Strava client_id is not configured")
        params = {
            "client_id": self.client_id,
            "response_type": "code",
            "redirect_uri": redirect_uri,
            "approval_prompt": "auto",
            "scope": scope,
        }
        if state:
            params["state"] = state
        return f"{OAUTH_AUTHORIZE_URL}?{urllib.parse.urlencode(params)}"

    def exchange_code(self, code: str, redirect_uri: str = "http://localhost") -> dict:
        """Exchange an OAuth authorization code for tokens and cache them."""
        if not self.client_id or not self.client_secret:
            raise StravaError("Strava client_id and client_secret are required")
        data = self._post_token(
            {
                "client_id": self.client_id,
                "client_secret": self.client_secret,
                "code": code,
                "grant_type": "authorization_code",
                "redirect_uri": redirect_uri,
            }
        )
        self._apply_tokens(data)
        return data

    def refresh_access_token(self) -> str:
        """Refresh the access token if needed and return it."""
        if self.access_token and (not self.expires_at or self.expires_at - 60 > time.time()):
            return self.access_token
        if not self.refresh_token:
            if self.access_token:
                return self.access_token
            raise StravaError("Strava is not configured: no refresh token available")
        if not self.client_id or not self.client_secret:
            raise StravaError(
                "Strava client_id and client_secret are required to refresh the access token"
            )
        data = self._post_token(
            {
                "client_id": self.client_id,
                "client_secret": self.client_secret,
                "grant_type": "refresh_token",
                "refresh_token": self.refresh_token,
            }
        )
        self._apply_tokens(data)
        log.info("Refreshed Strava access token")
        return self.access_token

    def _post_token(self, payload: dict) -> dict:
        body = urllib.parse.urlencode(payload).encode("utf-8")
        _, response = self._request(
            "POST",
            OAUTH_TOKEN_URL,
            data=body,
            headers={
                "Content-Type": "application/x-www-form-urlencoded",
                "Accept": "application/json",
            },
        )
        try:
            data = json.loads(response.decode("utf-8"))
        except ValueError as e:
            raise StravaError(f"Invalid Strava token response: {e}") from None
        if not isinstance(data, dict) or not data.get("access_token"):
            raise StravaError(f"Strava token response missing access_token: {data}")
        return data

    def _apply_tokens(self, data: dict) -> None:
        self.access_token = str(data.get("access_token") or self.access_token)
        self.refresh_token = str(data.get("refresh_token") or self.refresh_token)
        self.expires_at = float(data.get("expires_at") or 0.0)
        self._save_cached_tokens()

    # ------------------------------------------------------------------
    # HTTP helpers
    # ------------------------------------------------------------------
    def _request(
        self,
        method: str,
        url: str,
        data: Optional[bytes] = None,
        headers: Optional[dict[str, str]] = None,
        timeout: Optional[float] = None,
    ) -> tuple[int, bytes]:
        """Perform an HTTP request. Kept as one method so tests can fake it."""
        request = urllib.request.Request(url, data=data, headers=headers or {}, method=method)
        try:
            with urllib.request.urlopen(request, timeout=timeout or self.timeout) as response:
                return int(getattr(response, "status", 200)), response.read()
        except urllib.error.HTTPError as e:
            try:
                body = e.read()
            except Exception:
                body = b""
            message = _error_message(body) or str(e.reason)
            raise StravaError(f"Strava API error ({e.code}): {message}") from None
        except urllib.error.URLError as e:
            raise StravaError(f"Cannot reach Strava: {e.reason}") from None

    def _authorized_request(
        self,
        method: str,
        path: str,
        data: Optional[bytes] = None,
        headers: Optional[dict[str, str]] = None,
    ) -> tuple[int, bytes]:
        token = self.refresh_access_token()
        request_headers = {"Authorization": f"Bearer {token}", **(headers or {})}
        try:
            return self._request(method, path, data=data, headers=request_headers)
        except StravaError as e:
            # Access token may have been revoked between refresh and use.
            if "401" not in str(e):
                raise
            log.info("Strava access token rejected, refreshing and retrying")
            self.expires_at = 0.0
            token = self.refresh_access_token()
            request_headers["Authorization"] = f"Bearer {token}"
            return self._request(method, path, data=data, headers=request_headers)

    def _json(self, method: str, path: str, **kwargs: Any) -> Any:
        _, body = self._authorized_request(method, path, **kwargs)
        try:
            return json.loads(body.decode("utf-8"))
        except ValueError as e:
            raise StravaError(f"Invalid JSON from Strava: {e}") from None

    # ------------------------------------------------------------------
    # Upload
    # ------------------------------------------------------------------
    def upload_tcx(
        self,
        tcx: str | bytes,
        name: Optional[str] = None,
        description: Optional[str] = None,
        activity_type: str = "ride",
        trainer: bool = True,
        private: bool = False,
        external_id: Optional[str] = None,
        wait: bool = True,
    ) -> dict:
        """Upload a TCX document to Strava and wait for processing.

        Returns a dict with ``ok`` plus either ``activity_id``/``upload_id``
        or ``error``. This never raises for expected API errors, making it
        safe to call directly from HTTP handlers.
        """
        if isinstance(tcx, str):
            tcx_bytes = tcx.encode("utf-8")
        else:
            tcx_bytes = bytes(tcx)
        external_id = external_id or f"daum-bridge-{int(time.time())}"
        fields = {
            "data_type": "tcx",
            "trainer": "1" if trainer else "0",
            "activity_type": activity_type,
            "external_id": external_id,
        }
        if private:
            fields["private"] = "1"
        if name:
            fields["name"] = name
        if description:
            fields["description"] = description
        body, boundary = _encode_multipart(
            fields,
            {"file": (f"{external_id}.tcx", tcx_bytes, "application/vnd.garmin.tcx+xml")},
        )
        try:
            response = self._json(
                "POST",
                f"{API_BASE}/uploads",
                data=body,
                headers={"Content-Type": f"multipart/form-data; boundary={boundary}"},
            )
        except StravaError as e:
            log.error("Strava upload failed: %s", e)
            return {"ok": False, "error": str(e), "external_id": external_id}
        if not isinstance(response, dict):
            return {"ok": False, "error": "Unexpected response from Strava", "external_id": external_id}
        if response.get("error"):
            return {"ok": False, "error": str(response["error"]), "external_id": external_id}
        if response.get("activity_id"):
            return self._upload_result(response, external_id)
        upload_id = response.get("id")
        if upload_id is None:
            return {"ok": False, "error": "Strava did not return an upload id", "external_id": external_id}
        if not wait:
            return {
                "ok": True,
                "pending": True,
                "upload_id": upload_id,
                "status": response.get("status"),
                "external_id": external_id,
            }
        return self._wait_for_upload(upload_id, external_id)

    def _wait_for_upload(self, upload_id: Any, external_id: str) -> dict:
        deadline = time.monotonic() + self.poll_timeout
        while time.monotonic() < deadline:
            try:
                data = self._json("GET", f"{API_BASE}/uploads/{upload_id}")
            except StravaError as e:
                return {"ok": False, "error": str(e), "upload_id": upload_id, "external_id": external_id}
            if isinstance(data, dict):
                if data.get("error"):
                    return {
                        "ok": False,
                        "error": str(data["error"]),
                        "upload_id": upload_id,
                        "external_id": external_id,
                    }
                if data.get("activity_id"):
                    return self._upload_result(data, external_id)
            time.sleep(self.poll_interval)
        return {
            "ok": False,
            "error": "Timed out waiting for Strava to process the upload",
            "upload_id": upload_id,
            "external_id": external_id,
        }

    @staticmethod
    def _upload_result(data: dict, external_id: str) -> dict:
        return {
            "ok": True,
            "activity_id": data.get("activity_id"),
            "upload_id": data.get("id") or data.get("upload_id"),
            "status": data.get("status"),
            "external_id": external_id,
        }

    def upload_ride(
        self,
        ride: dict,
        samples: Optional[list] = None,
        name: Optional[str] = None,
        description: Optional[str] = None,
        private: Optional[bool] = None,
        wait: bool = True,
    ) -> dict:
        """Build a TCX for ``ride`` and upload it to Strava.

        ``ride`` is the dict stored in the ride history (samples may be
        included as ``ride["samples"]``). Failures are returned as
        ``{"ok": False, "error": ...}`` instead of raising.
        """
        if not self.is_configured():
            return {
                "ok": False,
                "error": "Strava is not configured. Run 'daum-bridge strava-auth' "
                "or set STRAVA_CLIENT_ID/STRAVA_CLIENT_SECRET/STRAVA_REFRESH_TOKEN.",
            }
        try:
            tcx = build_tcx(ride, samples)
        except Exception as e:  # pragma: no cover - defensive
            log.exception("Could not build TCX")
            return {"ok": False, "error": f"Could not build TCX: {e}"}

        if not name:
            start = ride.get("start")
            when = ""
            if start:
                try:
                    when = " – " + datetime.fromtimestamp(float(start)).strftime("%Y-%m-%d %H:%M")
                except (TypeError, ValueError, OSError):
                    when = ""
            name = f"{DEFAULT_NAME}{when}"
        if not description:
            parts = []
            if ride.get("avg_power"):
                parts.append(f"{float(ride['avg_power']):.0f} W avg")
            if ride.get("max_power"):
                parts.append(f"{float(ride['max_power']):.0f} W max")
            if ride.get("distance"):
                parts.append(f"{float(ride['distance']):.1f} km")
            if ride.get("work_kj"):
                parts.append(f"{float(ride['work_kj']):.0f} kJ")
            description = " · ".join(parts) + (" · " if parts else "") + "Recorded with daum-bridge"
        if private is None:
            private = False
        external_id = f"daum-{ride.get('id') or int(time.time())}"
        return self.upload_tcx(
            tcx,
            name=name,
            description=description,
            private=bool(private),
            external_id=external_id,
            wait=wait,
        )

    # ------------------------------------------------------------------
    # Read helpers (optional)
    # ------------------------------------------------------------------
    def list_activities(self, limit: int = 10) -> list:
        """Return the athlete's most recent activities (read scope needed)."""
        if not self.is_configured():
            return []
        try:
            activities = self._json(
                "GET", f"{API_BASE}/athlete/activities?per_page={int(limit)}"
            )
        except StravaError as e:
            log.debug("Strava list activities failed: %s", e)
            return []
        if not isinstance(activities, list):
            return []
        return [
            {
                "id": a.get("id"),
                "name": a.get("name"),
                "distance": a.get("distance"),
                "start_date": a.get("start_date"),
            }
            for a in activities
            if isinstance(a, dict)
        ]
