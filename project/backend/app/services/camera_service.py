from typing import Optional

from sqlalchemy.orm import Session

from app.camera.credentials import obfuscate_secret, resolve_credential, ENV_PREFIX, credential_is_set
from app.core.config import CONNECTION_TYPE_LOCAL, NETWORK_CONNECTION_TYPES
from app.models.camera import Camera


def _generate_camera_code(db: Session) -> str:
    existing_codes = {c.camera_code for c in db.query(Camera.camera_code).all()}
    n = 1
    while True:
        candidate = f"CAM-{n:03d}"
        if candidate not in existing_codes:
            return candidate
        n += 1


def list_cameras(db: Session, enabled_only: bool = False):
    q = db.query(Camera)
    if enabled_only:
        q = q.filter(Camera.enabled == True)  # noqa: E712
    return q.order_by(Camera.id.asc()).all()


def get_camera(db: Session, camera_id: int) -> Optional[Camera]:
    return db.get(Camera, camera_id)


def create_camera(db: Session, data: dict) -> Camera:
    password = data.pop("password", None)
    password_is_env = data.pop("password_is_env", False)

    if password_is_env and password:
        password_field = f"{ENV_PREFIX}{password}"
    elif password:
        password_field = obfuscate_secret(password)
    else:
        password_field = None

    connection_type = data.get("connection_type", CONNECTION_TYPE_LOCAL)
    camera = Camera(
        camera_code=_generate_camera_code(db),
        name=data["name"].strip(),
        location=(data.get("location") or "").strip(),
        description=(data.get("description") or "").strip(),
        zone=(data.get("zone") or "").strip(),
        camera_type=data.get("camera_type", "Local Webcam"),
        connection_type=connection_type,
        device_index=data.get("device_index") if connection_type == CONNECTION_TYPE_LOCAL else None,
        stream_url=(data.get("stream_url") or "").strip() if connection_type in NETWORK_CONNECTION_TYPES else "",
        username=(data.get("username") or "").strip(),
        password=password_field,
        enabled=data.get("enabled", True),
        status="unknown",
    )
    db.add(camera)
    db.commit()
    db.refresh(camera)
    return camera


def update_camera(db: Session, camera_id: int, data: dict) -> Optional[Camera]:
    camera = db.get(Camera, camera_id)
    if camera is None:
        return None

    password = data.pop("password", None)
    password_is_env = data.pop("password_is_env", False)
    keep_existing_password = data.pop("keep_existing_password", True)

    if keep_existing_password and not password:
        password_field = camera.password
    elif password_is_env and password:
        password_field = f"{ENV_PREFIX}{password}"
    elif password:
        password_field = obfuscate_secret(password)
    else:
        password_field = None

    connection_type = data.get("connection_type", camera.connection_type)

    camera.name = data.get("name", camera.name).strip()
    camera.location = (data.get("location") or "").strip()
    camera.description = (data.get("description") or "").strip()
    camera.zone = (data.get("zone") or "").strip()
    camera.camera_type = data.get("camera_type", camera.camera_type)
    camera.connection_type = connection_type
    camera.device_index = data.get("device_index") if connection_type == CONNECTION_TYPE_LOCAL else None
    camera.stream_url = (data.get("stream_url") or "").strip() if connection_type in NETWORK_CONNECTION_TYPES else ""
    camera.username = (data.get("username") or "").strip()
    camera.password = password_field
    camera.enabled = data.get("enabled", camera.enabled)

    db.commit()
    db.refresh(camera)
    return camera


def delete_camera(db: Session, camera_id: int) -> bool:
    camera = db.get(Camera, camera_id)
    if camera is None:
        return False
    db.delete(camera)
    db.commit()
    return True


def build_source(camera: Camera):
    """Resolves a Camera row to a source usable by CameraCapture."""
    if camera.connection_type == CONNECTION_TYPE_LOCAL:
        return int(camera.device_index or 0)

    url = camera.stream_url or ""
    username = camera.username or ""
    password = resolve_credential(camera.password or "")

    if username and "://" in url and "@" not in url:
        scheme, rest = url.split("://", 1)
        if password:
            url = f"{scheme}://{username}:{password}@{rest}"
        else:
            url = f"{scheme}://{username}@{rest}"
    return url


def camera_to_out_dict(camera: Camera) -> dict:
    """Builds the API-safe representation - credentials never leave the server."""
    if camera.connection_type == CONNECTION_TYPE_LOCAL:
        stream_display = f"Device index {camera.device_index if camera.device_index is not None else 0}"
    else:
        # Show the URL without embedded credentials.
        stream_display = camera.stream_url or ""

    return {
        "id": camera.id,
        "camera_code": camera.camera_code,
        "name": camera.name,
        "location": camera.location,
        "description": camera.description,
        "zone": camera.zone,
        "camera_type": camera.camera_type,
        "connection_type": camera.connection_type,
        "device_index": camera.device_index,
        "stream_url_display": stream_display,
        "username": camera.username,
        "has_password": credential_is_set(camera.password or ""),
        "enabled": camera.enabled,
        "status": camera.status,
        "last_fps": camera.last_fps,
        "last_latency_ms": camera.last_latency_ms,
        "last_seen_at": camera.last_seen_at,
        "last_error": camera.last_error,
        "created_at": camera.created_at,
        "updated_at": camera.updated_at,
    }
