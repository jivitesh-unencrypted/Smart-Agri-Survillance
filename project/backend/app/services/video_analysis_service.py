"""
Background video-file analysis. Runs in its own thread (registered in
the in-process JOB_REGISTRY below) so the upload endpoint can return
immediately with a job id, and the frontend polls
GET /api/video-analysis/jobs/{id} for progress.

Reuses the exact same detector + event-grouping pipeline as live
cameras (CameraEventTracker) - the only difference is the frame
source is a finite video file instead of a live stream, so we know
`total_frames` up front and can report real progress.
"""
import threading
import time
from pathlib import Path
from typing import Dict, Optional

import cv2

from app.core.config import settings
from app.core.database import SessionLocal
from app.detection.registry import get_detector
from app.models.video_job import VideoAnalysisJob
from app.services.detection_service import CameraEventTracker

# In-process registry so /cancel can signal a running thread. Jobs are
# not persisted across a backend restart (a restart interrupts any
# job in flight - its DB row is left in "processing" and should be
# treated as stale/failed by the frontend if seen after a restart).
_JOB_THREADS: Dict[int, threading.Thread] = {}


def start_job(job_id: int, file_path: Path):
    thread = threading.Thread(target=_run_job, args=(job_id, file_path), daemon=True)
    _JOB_THREADS[job_id] = thread
    thread.start()


def request_cancel(job_id: int) -> bool:
    db = SessionLocal()
    try:
        job = db.get(VideoAnalysisJob, job_id)
        if job is None or job.status not in ("queued", "processing"):
            return False
        job.cancel_requested = True
        db.commit()
        return True
    finally:
        db.close()


def _update_job(job_id: int, **fields):
    db = SessionLocal()
    try:
        job = db.get(VideoAnalysisJob, job_id)
        if job is None:
            return
        for k, v in fields.items():
            setattr(job, k, v)
        db.commit()
    finally:
        db.close()


def _is_cancel_requested(job_id: int) -> bool:
    db = SessionLocal()
    try:
        job = db.get(VideoAnalysisJob, job_id)
        return bool(job and job.cancel_requested)
    finally:
        db.close()


def _read_detection_settings() -> dict:
    from app.models.settings import AppSettings
    db = SessionLocal()
    try:
        row = db.get(AppSettings, 1)
        if row is None:
            row = AppSettings(id=1)
            db.add(row)
            db.commit()
            db.refresh(row)
        return {
            "confidence_threshold": row.confidence_threshold,
            "iou_threshold": row.iou_threshold,
            "frame_skip": row.frame_skip,
            "event_cooldown_seconds": row.event_cooldown_seconds,
            "snapshot_on_event": row.snapshot_on_event,
        }
    finally:
        db.close()


def _run_job(job_id: int, file_path: Path):
    from datetime import datetime, timezone

    _update_job(job_id, status="processing", started_at=datetime.now(timezone.utc))

    detector = get_detector()
    if detector is None:
        _update_job(job_id, status="failed", error_message="YOLO model is not loaded on the server.",
                     completed_at=datetime.now(timezone.utc))
        _cleanup(file_path)
        return

    cap = cv2.VideoCapture(str(file_path))
    if not cap.isOpened():
        _update_job(job_id, status="failed", error_message="Could not open the uploaded video file.",
                     completed_at=datetime.now(timezone.utc))
        _cleanup(file_path)
        return

    total_frames = int(cap.get(cv2.CAP_PROP_FRAME_COUNT)) or None
    source_fps = cap.get(cv2.CAP_PROP_FPS) or None
    _update_job(job_id, total_frames=total_frames, source_fps=source_fps)

    cfg = _read_detection_settings()
    tracker = CameraEventTracker(
        camera_id=None,
        camera_name=file_path.name,
        location="Uploaded Video",
        video_analysis_job_id=job_id,
    )

    frame_index = 0
    last_progress_push = 0.0
    event_count = 0

    def _on_new_event(payload, is_new):
        nonlocal event_count
        if is_new:
            event_count += 1

    try:
        while True:
            if _is_cancel_requested(job_id):
                _update_job(job_id, status="cancelled", completed_at=datetime.now(timezone.utc))
                return

            ret, frame = cap.read()
            if not ret or frame is None:
                break  # end of video

            frame_index += 1
            frame_skip = max(cfg["frame_skip"], 0)
            due = (frame_skip == 0) or (frame_index % (frame_skip + 1) == 0)

            if due:
                annotated, detections, counts, _inference_ms = detector.detect_frame(
                    frame,
                    conf_threshold=cfg["confidence_threshold"],
                    iou_threshold=cfg["iou_threshold"],
                )
                tracker.process_detections(
                    detections,
                    annotated,
                    cooldown_seconds=cfg["event_cooldown_seconds"],
                    snapshot_on_event=cfg["snapshot_on_event"],
                    source="Video Analysis",
                    on_new_event=_on_new_event,
                )

            now = time.monotonic()
            if total_frames and (now - last_progress_push) >= 0.5:
                last_progress_push = now
                progress = min(99.0, (frame_index / total_frames) * 100.0)
                _update_job(job_id, processed_frames=frame_index, progress_percent=progress,
                            event_count=event_count)

        tracker.close_all()
        _update_job(
            job_id,
            status="completed",
            processed_frames=frame_index,
            progress_percent=100.0,
            event_count=event_count,
            completed_at=datetime.now(timezone.utc),
        )
    except Exception as e:  # noqa: BLE001 - a failed analysis job should never crash the server
        _update_job(job_id, status="failed", error_message=str(e)[:1000],
                    completed_at=datetime.now(timezone.utc))
    finally:
        cap.release()
        _cleanup(file_path)
        _JOB_THREADS.pop(job_id, None)


def _cleanup(file_path: Path):
    """Uploaded source videos are temporary - only the logged events/snapshots persist."""
    try:
        if file_path.exists():
            file_path.unlink()
    except Exception:
        pass
