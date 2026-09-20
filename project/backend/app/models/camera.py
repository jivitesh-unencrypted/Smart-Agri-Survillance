from datetime import datetime, timezone

from sqlalchemy import Column, Integer, String, Boolean, Float
from sqlalchemy.orm import relationship

from app.core.database import Base
from app.core.types import UTCDateTime


class Camera(Base):
    __tablename__ = "cameras"

    id = Column(Integer, primary_key=True, index=True)
    camera_code = Column(String(32), unique=True, index=True, nullable=False)  # e.g. CAM-001
    name = Column(String(128), nullable=False)
    location = Column(String(128), nullable=True)
    description = Column(String(512), nullable=True)
    zone = Column(String(128), nullable=True)

    camera_type = Column(String(64), nullable=False, default="Local Webcam")
    connection_type = Column(String(32), nullable=False, default="local_webcam")  # local_webcam | ip_camera | rtsp | http_mjpeg
    device_index = Column(Integer, nullable=True)          # for local_webcam
    stream_url = Column(String(512), nullable=True)        # for network cameras
    username = Column(String(128), nullable=True)
    # Credential is stored resolved through the same env:/obf: scheme as
    # the original project - see app/services/camera_service.py
    password = Column(String(512), nullable=True)

    enabled = Column(Boolean, default=True, nullable=False)

    # Runtime health (best-effort, updated by the background stream worker;
    # never fabricated - null/None means "not measured yet")
    status = Column(String(16), default="unknown", nullable=False)  # unknown|testing|online|offline
    last_fps = Column(Float, nullable=True)
    last_latency_ms = Column(Float, nullable=True)
    last_seen_at = Column(UTCDateTime, nullable=True)
    last_error = Column(String(512), nullable=True)

    created_at = Column(UTCDateTime, default=lambda: datetime.now(timezone.utc))
    updated_at = Column(UTCDateTime, default=lambda: datetime.now(timezone.utc),
                         onupdate=lambda: datetime.now(timezone.utc))

    detections = relationship("Detection", back_populates="camera", cascade="all, delete-orphan")
    alerts = relationship("Alert", back_populates="camera", cascade="all, delete-orphan")
