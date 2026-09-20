from datetime import datetime, timezone

from sqlalchemy import Column, Integer, Float, Boolean, String

from app.core.types import UTCDateTime

from app.core.database import Base


class AppSettings(Base):
    """
    Single-row table holding all user-configurable settings. Row id is
    always 1 - see app/services/settings_service.py.
    """
    __tablename__ = "settings"

    id = Column(Integer, primary_key=True, default=1)

    # Detection
    confidence_threshold = Column(Float, nullable=False, default=0.25)
    iou_threshold = Column(Float, nullable=False, default=0.45)
    inference_interval_ms = Column(Integer, nullable=False, default=400)
    frame_skip = Column(Integer, nullable=False, default=2)
    event_cooldown_seconds = Column(Integer, nullable=False, default=8)

    # Alerts / sound
    alerts_enabled = Column(Boolean, nullable=False, default=True)
    sound_enabled = Column(Boolean, nullable=False, default=True)
    alert_on_human = Column(Boolean, nullable=False, default=True)
    alert_on_animal = Column(Boolean, nullable=False, default=True)
    alert_on_vehicle = Column(Boolean, nullable=False, default=False)

    # Storage
    snapshot_on_event = Column(Boolean, nullable=False, default=True)
    max_snapshot_age_days = Column(Integer, nullable=False, default=30)

    # Model
    model_path = Column(String(512), nullable=True)

    updated_at = Column(UTCDateTime, default=lambda: datetime.now(timezone.utc),
                         onupdate=lambda: datetime.now(timezone.utc))
