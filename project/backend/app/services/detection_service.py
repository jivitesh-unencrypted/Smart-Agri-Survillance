"""
Detection EVENT grouping.

This is the core of requirement #6 from the spec: we must NOT create a
database row per frame. Instead, for each continuously-present object
INSTANCE, a single event row is created and then extended (end_time /
duration / confidence / frame_count bumped) in place. Only once an
instance hasn't been seen for `event_cooldown_seconds` is its event
considered finished; if it comes back afterwards, a brand new event is
created.

Multiple simultaneous instances of the SAME class (e.g. three people
in frame at once) are tracked separately, each with its own event row -
they are matched frame-to-frame by bounding-box IoU overlap against
the same class's other active instances, similar in spirit to a
simple IoU tracker (no full linear assignment/Kalman filter - greedy
best-match is enough for this use case and keeps the pipeline fast).

Thread-safety: each camera worker runs in its own thread, and every
instance key is only ever touched by that camera's worker, so a
simple per-tracker lock is enough - there's no cross-camera contention
on the same key.
"""
import threading
import time
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

import cv2

from app.core.config import settings, SEVERITY_MAP
from app.core.database import SessionLocal
from app.models.detection import Detection
from app.services import alert_service

# Two boxes of the same class across consecutive processed frames are
# considered "the same object" if their IoU is at least this. Lower
# catches fast-moving objects better but risks merging genuinely
# different objects that cross paths; this value is a reasonable
# middle ground for typical surveillance frame rates.
IOU_MATCH_THRESHOLD = 0.2


@dataclass
class _ActiveEvent:
    db_id: int
    category: str
    start_time: datetime
    last_seen_mono: float
    max_confidence: float
    conf_sum: float
    frame_count: int
    last_bbox: Tuple[float, float, float, float]
    last_snapshot_mono: float = 0.0


def _iou(box_a, box_b) -> float:
    ax1, ay1, ax2, ay2 = box_a
    bx1, by1, bx2, by2 = box_b

    inter_x1, inter_y1 = max(ax1, bx1), max(ay1, by1)
    inter_x2, inter_y2 = min(ax2, bx2), min(ay2, by2)
    inter_w, inter_h = max(0.0, inter_x2 - inter_x1), max(0.0, inter_y2 - inter_y1)
    inter_area = inter_w * inter_h
    if inter_area <= 0:
        return 0.0

    area_a = max(0.0, ax2 - ax1) * max(0.0, ay2 - ay1)
    area_b = max(0.0, bx2 - bx1) * max(0.0, by2 - by1)
    union = area_a + area_b - inter_area
    return inter_area / union if union > 0 else 0.0


class CameraEventTracker:
    """
    Owns the active-event grouping state for one source stream - either
    a live camera (camera_id set) or a video-analysis job
    (video_analysis_job_id set, camera_id left None). The grouping
    logic itself doesn't care which; it just needs somewhere to tag
    new Detection rows so they can be filtered/found again later.
    """

    def __init__(self, camera_id: Optional[int], camera_name: str, location: str,
                 video_analysis_job_id: Optional[int] = None):
        self.camera_id = camera_id
        self.camera_name = camera_name
        self.location = location
        self.video_analysis_job_id = video_analysis_job_id
        # Keyed by a synthetic per-instance id, e.g. "person#3" - NOT
        # just the object name, so multiple simultaneous instances of
        # the same class each get their own row.
        self._active: Dict[str, _ActiveEvent] = {}
        self._next_instance_seq: Dict[str, int] = {}
        self._lock = threading.Lock()

    def process_detections(
        self,
        detections: list,
        annotated_frame_bgr,
        cooldown_seconds: int,
        snapshot_on_event: bool,
        snapshot_cooldown_seconds: int = 5,
        source: str = "Live Camera",
        on_new_event=None,
        on_alert=None,
    ):
        """Call once per processed (inference) frame."""
        now_mono = time.monotonic()
        now_dt = datetime.now(timezone.utc)

        # Group this frame's raw detections by class name.
        by_name: Dict[str, List[dict]] = {}
        for det in detections:
            by_name.setdefault(det["name"], []).append(det)

        with self._lock:
            matched_instance_keys = set()

            for name, dets in by_name.items():
                # Existing active instances of this same class, available to match against.
                candidate_keys = [k for k, ev in self._active.items() if k.rsplit("#", 1)[0] == name]

                # Greedy matching: process highest-confidence detections first,
                # each claiming its best-overlapping still-unclaimed active instance.
                dets_sorted = sorted(dets, key=lambda d: d["confidence"], reverse=True)
                unclaimed_keys = set(candidate_keys)

                for det in dets_sorted:
                    bbox = tuple(det["bbox"])
                    category = det["category"]
                    confidence = det["confidence"]

                    best_key, best_iou = None, 0.0
                    for key in unclaimed_keys:
                        iou = _iou(bbox, self._active[key].last_bbox)
                        if iou > best_iou:
                            best_key, best_iou = key, iou

                    if best_key is not None and best_iou >= IOU_MATCH_THRESHOLD:
                        # Extend the matched existing instance.
                        unclaimed_keys.discard(best_key)
                        matched_instance_keys.add(best_key)
                        event = self._active[best_key]
                        event.last_seen_mono = now_mono
                        event.last_bbox = bbox
                        event.frame_count += 1
                        event.conf_sum += confidence
                        event.max_confidence = max(event.max_confidence, confidence)

                        db = SessionLocal()
                        try:
                            row = db.get(Detection, event.db_id)
                            if row is not None:
                                row.end_time = now_dt
                                row.duration_seconds = (now_dt - event.start_time).total_seconds()
                                row.confidence = event.max_confidence
                                row.avg_confidence = event.conf_sum / event.frame_count
                                row.frame_count = event.frame_count

                                if (snapshot_on_event and annotated_frame_bgr is not None
                                        and (now_mono - event.last_snapshot_mono) >= snapshot_cooldown_seconds):
                                    new_snap = _save_snapshot(annotated_frame_bgr, self.camera_id, name)
                                    if new_snap:
                                        row.snapshot_path = new_snap
                                        event.last_snapshot_mono = now_mono

                                db.commit()
                                db.refresh(row)
                                event_payload = _event_to_dict(row)
                            else:
                                event_payload = None
                        finally:
                            db.close()

                        if on_new_event and event_payload:
                            on_new_event(event_payload, is_new=False)
                    else:
                        # No matching active instance - this is a new, distinct object.
                        seq = self._next_instance_seq.get(name, 0) + 1
                        self._next_instance_seq[name] = seq
                        instance_key = f"{name}#{seq}"
                        matched_instance_keys.add(instance_key)

                        db = SessionLocal()
                        try:
                            snapshot_rel_path = None
                            if snapshot_on_event and annotated_frame_bgr is not None:
                                snapshot_rel_path = _save_snapshot(annotated_frame_bgr, self.camera_id, name)

                            row = Detection(
                                source=source,
                                camera_id=self.camera_id,
                                camera_name=self.camera_name,
                                location=self.location,
                                video_analysis_job_id=self.video_analysis_job_id,
                                object_name=name,
                                category=category,
                                severity=SEVERITY_MAP.get(category, "normal"),
                                confidence=confidence,
                                avg_confidence=confidence,
                                frame_count=1,
                                start_time=now_dt,
                                end_time=now_dt,
                                duration_seconds=0.0,
                                snapshot_path=snapshot_rel_path,
                            )
                            db.add(row)
                            db.commit()
                            db.refresh(row)
                            event_id = row.id
                            event_payload = _event_to_dict(row)
                        finally:
                            db.close()

                        self._active[instance_key] = _ActiveEvent(
                            db_id=event_id,
                            category=category,
                            start_time=now_dt,
                            last_seen_mono=now_mono,
                            max_confidence=confidence,
                            conf_sum=confidence,
                            frame_count=1,
                            last_bbox=bbox,
                            last_snapshot_mono=now_mono,
                        )

                        if on_new_event:
                            on_new_event(event_payload, is_new=True)
                        alert_payload = alert_service.create_alert_for_detection(event_payload)
                        if alert_payload and on_alert:
                            on_alert(alert_payload)

            # Close out instances not seen in this frame beyond cooldown.
            stale = [
                key for key, ev in self._active.items()
                if key not in matched_instance_keys and (now_mono - ev.last_seen_mono) >= cooldown_seconds
            ]
            for key in stale:
                del self._active[key]

    def close_all(self):
        """Called when a camera stops - finalizes any still-open events."""
        with self._lock:
            self._active.clear()
            self._next_instance_seq.clear()

    def current_counts(self) -> Dict[str, int]:
        counts = {"Human": 0, "Animals": 0, "Vehicles": 0, "Others": 0}
        with self._lock:
            for ev in self._active.values():
                counts[ev.category] = counts.get(ev.category, 0) + 1
        return counts


def _save_snapshot(frame_bgr, camera_id: Optional[int], object_name: str) -> Optional[str]:
    try:
        day_dir = datetime.now().strftime("%Y-%m-%d")
        target_dir: Path = settings.snapshots_dir / day_dir
        target_dir.mkdir(parents=True, exist_ok=True)
        cam_label = camera_id if camera_id is not None else "video"
        filename = f"cam{cam_label}_{object_name}_{datetime.now().strftime('%H%M%S_%f')}.jpg"
        target_path = target_dir / filename
        cv2.imwrite(str(target_path), frame_bgr)
        # Stored relative to storage/ so the API can serve it consistently.
        return f"snapshots/{day_dir}/{filename}"
    except Exception:
        return None


def _event_to_dict(row: Detection) -> Dict[str, Any]:
    return {
        "id": row.id,
        "source": row.source,
        "camera_id": row.camera_id,
        "camera_name": row.camera_name,
        "location": row.location,
        "object_name": row.object_name,
        "category": row.category,
        "severity": row.severity,
        "confidence": row.confidence,
        "avg_confidence": row.avg_confidence,
        "frame_count": row.frame_count,
        "start_time": row.start_time.isoformat() if row.start_time else None,
        "end_time": row.end_time.isoformat() if row.end_time else None,
        "duration_seconds": row.duration_seconds,
        "snapshot_path": row.snapshot_path,
    }
