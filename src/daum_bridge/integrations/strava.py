"""Strava integration - upload rides to Strava."""
from __future__ import annotations

import json
import logging
import os
from pathlib import Path
from typing import Optional

log = logging.getLogger(__name__)


class StravaClient:
    def __init__(self, access_token: Optional[str] = None, refresh_token: Optional[str] = None):
        self.access_token = access_token or os.environ.get("STRAVA_ACCESS_TOKEN", "")
        self.refresh_token = refresh_token or os.environ.get("STRAVA_REFRESH_TOKEN", "")
        self.client_id = os.environ.get("STRAVA_CLIENT_ID", "")
        self.client_secret = os.environ.get("STRAVA_CLIENT_SECRET", "")

    def is_configured(self) -> bool:
        return bool(self.access_token)

    def upload_ride(self, ride_data: dict, name: str = "Daum Bridge Ride") -> dict:
        """Upload a ride to Strava (requires stravalib or direct API)."""
        if not self.is_configured():
            return {"ok": False, "error": "Strava not configured"}
        try:
            # Try using stravalib if available
            try:
                from stravalib.client import Client
                client = Client(access_token=self.access_token)
                # Create activity
                activity = client.create_activity(
                    name=name,
                    activity_type="Ride",
                    start_date_local=ride_data.get("start_date_local"),
                    elapsed_time=int(ride_data.get("duration", 0)),
                    description=f"Power: {ride_data.get('avg_power', 0)}W avg, {ride_data.get('max_power', 0)}W max, {ride_data.get('work_kj', 0)} kJ",
                    trainer=True
                )
                return {"ok": True, "activity_id": activity.id}
            except ImportError:
                log.warning("stravalib not installed")
                return {"ok": False, "error": "stravalib not installed. Install with: pip install stravalib"}
        except Exception as e:
            log.error(f"Strava upload error: {e}")
            return {"ok": False, "error": str(e)}

    def list_activities(self, limit: int = 10) -> list:
        if not self.is_configured():
            return []
        try:
            from stravalib.client import Client
            client = Client(access_token=self.access_token)
            activities = client.get_activities(limit=limit)
            return [{"id": a.id, "name": a.name, "distance": a.distance, "start_date": str(a.start_date)} for a in activities]
        except Exception as e:
            log.debug(f"Strava list error: {e}")
            return []
