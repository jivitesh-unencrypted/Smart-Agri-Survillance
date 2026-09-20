from datetime import datetime, timezone

from sqlalchemy import Column, Integer, String, Float, Boolean

from app.core.types import UTCDateTime

from app.core.database import Base


class VideoAnalysisJob(Base):
    """
    Tracks a background video-file analysis run. The uploaded video is
    processed frame-by-frame through the same YOLO + event-grouping
    pipeline used for live cameras (see
    app/services/video_analysis_service.py); the resulting Detection
    rows are tagged source="Video Analysis" and linked back here via
    Detection.video_analysis_job_id.
    """
    __tablename__ = "video_analysis_jobs"

    id = Column(Integer, primary_key=True, index=True)

    original_filename = Column(String(256), nullable=False)
    status = Column(String(16), nullable=False, default="queued")  # queued|processing|completed|failed|cancelled

    total_frames = Column(Integer, nullable=True)
    processed_frames = Column(Integer, nullable=False, default=0)
    progress_percent = Column(Float, nullable=False, default=0.0)
    source_fps = Column(Float, nullable=True)

    event_count = Column(Integer, nullable=False, default=0)
    error_message = Column(String(1024), nullable=True)

    cancel_requested = Column(Boolean, nullable=False, default=False)

    created_at = Column(UTCDateTime, default=lambda: datetime.now(timezone.utc))
    started_at = Column(UTCDateTime, nullable=True)
    completed_at = Column(UTCDateTime, nullable=True)
