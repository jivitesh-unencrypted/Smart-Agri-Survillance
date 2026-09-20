from datetime import datetime, timezone

from sqlalchemy import Column, Integer, String, ForeignKey, Boolean, Index
from sqlalchemy.orm import relationship

from app.core.database import Base
from app.core.types import UTCDateTime


class Alert(Base):
    __tablename__ = "alerts"

    id = Column(Integer, primary_key=True, index=True)

    detection_id = Column(Integer, ForeignKey("detections.id", ondelete="SET NULL"), nullable=True)
    camera_id = Column(Integer, ForeignKey("cameras.id", ondelete="SET NULL"), nullable=True, index=True)
    camera_name = Column(String(128), nullable=True)

    category = Column(String(32), nullable=True)
    severity = Column(String(16), nullable=False, default="normal", index=True)  # critical|warning|info|normal
    title = Column(String(128), nullable=False)
    message = Column(String(512), nullable=False)

    acknowledged = Column(Boolean, default=False, nullable=False)
    resolved = Column(Boolean, default=False, nullable=False)

    created_at = Column(UTCDateTime, default=lambda: datetime.now(timezone.utc), index=True)
    resolved_at = Column(UTCDateTime, nullable=True)

    camera = relationship("Camera", back_populates="alerts")

    __table_args__ = (
        Index("ix_alerts_resolved_created", "resolved", "created_at"),
    )
