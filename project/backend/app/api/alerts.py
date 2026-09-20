from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session

from app.api.deps import get_current_user
from app.core.database import get_db
from app.models.alert import Alert
from app.models.user import User
from app.schemas.alert import AlertListResponse, AlertOut, AlertUpdate

router = APIRouter(prefix="/api/alerts", tags=["alerts"])


@router.get("", response_model=AlertListResponse)
def list_alerts(
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
    resolved: Optional[bool] = None,
    severity: Optional[str] = None,
    camera_id: Optional[int] = None,
    limit: int = Query(100, ge=1, le=500),
):
    q = db.query(Alert)
    if resolved is not None:
        q = q.filter(Alert.resolved == resolved)
    if severity:
        q = q.filter(Alert.severity == severity)
    if camera_id:
        q = q.filter(Alert.camera_id == camera_id)
    total = q.count()
    items = q.order_by(Alert.created_at.desc()).limit(limit).all()
    return AlertListResponse(items=items, total=total)


@router.patch("/{alert_id}", response_model=AlertOut)
def update_alert(alert_id: int, payload: AlertUpdate, db: Session = Depends(get_db),
                  current_user: User = Depends(get_current_user)):
    from datetime import datetime, timezone
    alert = db.get(Alert, alert_id)
    if alert is None:
        raise HTTPException(status_code=404, detail="Alert not found")
    if payload.acknowledged is not None:
        alert.acknowledged = payload.acknowledged
    if payload.resolved is not None:
        alert.resolved = payload.resolved
        alert.resolved_at = datetime.now(timezone.utc) if payload.resolved else None
    db.commit()
    db.refresh(alert)
    return alert
