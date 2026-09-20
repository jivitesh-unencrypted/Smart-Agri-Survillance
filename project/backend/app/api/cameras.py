from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import StreamingResponse
from sqlalchemy.orm import Session

from app.api.deps import get_current_user
from app.camera.testing import test_connection
from app.core.database import get_db
from app.models.user import User
from app.schemas.camera import CameraCreate, CameraOut, CameraTestResult, CameraUpdate
from app.services import camera_service

router = APIRouter(prefix="/api/cameras", tags=["cameras"])


@router.get("", response_model=list[CameraOut])
def list_cameras(db: Session = Depends(get_db), current_user: User = Depends(get_current_user)):
    cameras = camera_service.list_cameras(db)
    return [camera_service.camera_to_out_dict(c) for c in cameras]


@router.post("", response_model=CameraOut, status_code=201)
def create_camera(payload: CameraCreate, db: Session = Depends(get_db),
                   current_user: User = Depends(get_current_user)):
    if payload.connection_type != "local_webcam" and not (payload.stream_url or "").strip():
        raise HTTPException(status_code=422, detail="stream_url is required for IP / RTSP / HTTP cameras")
    camera = camera_service.create_camera(db, payload.model_dump())
    return camera_service.camera_to_out_dict(camera)


@router.get("/{camera_id}", response_model=CameraOut)
def get_camera(camera_id: int, db: Session = Depends(get_db), current_user: User = Depends(get_current_user)):
    camera = camera_service.get_camera(db, camera_id)
    if camera is None:
        raise HTTPException(status_code=404, detail="Camera not found")
    return camera_service.camera_to_out_dict(camera)


@router.put("/{camera_id}", response_model=CameraOut)
def update_camera(camera_id: int, payload: CameraUpdate, db: Session = Depends(get_db),
                   current_user: User = Depends(get_current_user)):
    if payload.connection_type != "local_webcam" and not (payload.stream_url or "").strip():
        raise HTTPException(status_code=422, detail="stream_url is required for IP / RTSP / HTTP cameras")
    camera = camera_service.update_camera(db, camera_id, payload.model_dump())
    if camera is None:
        raise HTTPException(status_code=404, detail="Camera not found")
    return camera_service.camera_to_out_dict(camera)


@router.delete("/{camera_id}", status_code=204)
def delete_camera(camera_id: int, request: Request, db: Session = Depends(get_db),
                   current_user: User = Depends(get_current_user)):
    request.app.state.stream_manager.stop_camera(camera_id)
    ok = camera_service.delete_camera(db, camera_id)
    if not ok:
        raise HTTPException(status_code=404, detail="Camera not found")


@router.post("/{camera_id}/test", response_model=CameraTestResult)
def test_camera(camera_id: int, db: Session = Depends(get_db), current_user: User = Depends(get_current_user)):
    camera = camera_service.get_camera(db, camera_id)
    if camera is None:
        raise HTTPException(status_code=404, detail="Camera not found")
    source = camera_service.build_source(camera)
    result = test_connection(source)
    camera.status = "online" if result["success"] else "offline"
    if result["success"]:
        camera.last_latency_ms = result["latency_ms"]
    camera.last_error = None if result["success"] else result["message"]
    db.commit()
    return result


@router.post("/{camera_id}/start")
def start_camera(camera_id: int, request: Request, db: Session = Depends(get_db),
                  current_user: User = Depends(get_current_user)):
    camera = camera_service.get_camera(db, camera_id)
    if camera is None:
        raise HTTPException(status_code=404, detail="Camera not found")
    if not camera.enabled:
        raise HTTPException(status_code=400, detail="Camera is disabled")
    request.app.state.stream_manager.start_camera(camera_id)
    return {"status": "starting"}


@router.post("/{camera_id}/stop")
def stop_camera(camera_id: int, request: Request, current_user: User = Depends(get_current_user)):
    request.app.state.stream_manager.stop_camera(camera_id)
    return {"status": "stopped"}


@router.get("/{camera_id}/stream")
def stream_camera(camera_id: int, request: Request):
    # Note: browsers can't attach an Authorization header to an <img> src
    # request, so this endpoint is intentionally left open on the local
    # network - it only ever serves already-annotated JPEG frames, never
    # camera control. Restrict it at your network/firewall boundary for
    # anything beyond local/trusted-LAN use.
    stream_manager = request.app.state.stream_manager
    if not stream_manager.is_running(camera_id):
        raise HTTPException(status_code=409, detail="Camera is not currently running - start it first")
    return StreamingResponse(
        stream_manager.mjpeg_generator(camera_id),
        media_type="multipart/x-mixed-replace; boundary=frame",
    )
