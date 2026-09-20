"""
Central application configuration, loaded from environment variables /
.env. Nothing here hits a network service - every default keeps the
app 100% local and free to run.
"""
from pathlib import Path
from typing import List

from pydantic_settings import BaseSettings, SettingsConfigDict


BASE_DIR = Path(__file__).resolve().parent.parent.parent  # backend/


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=str(BASE_DIR / ".env"), extra="ignore")

    # --- App ---
    APP_NAME: str = "Smart Agri Surveillance API"
    APP_VERSION: str = "2.0.0"

    # --- Security ---
    JWT_SECRET_KEY: str = "change-this-to-a-random-secret-key"
    JWT_ALGORITHM: str = "HS256"
    ACCESS_TOKEN_EXPIRE_MINUTES: int = 480

    # --- AI Model ---
    MODEL_PATH: str = "./models/yolov8n.pt"
    DEFAULT_CONFIDENCE_THRESHOLD: float = 0.25
    DEFAULT_IOU_THRESHOLD: float = 0.45

    # --- CORS ---
    CORS_ORIGINS: str = "http://localhost:5173,http://127.0.0.1:5173"

    # --- Database ---
    DATABASE_URL: str = "sqlite:///./database/app.db"

    @property
    def cors_origins_list(self) -> List[str]:
        return [o.strip() for o in self.CORS_ORIGINS.split(",") if o.strip()]

    # --- Paths (always resolved relative to the backend/ folder so the
    # app behaves the same regardless of the current working directory
    # it's launched from) ---
    @property
    def storage_dir(self) -> Path:
        return BASE_DIR / "storage"

    @property
    def snapshots_dir(self) -> Path:
        return self.storage_dir / "snapshots"

    @property
    def recordings_dir(self) -> Path:
        return self.storage_dir / "recordings"

    @property
    def uploads_dir(self) -> Path:
        return self.storage_dir / "uploads"

    @property
    def model_dir(self) -> Path:
        return BASE_DIR / "models"

    @property
    def database_dir(self) -> Path:
        return BASE_DIR / "database"

    @property
    def resolved_model_path(self) -> Path:
        p = Path(self.MODEL_PATH)
        if p.is_absolute():
            return p
        return (BASE_DIR / p).resolve()


settings = Settings()

# Ensure required directories exist on import (mirrors the original
# project's config.py behaviour of creating folders up front).
for folder in (settings.storage_dir, settings.snapshots_dir, settings.recordings_dir,
               settings.uploads_dir, settings.model_dir, settings.database_dir):
    folder.mkdir(parents=True, exist_ok=True)

# ------------------------------------------------------------------
# Detection category mapping (preserved from the original project)
# ------------------------------------------------------------------
CATEGORIES = {
    "Human": ["person"],
    "Animals": ["bird", "cat", "dog", "horse", "sheep", "cow", "elephant", "bear", "zebra", "giraffe"],
    "Vehicles": ["bicycle", "car", "motorcycle", "bus", "truck", "train", "boat"],
}
CATEGORY_ORDER = ["Human", "Animals", "Vehicles", "Others"]

SEVERITY_MAP = {
    "Human": "critical",
    "Animals": "warning",
    "Vehicles": "info",
    "Others": "normal",
}

CATEGORY_BOX_COLOR_BGR = {
    "Human": (0, 255, 0),
    "Animals": (0, 165, 255),
    "Vehicles": (255, 0, 0),
    "Others": (128, 128, 128),
}

# Connection types a camera can be configured with (kept identical to
# the original app's vocabulary so migrated camera data lines up).
CONNECTION_TYPE_LOCAL = "local_webcam"
CONNECTION_TYPE_IP = "ip_camera"
CONNECTION_TYPE_RTSP = "rtsp"
CONNECTION_TYPE_HTTP = "http_mjpeg"

CONNECTION_TYPES = {
    CONNECTION_TYPE_LOCAL: "Local Webcam",
    CONNECTION_TYPE_IP: "IP Camera",
    CONNECTION_TYPE_RTSP: "RTSP Stream",
    CONNECTION_TYPE_HTTP: "HTTP/MJPEG Stream",
}
NETWORK_CONNECTION_TYPES = {CONNECTION_TYPE_IP, CONNECTION_TYPE_RTSP, CONNECTION_TYPE_HTTP}

# Reconnect / event-grouping tuning (also user-configurable via /api/settings)
CAMERA_RECONNECT_ATTEMPTS = 5
DEFAULT_INFERENCE_INTERVAL_MS = 400          # run YOLO at most every N ms per camera
DEFAULT_EVENT_COOLDOWN_SECONDS = 8           # gap allowed before an event is considered "ended"
DEFAULT_SNAPSHOT_COOLDOWN_SECONDS = 5        # min seconds between snapshots for the same event
