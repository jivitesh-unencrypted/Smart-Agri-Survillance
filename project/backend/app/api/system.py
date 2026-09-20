import time

from fastapi import APIRouter, Depends, Request
from sqlalchemy import text
from sqlalchemy.orm import Session

from app.api.deps import get_current_user
from app.core.database import get_db
from app.detection.registry import get_detector, get_load_error
from app.models.camera import Camera
from app.models.user import User
from app.schemas.system import SystemStatus

router = APIRouter(prefix="/api/system", tags=["system"])

_START_TIME = time.monotonic()


@router.get("/status", response_model=SystemStatus)
def system_status(request: Request, db: Session = Depends(get_db), current_user: User = Depends(get_current_user)):
    detector = get_detector()
    total_cameras = db.query(Camera).count()
    active_cameras = len(request.app.state.stream_manager.active_camera_ids())

    database_ok = True
    try:
        db.execute(text("SELECT 1"))
    except Exception:
        database_ok = False

    return SystemStatus(
        model_loaded=detector is not None,
        model_name="YOLO11 / YOLOv8" if detector is not None else "unavailable",
        model_error=get_load_error(),
        total_cameras=total_cameras,
        active_cameras=active_cameras,
        database_ok=database_ok,
        uptime_seconds=time.monotonic() - _START_TIME,
    )


@router.get("/health")
def health():
    """Unauthenticated liveness check for local monitoring / docker healthchecks."""
    return {"status": "ok"}
