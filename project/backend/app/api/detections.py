from datetime import datetime
from typing import Optional

from fastapi import APIRouter, Depends, Query
from sqlalchemy import func
from sqlalchemy.orm import Session

from app.api.deps import get_current_user
from app.core.database import get_db
from app.models.detection import Detection
from app.models.user import User
from app.schemas.detection import DetectionListResponse, DetectionOut, DetectionSummary

router = APIRouter(prefix="/api/detections", tags=["detections"])


@router.get("", response_model=DetectionListResponse)
def list_detections(
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
    page: int = Query(1, ge=1),
    page_size: int = Query(25, ge=1, le=200),
    source: Optional[str] = None,
    category: Optional[str] = None,
    severity: Optional[str] = None,
    camera_id: Optional[int] = None,
    date_from: Optional[datetime] = None,
    date_to: Optional[datetime] = None,
    search: Optional[str] = None,
):
    q = db.query(Detection)
    if source:
        q = q.filter(Detection.source == source)
    if category:
        q = q.filter(Detection.category == category)
    if severity:
        q = q.filter(Detection.severity == severity)
    if camera_id:
        q = q.filter(Detection.camera_id == camera_id)
    if date_from:
        q = q.filter(Detection.created_at >= date_from)
    if date_to:
        q = q.filter(Detection.created_at <= date_to)
    if search:
        like = f"%{search.lower()}%"
        q = q.filter(func.lower(Detection.object_name).like(like))

    total = q.count()
    items = (
        q.order_by(Detection.created_at.desc())
        .offset((page - 1) * page_size)
        .limit(page_size)
        .all()
    )
    return DetectionListResponse(items=items, total=total, page=page, page_size=page_size)


@router.get("/summary", response_model=DetectionSummary)
def detections_summary(db: Session = Depends(get_db), current_user: User = Depends(get_current_user)):
    total = db.query(func.count(Detection.id)).scalar() or 0
    human = db.query(func.count(Detection.id)).filter(Detection.category == "Human").scalar() or 0
    animal = db.query(func.count(Detection.id)).filter(Detection.category == "Animals").scalar() or 0
    vehicle = db.query(func.count(Detection.id)).filter(Detection.category == "Vehicles").scalar() or 0
    other = db.query(func.count(Detection.id)).filter(Detection.category == "Others").scalar() or 0
    return DetectionSummary(
        total_events=total, human_events=human, animal_events=animal,
        vehicle_events=vehicle, other_events=other,
    )
