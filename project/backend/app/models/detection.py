from datetime import datetime, timezone

from sqlalchemy import Column, Integer, String, Float, ForeignKey, Index
from sqlalchemy.orm import relationship

from app.core.database import Base
from app.core.types import UTCDateTime


class Detection(Base):
    """
    A detection EVENT, not a per-frame record. When the same
    object/category is seen continuously (gaps under the configured
    cooldown), the event's end_time/duration/confidence are updated in
    place instead of inserting a new row - see
    app/services/detection_service.py for the grouping logic.
    """
    __tablename__ = "detections"

    id = Column(Integer, primary_key=True, index=True)

    source = Column(String(32), nullable=False, default="Live Camera")  # "Live Camera" | "Video Analysis"
    camera_id = Column(Integer, ForeignKey("cameras.id", ondelete="SET NULL"), nullable=True, index=True)
    camera_name = Column(String(128), nullable=True)
    video_analysis_job_id = Column(Integer, ForeignKey("video_analysis_jobs.id", ondelete="SET NULL"),
                                    nullable=True, index=True)
    location = Column(String(128), nullable=True)

    object_name = Column(String(64), nullable=False, index=True)   # e.g. "person"
    category = Column(String(32), nullable=False, index=True)      # Human | Animals | Vehicles | Others
    severity = Column(String(16), nullable=False, default="normal")

    confidence = Column(Float, nullable=False, default=0.0)        # max confidence observed during the event
    avg_confidence = Column(Float, nullable=False, default=0.0)
    frame_count = Column(Integer, nullable=False, default=1)       # how many inference frames contributed

    start_time = Column(UTCDateTime, nullable=False, default=lambda: datetime.now(timezone.utc), index=True)
    end_time = Column(UTCDateTime, nullable=False, default=lambda: datetime.now(timezone.utc))
    duration_seconds = Column(Float, nullable=False, default=0.0)

    snapshot_path = Column(String(512), nullable=True)  # relative path under storage/snapshots

    created_at = Column(UTCDateTime, default=lambda: datetime.now(timezone.utc), index=True)

    camera = relationship("Camera", back_populates="detections")

    __table_args__ = (
        Index("ix_detections_camera_created", "camera_id", "created_at"),
        Index("ix_detections_category_created", "category", "created_at"),
    )
