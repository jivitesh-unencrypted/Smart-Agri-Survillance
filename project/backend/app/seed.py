from app.core.config import settings
from app.core.database import SessionLocal
from app.models.settings import AppSettings


def seed_defaults():
    """
    Seeds only the app-wide settings row. There is no default/bootstrap
    admin account - accounts are created by users themselves via
    POST /api/auth/register (see app/api/auth.py), with no approval
    step. The very first time the app is opened with an empty
    database, the login page's "Create account" tab is how the first
    user gets in.
    """
    db = SessionLocal()
    try:
        if db.get(AppSettings, 1) is None:
            db.add(AppSettings(
                id=1,
                confidence_threshold=settings.DEFAULT_CONFIDENCE_THRESHOLD,
                iou_threshold=settings.DEFAULT_IOU_THRESHOLD,
            ))
            db.commit()
    finally:
        db.close()
