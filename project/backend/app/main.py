import asyncio
import logging

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from fastapi.staticfiles import StaticFiles

from app.api import alerts, analytics, auth, cameras, detections, settings as settings_api, system, video_analysis
from app.camera.stream_manager import StreamManager
from app.core.config import settings
from app.core.database import init_db
from app.detection.registry import load_detector
from app.seed import seed_defaults
from app.websocket.routes import router as websocket_router

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(name)s: %(message)s")
logger = logging.getLogger("smart_agri_surveillance")

app = FastAPI(
    title=settings.APP_NAME,
    version=settings.APP_VERSION,
    description="Local, self-hosted AI surveillance API. No paid services, no cloud AI, no request limits.",
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origins_list,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.exception_handler(Exception)
async def unhandled_exception_handler(request: Request, exc: Exception):
    logger.exception("Unhandled error on %s %s", request.method, request.url.path)
    return JSONResponse(status_code=500, content={"detail": "Internal server error. Check the server logs."})


@app.on_event("startup")
async def on_startup():
    logger.info("Starting %s v%s", settings.APP_NAME, settings.APP_VERSION)

    init_db()
    seed_defaults()

    load_detector()
    from app.detection.registry import get_load_error
    if get_load_error():
        logger.warning("YOLO model failed to load: %s", get_load_error())
    else:
        logger.info("YOLO model loaded from %s", settings.resolved_model_path)

    loop = asyncio.get_event_loop()
    app.state.stream_manager = StreamManager(loop)
    logger.info("Backend ready.")


@app.on_event("shutdown")
async def on_shutdown():
    logger.info("Shutting down - stopping all camera streams...")
    if hasattr(app.state, "stream_manager"):
        app.state.stream_manager.stop_all()


# ---------------------------------------------------------------- routers
app.include_router(auth.router)
app.include_router(cameras.router)
app.include_router(detections.router)
app.include_router(alerts.router)
app.include_router(analytics.router)
app.include_router(settings_api.router)
app.include_router(system.router)
app.include_router(video_analysis.router)
app.include_router(websocket_router)

# Serve saved snapshots/recordings directly (read-only, local network use).
app.mount("/storage", StaticFiles(directory=str(settings.storage_dir)), name="storage")


@app.get("/")
def root():
    return {"name": settings.APP_NAME, "version": settings.APP_VERSION, "status": "running"}
