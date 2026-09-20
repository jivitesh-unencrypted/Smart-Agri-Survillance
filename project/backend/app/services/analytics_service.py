from collections import defaultdict
from datetime import datetime, timedelta, timezone

from sqlalchemy import func
from sqlalchemy.orm import Session

from app.core.config import CATEGORY_ORDER
from app.models.detection import Detection


def _empty_bucket():
    return {"Human": 0, "Animals": 0, "Vehicles": 0, "Others": 0}


def _bucketed_series(db: Session, since: datetime, fmt_key):
    rows = db.query(Detection.category, Detection.created_at).filter(Detection.created_at >= since).all()
    buckets = defaultdict(_empty_bucket)
    for category, created_at in rows:
        key = fmt_key(created_at)
        if category not in buckets[key]:
            buckets[key][category] = 0
        buckets[key][category] += 1
    ordered_keys = sorted(buckets.keys())
    return [{"bucket": k, **buckets[k]} for k in ordered_keys]


def get_analytics(db: Session) -> dict:
    now = datetime.now(timezone.utc)

    daily = _bucketed_series(db, now - timedelta(hours=24), lambda dt: dt.strftime("%Y-%m-%d %H:00"))
    weekly = _bucketed_series(db, now - timedelta(days=7), lambda dt: dt.strftime("%Y-%m-%d"))
    monthly = _bucketed_series(db, now - timedelta(days=30), lambda dt: dt.strftime("%Y-%m-%d"))

    by_category = {cat: 0 for cat in CATEGORY_ORDER}
    for category, count in db.query(Detection.category, func.count(Detection.id)).group_by(Detection.category).all():
        by_category[category] = count

    by_camera = []
    for camera_name, count in (
        db.query(Detection.camera_name, func.count(Detection.id))
        .filter(Detection.camera_name.isnot(None))
        .group_by(Detection.camera_name)
        .order_by(func.count(Detection.id).desc())
        .limit(10)
        .all()
    ):
        by_camera.append({"camera_name": camera_name or "Unknown", "count": count})

    # Peak detection hours (0-23) over all history.
    hour_counts = defaultdict(int)
    for (created_at,) in db.query(Detection.created_at).all():
        hour_counts[created_at.hour] += 1
    peak_hours = [{"hour": h, "count": hour_counts.get(h, 0)} for h in range(24)]

    return {
        "daily": daily,
        "weekly": weekly,
        "monthly": monthly,
        "by_category": by_category,
        "by_camera": by_camera,
        "peak_hours": peak_hours,
    }
