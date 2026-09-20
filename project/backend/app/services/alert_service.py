"""
Alert generation. Mirrors the severity rules from the original
project's utils/alerts.py:
    Human    -> Critical / Intrusion Alert
    Animals  -> Warning  / Animal Activity
    Vehicles -> Info     / Vehicle Activity
    Others   -> Normal   / Object Detected
"""
from typing import Any, Dict, Optional

from app.core.database import SessionLocal
from app.models.alert import Alert
from app.models.settings import AppSettings

_TITLES = {
    "Human": "Intrusion Alert",
    "Animals": "Animal Activity",
    "Vehicles": "Vehicle Activity",
    "Others": "Object Detected",
}


def _get_settings(db) -> AppSettings:
    row = db.get(AppSettings, 1)
    if row is None:
        row = AppSettings(id=1)
        db.add(row)
        db.commit()
        db.refresh(row)
    return row


def create_alert_for_detection(event: Dict[str, Any]) -> Optional[Dict[str, Any]]:
    """
    Creates an Alert row for a newly-opened detection event, respecting
    the user's alert-category toggles. Returns a broadcast-ready dict,
    or None if alerts are disabled for this category.
    """
    category = event.get("category", "Others")

    db = SessionLocal()
    try:
        app_settings = _get_settings(db)
        if not app_settings.alerts_enabled:
            return None
        if category == "Human" and not app_settings.alert_on_human:
            return None
        if category == "Animals" and not app_settings.alert_on_animal:
            return None
        if category == "Vehicles" and not app_settings.alert_on_vehicle:
            return None

        title = _TITLES.get(category, "Object Detected")
        cam_name = event.get("camera_name") or "Camera"
        location = event.get("location") or ""
        obj_name = str(event.get("object_name", "object")).title()

        message = f"{obj_name} detected on {cam_name}"
        if location:
            message += f" ({location})"

        row = Alert(
            detection_id=event.get("id"),
            camera_id=event.get("camera_id"),
            camera_name=cam_name,
            category=category,
            severity=event.get("severity", "normal"),
            title=title,
            message=message,
        )
        db.add(row)
        db.commit()
        db.refresh(row)

        return {
            "id": row.id,
            "detection_id": row.detection_id,
            "camera_id": row.camera_id,
            "camera_name": row.camera_name,
            "category": row.category,
            "severity": row.severity,
            "title": row.title,
            "message": row.message,
            "acknowledged": row.acknowledged,
            "resolved": row.resolved,
            "created_at": row.created_at.isoformat() if row.created_at else None,
        }
    finally:
        db.close()
