"""
One CameraStreamWorker per running camera. Runs in its own daemon
thread so many cameras can stream concurrently without blocking the
FastAPI event loop. Implements the efficient pipeline required by the
spec:

    frame -> frame skipping / inference interval -> YOLO (only when due)
          -> event grouping (detection_service) -> WebSocket broadcast

Detection does NOT run on every frame - only every `inference_interval_ms`
(and even then, every Nth frame is skipped per `frame_skip`), so a slow
CPU stays responsive and the UI stream itself is never blocked by
inference.
"""
import asyncio
import threading
import time
from datetime import datetime, timezone
from typing import Optional

import cv2
import numpy as np

from app.camera.capture import CameraCapture
from app.core.config import settings as app_settings, CAMERA_RECONNECT_ATTEMPTS
from app.core.database import SessionLocal
from app.detection.registry import get_detector
from app.models.camera import Camera
from app.models.settings import AppSettings
from app.services.detection_service import CameraEventTracker
from app.websocket.manager import broadcast_sync


def _placeholder_frame(text: str, subtitle: str = "") -> np.ndarray:
    img = np.full((480, 640, 3), (25, 30, 36), dtype=np.uint8)
    cv2.rectangle(img, (0, 0), (640, 6), (0, 140, 255), -1)
    cv2.putText(img, text, (40, 220), cv2.FONT_HERSHEY_SIMPLEX, 0.8, (255, 255, 255), 2, cv2.LINE_AA)
    if subtitle:
        cv2.putText(img, subtitle, (40, 260), cv2.FONT_HERSHEY_SIMPLEX, 0.5, (170, 180, 190), 1, cv2.LINE_AA)
    return img


class CameraStreamWorker:
    def __init__(self, camera_id: int, loop: asyncio.AbstractEventLoop):
        self.camera_id = camera_id
        self._loop = loop
        self._thread: Optional[threading.Thread] = None
        self._stop_event = threading.Event()

        self._frame_lock = threading.Lock()
        self._latest_jpeg: Optional[bytes] = None

        self._actual_fps = 0.0
        self._last_frame_mono: Optional[float] = None

        self._tracker: Optional[CameraEventTracker] = None

    # ---------------------------------------------------------- lifecycle
    def start(self):
        if self._thread is not None and self._thread.is_alive():
            return
        self._stop_event.clear()
        self._thread = threading.Thread(target=self._run, daemon=True)
        self._thread.start()

    def stop(self):
        self._stop_event.set()
        if self._thread is not None:
            self._thread.join(timeout=5)
        if self._tracker:
            self._tracker.close_all()
        self._set_camera_status("offline", message="Stopped")
        broadcast_sync(self._loop, {
            "type": "camera_status",
            "camera_id": self.camera_id,
            "status": "offline",
            "timestamp": datetime.now(timezone.utc).isoformat(),
        })

    def is_running(self) -> bool:
        return self._thread is not None and self._thread.is_alive() and not self._stop_event.is_set()

    def get_latest_jpeg(self) -> Optional[bytes]:
        with self._frame_lock:
            return self._latest_jpeg

    # ---------------------------------------------------------- DB helpers
    def _set_camera_status(self, status: str, fps: float = None, latency_ms: float = None, message: str = None):
        db = SessionLocal()
        try:
            cam = db.get(Camera, self.camera_id)
            if cam is None:
                return
            cam.status = status
            if fps is not None:
                cam.last_fps = fps
            if latency_ms is not None:
                cam.last_latency_ms = latency_ms
            if status == "online":
                cam.last_seen_at = datetime.now(timezone.utc)
            cam.last_error = message if status == "offline" else None
            db.commit()
        finally:
            db.close()

    def _load_camera_snapshot(self):
        """Reads the camera row + current settings once at (re)start."""
        db = SessionLocal()
        try:
            cam = db.get(Camera, self.camera_id)
            if cam is None:
                return None
            from app.services.camera_service import build_source
            source = build_source(cam)
            info = {
                "id": cam.id,
                "name": cam.name,
                "location": cam.location,
                "connection_type": cam.connection_type,
            }
            self._tracker = CameraEventTracker(cam.id, cam.name, cam.location or "")
            return source, info
        finally:
            db.close()

    def _read_settings(self) -> AppSettings:
        db = SessionLocal()
        try:
            row = db.get(AppSettings, 1)
            if row is None:
                row = AppSettings(id=1)
                db.add(row)
                db.commit()
                db.refresh(row)
            # Detach values we need so the session can close.
            return {
                "confidence_threshold": row.confidence_threshold,
                "iou_threshold": row.iou_threshold,
                "inference_interval_ms": row.inference_interval_ms,
                "frame_skip": row.frame_skip,
                "event_cooldown_seconds": row.event_cooldown_seconds,
                "snapshot_on_event": row.snapshot_on_event,
            }
        finally:
            db.close()

    # ---------------------------------------------------------- main loop
    def _run(self):
        loaded = self._load_camera_snapshot()
        if loaded is None:
            return
        source, camera_info = loaded

        capture = CameraCapture(source=source)
        connected = capture.connect()
        self._set_camera_status("online" if connected else "offline",
                                 message=None if connected else "Unable to open camera stream")
        broadcast_sync(self._loop, {
            "type": "camera_status",
            "camera_id": self.camera_id,
            "status": "online" if connected else "offline",
            "timestamp": datetime.now(timezone.utc).isoformat(),
        })

        reconnect_attempts = 0
        frame_counter = 0
        last_inference_mono = 0.0
        last_status_push_mono = 0.0

        try:
            while not self._stop_event.is_set():
                cfg = self._read_settings()
                ret, frame_bgr = capture.read_frame()

                if not ret or frame_bgr is None:
                    reconnect_attempts += 1
                    if reconnect_attempts <= CAMERA_RECONNECT_ATTEMPTS:
                        placeholder = _placeholder_frame(
                            "RECONNECTING...",
                            f"Attempt {reconnect_attempts} of {CAMERA_RECONNECT_ATTEMPTS}",
                        )
                        self._publish_frame(placeholder)
                        capture.reconnect()
                        time.sleep(1.0)
                        continue
                    else:
                        placeholder = _placeholder_frame("CAMERA OFFLINE", "Check stream URL / connectivity")
                        self._publish_frame(placeholder)
                        self._set_camera_status("offline", message="Camera offline - no frames received")
                        broadcast_sync(self._loop, {
                            "type": "camera_status",
                            "camera_id": self.camera_id,
                            "status": "offline",
                            "timestamp": datetime.now(timezone.utc).isoformat(),
                        })
                        time.sleep(2.0)
                        continue

                reconnect_attempts = 0
                frame_counter += 1

                # --- FPS tracking ---
                now_mono = time.monotonic()
                if self._last_frame_mono is not None:
                    delta = now_mono - self._last_frame_mono
                    if delta > 0:
                        inst_fps = 1.0 / delta
                        self._actual_fps = inst_fps if self._actual_fps == 0 else (self._actual_fps * 0.8 + inst_fps * 0.2)
                self._last_frame_mono = now_mono

                # --- Decide whether this frame gets run through YOLO ---
                frame_skip = max(cfg["frame_skip"], 0)
                interval_s = max(cfg["inference_interval_ms"], 0) / 1000.0
                due_by_interval = (now_mono - last_inference_mono) >= interval_s
                due_by_skip = (frame_skip == 0) or (frame_counter % (frame_skip + 1) == 0)

                detector = get_detector()
                annotated = frame_bgr
                inference_ms = 0.0

                if detector is not None and due_by_interval and due_by_skip:
                    last_inference_mono = now_mono
                    annotated, detections, counts, inference_ms = detector.detect_frame(
                        frame_bgr,
                        conf_threshold=cfg["confidence_threshold"],
                        iou_threshold=cfg["iou_threshold"],
                    )

                    def _on_new_event(payload, is_new):
                        broadcast_sync(self._loop, {
                            "type": "detection",
                            "camera_id": self.camera_id,
                            "is_new_event": is_new,
                            **payload,
                        })

                    def _on_alert(payload):
                        broadcast_sync(self._loop, {"type": "alert", **payload})

                    self._tracker.process_detections(
                        detections,
                        annotated,
                        cooldown_seconds=cfg["event_cooldown_seconds"],
                        snapshot_on_event=cfg["snapshot_on_event"],
                        source="Live Camera",
                        on_new_event=_on_new_event,
                        on_alert=_on_alert,
                    )

                    live_counts = self._tracker.current_counts()
                    broadcast_sync(self._loop, {
                        "type": "detection_count",
                        "camera_id": self.camera_id,
                        "counts": live_counts,
                        "total": sum(live_counts.values()),
                        "timestamp": datetime.now(timezone.utc).isoformat(),
                    })

                self._publish_frame(annotated)

                # --- Throttled telemetry / status push (~1/sec) ---
                if (now_mono - last_status_push_mono) >= 1.0:
                    last_status_push_mono = now_mono
                    self._set_camera_status("online", fps=self._actual_fps, latency_ms=inference_ms or None)
                    broadcast_sync(self._loop, {
                        "type": "fps",
                        "camera_id": self.camera_id,
                        "fps": round(self._actual_fps, 1),
                        "inference_ms": round(inference_ms, 1),
                        "timestamp": datetime.now(timezone.utc).isoformat(),
                    })
        finally:
            capture.release()

    def _publish_frame(self, frame_bgr: np.ndarray):
        ok, buf = cv2.imencode(".jpg", frame_bgr, [int(cv2.IMWRITE_JPEG_QUALITY), 80])
        if ok:
            with self._frame_lock:
                self._latest_jpeg = buf.tobytes()
