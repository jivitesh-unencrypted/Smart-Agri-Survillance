import re
import uuid

from fastapi import APIRouter, Depends, File, HTTPException, UploadFile
from sqlalchemy.orm import Session

from app.api.deps import get_current_user
from app.core.config import settings
from app.core.database import get_db
from app.models.user import User
from app.models.video_job import VideoAnalysisJob
from app.schemas.video_job import VideoAnalysisJobListResponse, VideoAnalysisJobOut
from app.services import video_analysis_service

router = APIRouter(prefix="/api/video-analysis", tags=["video-analysis"])

ALLOWED_EXTENSIONS = {".mp4", ".avi", ".mov", ".mkv", ".webm", ".m4v"}
# No artificial cap on detections/frames processed once uploaded, per the
# "no artificial limits" requirement - this only guards against an
# obviously wrong/corrupt upload (e.g. someone picking a non-video file).
MAX_UPLOAD_BYTES = 2 * 1024 * 1024 * 1024  # 2 GB sanity ceiling, not a feature limit


def _safe_suffix(filename: str) -> str:
    suffix = "".join(ch for ch in (filename.rsplit(".", 1)[-1] if "." in filename else "")
                      if ch.isalnum()).lower()
    return f".{suffix}" if suffix else ""


@router.post("/upload", response_model=VideoAnalysisJobOut, status_code=201)
async def upload_video(
    file: UploadFile = File(...),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    original_name = file.filename or "upload.mp4"
    ext = _safe_suffix(original_name)
    if ext not in ALLOWED_EXTENSIONS:
        raise HTTPException(status_code=422, detail=f"Unsupported video format '{ext}'. "
                                                      f"Allowed: {', '.join(sorted(ALLOWED_EXTENSIONS))}")

    safe_name = re.sub(r"[^\w\-. ]", "_", original_name)[:150]

    job = VideoAnalysisJob(original_filename=safe_name, status="queued")
    db.add(job)
    db.commit()
    db.refresh(job)

    dest_path = settings.uploads_dir / f"job{job.id}_{uuid.uuid4().hex[:8]}{ext}"

    size = 0
    try:
        with open(dest_path, "wb") as out:
            while chunk := await file.read(1024 * 1024):
                size += len(chunk)
                if size > MAX_UPLOAD_BYTES:
                    raise HTTPException(status_code=413, detail="Video file is too large.")
                out.write(chunk)
    except HTTPException:
        dest_path.unlink(missing_ok=True)
        db.delete(job)
        db.commit()
        raise
    except Exception:
        dest_path.unlink(missing_ok=True)
        db.delete(job)
        db.commit()
        raise HTTPException(status_code=500, detail="Failed to save uploaded video.")

    video_analysis_service.start_job(job.id, dest_path)
    return job


@router.get("/jobs", response_model=VideoAnalysisJobListResponse)
def list_jobs(db: Session = Depends(get_db), current_user: User = Depends(get_current_user)):
    items = db.query(VideoAnalysisJob).order_by(VideoAnalysisJob.created_at.desc()).limit(50).all()
    total = db.query(VideoAnalysisJob).count()
    return VideoAnalysisJobListResponse(items=items, total=total)


@router.get("/jobs/{job_id}", response_model=VideoAnalysisJobOut)
def get_job(job_id: int, db: Session = Depends(get_db), current_user: User = Depends(get_current_user)):
    job = db.get(VideoAnalysisJob, job_id)
    if job is None:
        raise HTTPException(status_code=404, detail="Job not found")
    return job


@router.post("/jobs/{job_id}/cancel")
def cancel_job(job_id: int, current_user: User = Depends(get_current_user)):
    ok = video_analysis_service.request_cancel(job_id)
    if not ok:
        raise HTTPException(status_code=400, detail="Job is not running or does not exist")
    return {"status": "cancel_requested"}
